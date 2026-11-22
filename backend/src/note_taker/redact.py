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
        # Tracebacks are formatted later by the handler, after this filter, and an exception
        # message can embed a remote URL. Pre-rendering into exc_text (which Formatter
        # reuses verbatim) lets us mask it, chained causes included.
        if record.exc_info and not record.exc_text:
            record.exc_text = mask_credentials(
                logging.Formatter().formatException(record.exc_info)
            )
        elif record.exc_text:
            record.exc_text = mask_credentials(record.exc_text)
        if record.stack_info:
            record.stack_info = mask_credentials(record.stack_info)
        return True
