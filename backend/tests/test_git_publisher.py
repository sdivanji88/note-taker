import subprocess
from pathlib import Path

import pytest

from note_taker.git_publisher import GitError, GitPublisher


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return r.stdout.strip()


@pytest.fixture
def pub(tmp_path, bare_remote) -> GitPublisher:
    p = GitPublisher(tmp_path / "clone", str(bare_remote), "main")
    p.clone()
    return p


def test_clone_and_is_cloned(tmp_path, bare_remote):
    p = GitPublisher(tmp_path / "clone", str(bare_remote), "main")
    assert not p.is_cloned()
    p.clone()
    assert p.is_cloned()
    assert (tmp_path / "clone" / "README.md").exists()
    assert len(p.head()) == 40


def test_clone_bad_branch_raises_with_stderr(tmp_path, bare_remote):
    p = GitPublisher(tmp_path / "clone", str(bare_remote), "nope")
    with pytest.raises(GitError) as e:
        p.clone()
    assert "nope" in e.value.stderr


def test_check_remote(tmp_path, bare_remote):
    GitPublisher(tmp_path / "c", str(bare_remote), "main").check_remote()
    with pytest.raises(GitError):
        GitPublisher(tmp_path / "c", str(bare_remote), "nope").check_remote()


def test_is_dirty_tracked_and_untracked_books(pub):
    repo = pub.repo_dir
    assert not pub.is_dirty("books")
    (repo / "outside.txt").write_text("x")
    assert not pub.is_dirty("books")  # untracked outside books/ is not ours
    (repo / "books").mkdir()
    (repo / "books" / "a.md").write_text("a")
    assert pub.is_dirty("books")
    (repo / "books" / "a.md").unlink()
    assert not pub.is_dirty("books")
    (repo / "README.md").write_text("changed")
    assert pub.is_dirty("books")


def test_commit_and_push_reaches_remote(pub, bare_remote):
    (pub.repo_dir / "books").mkdir()
    f = pub.repo_dir / "books" / "a.md"
    f.write_text("hello\n")
    sha = pub.commit([f], "add a")
    assert sha == pub.head()
    pub.push()
    assert git(bare_remote, "rev-parse", "main") == sha


def test_push_retries_after_non_ff(tmp_path, bare_remote, pub):
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", str(bare_remote), str(other)], check=True, capture_output=True
    )
    (other / "b.md").write_text("b")
    git(other, "add", "b.md")
    git(other, "commit", "-m", "other")
    git(other, "push", "origin", "main")

    f = pub.repo_dir / "a.md"
    f.write_text("a")
    pub.commit([f], "ours")
    pub.push()
    log = git(bare_remote, "log", "--format=%s", "main")
    assert log.splitlines()[:2] == ["ours", "other"]


def test_push_raises_git_error_when_remote_unreachable(pub, tmp_path):
    f = pub.repo_dir / "a.md"
    f.write_text("a")
    pub.commit([f], "ours")
    git(pub.repo_dir, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    with pytest.raises(GitError):
        pub.push()


def test_rollback_restores_files_and_head_without_touching_other_files(pub):
    repo = pub.repo_dir
    (repo / "books").mkdir()
    existing = repo / "books" / "old.md"
    existing.write_text("v1\n")
    pub.commit([existing], "base")
    pre = pub.head()

    existing.write_text("v1\nv2\n")
    created = repo / "books" / "new.md"
    created.write_text("new\n")
    pub.commit([existing, created], "app commit")
    unrelated = repo / "scratch.txt"
    unrelated.write_text("mine")

    pub.rollback(pre, [existing, created])

    assert pub.head() == pre
    assert existing.read_text() == "v1\n"
    assert not created.exists()
    assert unrelated.read_text() == "mine"
    assert not pub.is_dirty("books")


def test_rollback_without_commit_discards_uncommitted_app_writes(pub):
    repo = pub.repo_dir
    pre = pub.head()
    readme = repo / "README.md"
    readme.write_text("edited by app")
    created = repo / "books" / "x.md"
    created.parent.mkdir()
    created.write_text("x")
    pub.rollback(pre, [readme, created])
    assert readme.read_text() == "# notes\n"
    assert not created.exists()


def test_remote_file_after_fetch(tmp_path, bare_remote, pub):
    assert pub.remote_file("books/z.md") is None
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", str(bare_remote), str(other)], check=True, capture_output=True
    )
    (other / "books").mkdir()
    (other / "books" / "z.md").write_text("zed\n")
    git(other, "add", ".")
    git(other, "commit", "-m", "z")
    git(other, "push", "origin", "main")
    pub.fetch()
    assert pub.remote_file("books/z.md") == "zed\n"


def test_rollback_after_rebase_leaves_clone_clean(tmp_path, bare_remote, pub):
    # Simulates push rejected -> pull_rebase ok -> retry failed -> caller rolls back.
    repo = pub.repo_dir
    pre = pub.head()
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", str(bare_remote), str(other)], check=True, capture_output=True
    )
    (other / "README.md").write_text("remote edit\n")
    (other / "books").mkdir()
    (other / "books" / "theirs.md").write_text("theirs\n")
    git(other, "add", ".")
    git(other, "commit", "-m", "other")
    git(other, "push", "origin", "main")

    mine = repo / "books" / "mine.md"
    mine.parent.mkdir()
    mine.write_text("mine\n")
    pub.commit([mine], "ours")
    pub.pull_rebase()
    unrelated = repo / "scratch.txt"
    unrelated.write_text("keep")

    pub.rollback(pre, [mine])

    assert pub.head() == pre
    assert not pub.is_dirty("books")
    assert git(repo, "status", "--porcelain") == "?? scratch.txt"
    assert (repo / "README.md").read_text() == "# notes\n"
    assert not (repo / "books" / "theirs.md").exists()
    assert unrelated.read_text() == "keep"


@pytest.mark.parametrize("kind", ["dotdot", "absolute", "directory"])
def test_rollback_rejects_unsafe_paths_before_mutating(tmp_path, pub, kind):
    repo = pub.repo_dir
    victim = tmp_path / "victim.txt"
    victim.write_text("precious")
    pre = pub.head()
    (repo / "a.md").write_text("a")
    pub.commit([repo / "a.md"], "ours")
    head_before = pub.head()
    bad = {
        "dotdot": repo / ".." / "victim.txt",
        "absolute": victim,
        "directory": repo / "books",
    }[kind]
    (repo / "books").mkdir()
    with pytest.raises(ValueError):
        pub.rollback(pre, [repo / "a.md", bad])
    assert victim.read_text() == "precious"
    assert pub.head() == head_before
    assert (repo / "a.md").exists()


def test_rollback_relative_dotdot_rejected(tmp_path, pub):
    victim = tmp_path / "victim.txt"
    victim.write_text("precious")
    with pytest.raises(ValueError):
        pub.rollback(pub.head(), [Path("../victim.txt")])
    assert victim.read_text() == "precious"


def test_rollback_bad_pre_head_raises_git_error_without_mutating(pub):
    f = pub.repo_dir / "a.md"
    f.write_text("a")
    with pytest.raises(GitError):
        pub.rollback("0" * 40, [f])
    assert f.read_text() == "a"


def test_is_dirty_sees_untracked_books_despite_user_config(pub):
    git(pub.repo_dir, "config", "status.showUntrackedFiles", "no")
    (pub.repo_dir / "books").mkdir()
    (pub.repo_dir / "books" / "x.md").write_text("x")
    assert pub.is_dirty("books")
