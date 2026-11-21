from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import MultipartParser, parse_options_header
from starlette.requests import Request

from note_taker.api.deps import ApiError

# The form field the renderer sends photos under (accept the PHP-style name too).
_FILE_FIELDS = {"files", "files[]"}


@dataclass
class UploadedFile:
    filename: str
    data: bytes = b""
    # Set once the part passes the size cap; its bytes are dropped, not kept.
    too_large: bool = False


@dataclass
class _Part:
    headers: dict[bytes, bytes] = field(default_factory=dict)
    is_file: bool = False
    filename: str = ""
    data: bytearray = field(default_factory=bytearray)
    too_large: bool = False


class _Collector:
    """python-multipart callbacks that keep only photo parts, each capped at max_bytes.

    Starlette's form parser spools every part in full; this stops buffering a part the
    moment it passes the cap, and non-file fields are never buffered at all.
    """

    def __init__(self, max_bytes: int):
        self._max = max_bytes
        self._part = _Part()
        self._header_name = b""
        self._header_value = b""
        self.finished: list[UploadedFile] = []

    def callbacks(self) -> dict:
        return {
            "on_part_begin": self._begin,
            "on_header_field": self._header_field,
            "on_header_value": self._header_val,
            "on_header_end": self._header_end,
            "on_headers_finished": self._headers_done,
            "on_part_data": self._data,
            "on_part_end": self._end,
        }

    def _begin(self) -> None:
        self._part = _Part()

    def _header_field(self, data: bytes, start: int, end: int) -> None:
        self._header_name += data[start:end]

    def _header_val(self, data: bytes, start: int, end: int) -> None:
        self._header_value += data[start:end]

    def _header_end(self) -> None:
        self._part.headers[self._header_name.lower()] = self._header_value
        self._header_name = self._header_value = b""

    def _headers_done(self) -> None:
        _, options = parse_options_header(self._part.headers.get(b"content-disposition", b""))
        name = options.get(b"name", b"").decode("utf-8", "replace")
        if name in _FILE_FIELDS and b"filename" in options:
            self._part.is_file = True
            self._part.filename = options[b"filename"].decode("utf-8", "replace")

    def _data(self, data: bytes, start: int, end: int) -> None:
        part = self._part
        if not part.is_file or part.too_large:
            return
        if len(part.data) + (end - start) > self._max:
            part.too_large = True
            part.data = bytearray()  # release what was read so far
            return
        part.data += data[start:end]

    def _end(self) -> None:
        part = self._part
        if part.is_file:
            self.finished.append(UploadedFile(part.filename, bytes(part.data), part.too_large))
        self._part = _Part()


async def stream_files(request: Request, max_bytes: int) -> AsyncIterator[UploadedFile]:
    """Yield each uploaded photo as soon as its part is complete.

    The caller stores one file before the next is read, so at most about one
    capped file is in memory however many the request carries.
    """
    _, params = parse_options_header(request.headers.get("content-type", ""))
    boundary = params.get(b"boundary")
    if not boundary:
        raise ApiError(400, "invalid_upload", "multipart body has no boundary")
    collector = _Collector(max_bytes)
    parser = MultipartParser(boundary, collector.callbacks())
    try:
        async for chunk in request.stream():
            parser.write(chunk)
            while collector.finished:
                yield collector.finished.pop(0)
        parser.finalize()
    except MultipartParseError:
        raise ApiError(400, "invalid_upload", "malformed multipart body") from None
    while collector.finished:
        yield collector.finished.pop(0)
