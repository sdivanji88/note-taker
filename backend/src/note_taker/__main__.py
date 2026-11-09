import argparse
import logging
import os
from pathlib import Path

import uvicorn

from note_taker.api.app import AppConfig, create_app
from note_taker.redact import RedactingFilter


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # On the handler, not a logger, so it sees every module's records (git stderr from
    # the push service, uvicorn's access log with ?token=) after formatting args.
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(RedactingFilter())


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="note_taker", description="note-taker local backend")
    parser.add_argument("--port", type=int, required=True)
    # Env is preferred: an argv token is visible to other local users in `ps`.
    parser.add_argument("--token", help="fallback for NOTE_TAKER_TOKEN (visible in `ps`)")
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    token = os.environ.get("NOTE_TAKER_TOKEN") or args.token
    if not token:
        parser.error("a session token is required: set NOTE_TAKER_TOKEN (or pass --token)")

    _configure_logging()
    app = create_app(AppConfig(data_dir=args.data_dir, token=token))
    # 127.0.0.1 only: the API is for the local Electron app, never the network.
    # log_config=None leaves uvicorn's loggers propagating to our redacting handler.
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_config=None)


if __name__ == "__main__":
    main()
