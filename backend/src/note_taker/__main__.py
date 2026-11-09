import argparse
import logging
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
    parser.add_argument("--token", required=True, help="per-launch session token from Electron")
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    _configure_logging()
    app = create_app(AppConfig(data_dir=args.data_dir, token=args.token))
    # 127.0.0.1 only: the API is for the local Electron app, never the network.
    # log_config=None leaves uvicorn's loggers propagating to our redacting handler.
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_config=None)


if __name__ == "__main__":
    main()
