import base64
import logging
from pathlib import Path

import httpx
from pydantic import ValidationError

from note_taker.extractors.base import ExtractionError, HealthStatus
from note_taker.imaging import downscaled_jpeg_bytes
from note_taker.models import ExtractionResult

log = logging.getLogger(__name__)

# Tuned later against real photos; keep the wording stable until then.
PROMPT = (
    "This is a photo of a printed book page. Return ONLY text that is marked with a highlighter "
    "(usually yellow), as separate passages in reading order, transcribed exactly. Ignore "
    "unhighlighted text. If there is handwritten text in the margins, return it as `note`. "
    "Return the printed page number as `page` and the chapter title as `chapter` if a running "
    "header shows it; otherwise null."
)

# bbox is deliberately absent: vision models give poor pixel coordinates, and asking for
# them degrades the text, which is what matters. The overlay it feeds is optional.
_FORMAT = {
    "type": "object",
    "properties": {
        "highlights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
        "note": {"type": ["string", "null"]},
        "page": {"type": ["integer", "null"]},
        "chapter": {"type": ["string", "null"]},
    },
    "required": ["highlights"],
}

_HEALTH_TIMEOUT_S = 3.0
_CONNECT_TIMEOUT_S = 5.0


class OllamaVisionExtractor:
    def __init__(self, base_url: str, model: str, timeout_s: float = 180):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.name = f"ollama:{model}"

    def health(self) -> HealthStatus:
        try:
            resp = httpx.get(f"{self.base_url}/api/tags", timeout=_HEALTH_TIMEOUT_S)
            resp.raise_for_status()
            names = {m.get("name") for m in resp.json().get("models", [])}
        except (httpx.HTTPError, ValueError, AttributeError):
            # Includes a non-Ollama server answering on the port: to the user it is the same thing.
            return HealthStatus(ok=False, detail=f"Ollama not reachable at {self.base_url}")
        # Ollama lists untagged pulls as "<name>:latest".
        if self.model in names or f"{self.model}:latest" in names:
            return HealthStatus(ok=True, detail="ok")
        return HealthStatus(ok=False, detail=f"model {self.model} not pulled (run: ollama pull {self.model})")

    def extract(self, image_path: Path, rotation: int = 0) -> ExtractionResult:
        try:
            image_b64 = base64.b64encode(downscaled_jpeg_bytes(image_path, rotation=rotation)).decode()
        except OSError as exc:
            raise ExtractionError("could not read the photo") from exc
        body = {
            "model": self.model,
            "stream": False,
            "format": _FORMAT,
            "options": {"temperature": 0},
            "messages": [{"role": "user", "content": PROMPT, "images": [image_b64]}],
        }
        data = self._chat(body)
        return self._parse(data)

    def _chat(self, body: dict) -> dict:
        # The queue cannot kill a hung extract() thread, so this client must give up first.
        timeout = httpx.Timeout(self.timeout_s, connect=min(_CONNECT_TIMEOUT_S, self.timeout_s))
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(f"{self.base_url}/api/chat", json=body)
            resp.raise_for_status()
            data = resp.json()
        except httpx.TimeoutException as exc:
            raise ExtractionError(f"timed out after {self.timeout_s:g}s waiting for {self.name}") from exc
        except httpx.ConnectError as exc:
            raise ExtractionError(f"Ollama not reachable at {self.base_url}") from exc
        except httpx.HTTPStatusError as exc:
            raise ExtractionError(f"Ollama returned HTTP {exc.response.status_code}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ExtractionError("Ollama request failed") from exc
        if not isinstance(data, dict):
            raise ExtractionError("Ollama returned an unexpected response")
        return data

    @staticmethod
    def _parse(data: dict) -> ExtractionResult:
        # Model output is untrusted text: anything that isn't the shape we asked for is a failure
        # of this capture, never an exception for the caller to interpret.
        try:
            content = data["message"]["content"]
            payload = ExtractionResult.model_validate_json(content)
        except (KeyError, TypeError, ValidationError) as exc:
            log.warning("unusable Ollama output: %s", type(exc).__name__)
            raise ExtractionError("the model did not return usable JSON") from exc
        payload.highlights = [
            h.model_copy(update={"text": h.text.strip()}) for h in payload.highlights if h.text.strip()
        ]
        payload.raw = data
        return payload
