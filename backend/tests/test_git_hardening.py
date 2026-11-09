"""Subprocess hardening: git never blocks forever, never prompts, never sees the token."""

import time
from pathlib import Path

import pytest
from api_helpers import H, put_settings

from note_taker import git_publisher, push_service
from note_taker.api import routes_system
from note_taker.git_publisher import GitError, GitPublisher
from note_taker.models import Settings
from note_taker.push_service import PushService


@pytest.fixture
def shim(tmp_path, monkeypatch):
    """Put a fake `git` first on PATH whose body is the given shell script."""

    def _install(body: str) -> None:
        bin_dir = tmp_path / "shim-bin"
        bin_dir.mkdir(exist_ok=True)
        script = bin_dir / "git"
        script.write_text(f"#!/bin/sh\n{body}\n")
        script.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")

    return _install


def _pub(tmp_path: Path, **kw) -> GitPublisher:
    repo = tmp_path / "clone"
    (repo / ".git").mkdir(parents=True, exist_ok=True)
    return GitPublisher(repo, "https://example.invalid/notes.git", "main", **kw)


def test_network_command_times_out(tmp_path, shim):
    shim("exec sleep 10")
    pub = _pub(tmp_path, network_timeout_s=0.5)
    start = time.monotonic()
    with pytest.raises(GitError, match="git ls-remote timed out after 0.5s"):
        pub.check_remote()
    assert time.monotonic() - start < 5


def test_check_remote_timeout_override(tmp_path, shim):
    shim("exec sleep 10")
    pub = _pub(tmp_path)
    start = time.monotonic()
    with pytest.raises(GitError, match="timed out"):
        pub.check_remote(timeout_s=0.5)
    assert time.monotonic() - start < 5


def test_pull_rebase_timeout_override(tmp_path, shim):
    shim("exec sleep 10")
    pub = _pub(tmp_path)
    start = time.monotonic()
    with pytest.raises(GitError, match="git fetch timed out"):
        pub.pull_rebase(timeout_s=0.5)
    assert time.monotonic() - start < 5


def test_local_command_times_out(tmp_path, shim, monkeypatch):
    shim("exec sleep 10")
    monkeypatch.setattr(git_publisher, "LOCAL_TIMEOUT_S", 0.5)
    with pytest.raises(GitError, match="git rev-parse timed out"):
        _pub(tmp_path).head()


def test_clone_times_out(tmp_path, shim):
    shim("exec sleep 10")
    pub = GitPublisher(tmp_path / "new", "https://example.invalid/n.git", "main", network_timeout_s=0.5)
    with pytest.raises(GitError, match="git clone timed out"):
        pub.clone()


def test_child_env_has_no_token_and_never_prompts(tmp_path, shim, monkeypatch):
    monkeypatch.setenv("NOTE_TAKER_TOKEN", "s3cret")
    monkeypatch.delenv("GIT_TERMINAL_PROMPT")
    # The shim also proves stdin is not inherited: `read` gets EOF at once.
    shim('read -r line; echo "stdin=[$line]"; env')
    out = _pub(tmp_path).head()
    assert "NOTE_TAKER_TOKEN" not in out
    assert "s3cret" not in out
    assert "GIT_TERMINAL_PROMPT=0" in out.splitlines()
    assert "GIT_LITERAL_PATHSPECS=1" in out.splitlines()
    assert "LC_ALL=C" in out.splitlines()
    assert "stdin=[]" in out.splitlines()


@pytest.mark.usefixtures("no_osd")
def test_health_remote_check_uses_its_own_short_timeout(client, shim, monkeypatch):
    put_settings(client, remote_url="https://example.invalid/notes.git")
    monkeypatch.setattr(routes_system, "_HEALTH_REMOTE_TIMEOUT_S", 0.5)
    shim("exec sleep 10")
    start = time.monotonic()
    remote = client.get("/health", headers=H).json()["remote"]
    assert remote["ok"] is False
    assert "timed out" in remote["detail"]
    assert time.monotonic() - start < 5


def test_sync_uses_its_own_short_timeout(tmp_path, shim, monkeypatch):
    # Only fetch hangs; status reports a clean clone so sync gets as far as the pull.
    shim('case "$*" in *fetch*) exec sleep 10;; esac; exit 0')
    monkeypatch.setattr(push_service, "_SYNC_TIMEOUT_S", 0.5)
    pub = _pub(tmp_path)
    svc = PushService(None, None, lambda: pub, Settings, None, None)
    start = time.monotonic()
    svc.sync()  # swallows the timeout: a listing never fails because of the remote
    assert time.monotonic() - start < 5
