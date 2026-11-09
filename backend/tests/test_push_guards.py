"""The app only ever pushes from (and syncs) the configured branch of the configured remote."""

import subprocess

import pytest
from api_helpers import H, connect, error_code, kindle, new_batch, put_settings, repo_path
from push_helpers import add_batch, git, push_env, remote_text

from note_taker.git_publisher import GitPublisher
from note_taker.models import Kind
from note_taker.push_service import PushError


@pytest.fixture
def env(tmp_path, data_paths, bare_remote):
    return push_env(tmp_path, data_paths, bare_remote)


def _advance_remote(tmp_path, remote) -> str:
    """Push a new commit to remote main from another clone; returns its sha."""
    other = tmp_path / "other"
    subprocess.run(["git", "clone", str(remote), str(other)], check=True, capture_output=True)
    (other / "elsewhere.md").write_text("from another machine\n")
    git(other, "add", "elsewhere.md")
    git(other, "commit", "-m", "elsewhere")
    git(other, "push", "origin", "main")
    return git(other, "rev-parse", "HEAD")


def test_current_branch_and_origin_url(env):
    pub = GitPublisher(env.clone, str(env.remote), "main")
    assert pub.current_branch() == "main"
    assert pub.origin_url() == str(env.remote)
    git(env.clone, "checkout", "--detach")
    assert pub.current_branch() is None


def test_push_refuses_wrong_branch(env):
    env.books.create("Dune", None, Kind.fiction)
    batch = add_batch(env, "dune")
    git(env.clone, "checkout", "-b", "wip")
    head = git(env.clone, "rev-parse", "wip")

    with pytest.raises(PushError) as e:
        env.svc.push(batch.id)

    assert e.value.code == "wrong_branch"
    assert "wip" in str(e.value) and "main" in str(e.value)
    assert git(env.clone, "rev-parse", "wip") == head
    assert remote_text(env) is None
    assert env.store.get(batch.id) == batch


def test_push_refuses_detached_head(env):
    env.books.create("Dune", None, Kind.fiction)
    batch = add_batch(env, "dune")
    git(env.clone, "checkout", "--detach")
    with pytest.raises(PushError) as e:
        env.svc.push(batch.id)
    assert e.value.code == "wrong_branch"


def test_push_refuses_remote_mismatch_with_masked_message(env, tmp_path):
    env.books.create("Dune", None, Kind.fiction)
    batch = add_batch(env, "dune")
    git(env.clone, "remote", "set-url", "origin", "https://me:ghp_TOKEN@example.invalid/x.git")

    with pytest.raises(PushError) as e:
        env.svc.push(batch.id)

    assert e.value.code == "remote_mismatch"
    assert "ghp_TOKEN" not in str(e.value)
    assert env.store.get(batch.id) == batch


def test_sync_does_not_rebase_a_wrong_branch(env, tmp_path):
    git(env.clone, "checkout", "-b", "wip")
    head = git(env.clone, "rev-parse", "wip")
    _advance_remote(tmp_path, env.remote)
    env.svc.sync()
    assert git(env.clone, "rev-parse", "wip") == head


def test_sync_skips_on_remote_mismatch(env, tmp_path):
    env.settings.notes_repo.remote_url = str(tmp_path / "configured-elsewhere.git")
    head = git(env.clone, "rev-parse", "HEAD")
    _advance_remote(tmp_path, env.remote)
    env.svc.sync()
    assert git(env.clone, "rev-parse", "HEAD") == head


# --- through the API -------------------------------------------------------------

pytestmark = pytest.mark.usefixtures("no_osd")


def _approved_batch(client) -> str:
    client.post("/books", headers=H, json={"title": "Dune", "kind": "fiction"})
    b = new_batch(client, default_book_slug="dune")
    c = kindle(client, b)
    client.patch(f"/captures/{c['id']}", headers=H, json={"status": "approved"})
    return b


def test_api_wrong_branch_is_409_and_books_does_not_rebase(client, bare_remote, tmp_path):
    connect(client, bare_remote)
    b = _approved_batch(client)
    repo = repo_path(client)
    git(repo, "checkout", "-b", "wip")
    head = git(repo, "rev-parse", "wip")
    _advance_remote(tmp_path, bare_remote)

    r = client.post(f"/batches/{b}/push", headers=H)
    assert r.status_code == 409
    assert error_code(r) == "wrong_branch"
    assert client.get("/books", headers=H).status_code == 200
    assert git(repo, "rev-parse", "wip") == head
    assert client.get(f"/batches/{b}", headers=H).json()["status"] == "open"


def test_api_remote_mismatch_is_409(client, bare_remote, tmp_path):
    connect(client, bare_remote)
    b = _approved_batch(client)
    git(repo_path(client), "remote", "set-url", "origin", str(tmp_path / "elsewhere.git"))
    r = client.post(f"/batches/{b}/push", headers=H)
    assert r.status_code == 409
    assert error_code(r) == "remote_mismatch"


def test_api_settings_remote_change_after_clone_is_remote_mismatch(client, bare_remote, tmp_path):
    connect(client, bare_remote)
    b = _approved_batch(client)
    put_settings(client, remote_url=str(tmp_path / "new-remote.git"))
    r = client.post(f"/batches/{b}/push", headers=H)
    assert r.status_code == 409
    assert error_code(r) == "remote_mismatch"
