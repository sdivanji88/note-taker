import hmac
import logging
import re
from urllib.parse import parse_qs

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

log = logging.getLogger(__name__)

# <img> and EventSource cannot send custom headers, so only these two GET routes
# accept the token as a query parameter. Everything else needs the header, which
# keeps the token out of URLs (history, logs) wherever possible.
_QUERY_TOKEN_PATHS = (
    re.compile(r"^/captures/[^/]+/image$"),
    re.compile(r"^/batches/[^/]+/events$"),
)


class SessionTokenMiddleware:
    """Pure ASGI (not BaseHTTPMiddleware) so streaming SSE responses pass through untouched.

    Sits inside CORSMiddleware: a CORS preflight carries no token and is answered
    before it gets here. The token, not CORS, is the security boundary.
    """

    def __init__(self, app: ASGIApp, token: str):
        self.app = app
        self._token = token.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self._authorized(scope):
            await self.app(scope, receive, send)
            return
        log.warning("rejected request without a valid session token: %s %s", scope["method"], scope["path"])
        response = JSONResponse(
            {"error": {"code": "unauthorized", "message": "missing or invalid session token"}},
            status_code=401,
        )
        await response(scope, receive, send)

    def _authorized(self, scope: Scope) -> bool:
        presented = Headers(scope=scope).get("x-session-token")
        if presented is None and any(p.match(scope["path"]) for p in _QUERY_TOKEN_PATHS):
            values = parse_qs(scope.get("query_string", b"").decode("latin-1")).get("token")
            presented = values[0] if values else None
        if presented is None:
            return False
        return hmac.compare_digest(presented.encode(), self._token)
