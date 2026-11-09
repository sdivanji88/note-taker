import logging
import re

# A remote URL may embed credentials (https://user:token@host/...), and git echoes the
# URL in its stderr. The session token rides in ?token= on two routes, which uvicorn's
# access log records. Neither may ever reach a response or a log line.
_USERINFO = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://)[^/\s@]+@")
_TOKEN_PARAM = re.compile(r"([?&]token=)[^&\s\"]+")


def mask_credentials(text: str) -> str:
    return _TOKEN_PARAM.sub(r"\1***", _USERINFO.sub(r"\1***@", text))


def has_credentials(url: str) -> bool:
    return _USERINFO.search(url) is not None


class RedactingFilter(logging.Filter):
    """Masks secrets in the fully formatted message, so it covers every module's records
    (including git stderr logged by the push service) when attached to a handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        masked = mask_credentials(message)
        if masked != message:
            record.msg, record.args = masked, ()
        return True
