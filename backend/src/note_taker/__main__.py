import argparse
import logging
import os
import sys
import threading
import time
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="note_taker", description="note-taker local backend")
    parser.add_argument("--port", type=int, required=True)
    # Env is preferred: an argv token is visible to other local users in `ps`.
    parser.add_argument("--token", help="fallback for NOTE_TAKER_TOKEN (visible in `ps`)")
    parser.add_argument("--data-dir", type=Path, required=True)
    # Opt-in so a backend started by hand from a terminal is unaffected.
    parser.add_argument(
        "--exit-on-stdin-eof",
        action="store_true",
        help="shut down when stdin closes (the Electron parent holds the pipe open)",
    )
    return parser


def watch_parent_stdin(server, stdin, grace_s: float = 5.0, exit_fn=os._exit) -> threading.Thread:
    """Stop `server` when `stdin` reaches EOF, i.e. the parent exited (even via kill -9).

    Graceful first (should_exit lets uvicorn drain); the hard exit is a last resort so a
    stuck extraction cannot keep an orphaned backend alive forever. The thread is a
    daemon: if shutdown completes in time the process ends and the thread with it.
    """

    def watch() -> None:
        try:
            while stdin.read(1):
                pass
        except (OSError, ValueError):
            pass  # a broken or closed stdin means the parent is gone too
        server.should_exit = True
        time.sleep(grace_s)
        exit_fn(1)

    thread = threading.Thread(target=watch, name="parent-watch", daemon=True)
    thread.start()
    return thread


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    token = os.environ.get("NOTE_TAKER_TOKEN") or args.token
    if not token:
        parser.error("a session token is required: set NOTE_TAKER_TOKEN (or pass --token)")

    _configure_logging()
    app = create_app(AppConfig(data_dir=args.data_dir, token=token))
    # 127.0.0.1 only: the API is for the local Electron app, never the network.
    # log_config=None leaves uvicorn's loggers propagating to our redacting handler.
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port, log_config=None))
    if args.exit_on_stdin_eof:
        watch_parent_stdin(server, sys.stdin)
    server.run()


if __name__ == "__main__":
    main()
