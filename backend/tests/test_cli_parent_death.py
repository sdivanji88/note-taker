import io
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

from note_taker import __main__ as cli


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_flag_is_parsed_and_off_by_default():
    assert cli.build_parser().parse_args(["--port", "1", "--data-dir", "d"]).exit_on_stdin_eof is False
    args = cli.build_parser().parse_args(["--port", "1", "--data-dir", "d", "--exit-on-stdin-eof"])
    assert args.exit_on_stdin_eof is True


class _Server:
    should_exit = False


def test_stdin_eof_asks_server_to_exit_then_hard_exits_after_grace():
    server, exits = _Server(), []
    t = cli.watch_parent_stdin(server, io.StringIO(""), grace_s=0.05, exit_fn=exits.append)
    t.join(2)
    assert server.should_exit is True
    assert exits == [1]  # the server never stopped, so the last-resort exit fired


def test_watcher_is_a_daemon_thread():
    # A daemon thread cannot keep a cleanly-stopped server's process alive, so the
    # grace-period hard exit only ever fires when shutdown is actually stuck.
    t = cli.watch_parent_stdin(_Server(), io.StringIO(""), grace_s=0, exit_fn=lambda c: None)
    assert t.daemon


def _spawn(tmp_path, *extra):
    port = _free_port()
    env = {**os.environ, "NOTE_TAKER_TOKEN": "t"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "note_taker", "--port", str(port), "--data-dir", str(tmp_path / "d"), *extra],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
    )
    req = urllib.request.Request(f"http://127.0.0.1:{port}/health", headers={"X-Session-Token": "t"})
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            urllib.request.urlopen(req, timeout=1)
            return proc
        except Exception:  # noqa: BLE001  # any connect/HTTP error just means "not up yet"
            if proc.poll() is not None:
                pytest.fail("backend exited during startup")
            time.sleep(0.2)
    proc.kill()
    pytest.fail("backend never became healthy")


def test_closing_stdin_stops_a_flagged_backend(tmp_path):
    proc = _spawn(tmp_path, "--exit-on-stdin-eof")
    try:
        proc.stdin.close()
        assert proc.wait(timeout=10) is not None
    finally:
        proc.kill()


def test_closing_stdin_does_not_stop_an_unflagged_backend(tmp_path):
    proc = _spawn(tmp_path)
    try:
        proc.stdin.close()
        time.sleep(2)
        assert proc.poll() is None
    finally:
        proc.kill()
        proc.wait()
