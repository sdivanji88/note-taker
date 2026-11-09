import subprocess
from pathlib import Path


class GitError(Exception):
    def __init__(self, stderr: str):
        super().__init__(stderr)
        self.stderr = stderr


class GitPublisher:
    """Publishes notes by shelling out to the user's own `git`.

    Auth comes from the user's existing git credentials; the app stores none.
    Argument lists only (no shell), and user-supplied values (url, branch, paths)
    are placed after `--` or as option values so they can't be parsed as flags.
    """

    def __init__(self, repo_dir: Path, remote_url: str, branch: str):
        self.repo_dir = Path(repo_dir)
        self.remote_url = remote_url
        self.branch = branch

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        r = subprocess.run(
            ["git", "-C", str(self.repo_dir), *args],
            check=False, capture_output=True, text=True,
        )
        if check and r.returncode != 0:
            raise GitError(r.stderr)
        return r

    def _rel(self, path: Path) -> str:
        p = Path(path)
        return str(p.relative_to(self.repo_dir)) if p.is_absolute() else str(p)

    def is_cloned(self) -> bool:
        return (self.repo_dir / ".git").exists()

    def clone(self) -> None:
        # Not _run: the repo doesn't exist yet, so there is nothing for -C to point at.
        r = subprocess.run(
            ["git", "clone", "--branch", self.branch, "--", self.remote_url, str(self.repo_dir)],
            check=False, capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise GitError(r.stderr)

    def check_remote(self) -> None:
        r = subprocess.run(
            ["git", "ls-remote", "--exit-code", "--heads", "--", self.remote_url, self.branch],
            check=False, capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise GitError(r.stderr or f"branch {self.branch!r} not found on remote")

    def is_dirty(self, books_dir: str) -> bool:
        # Untracked files elsewhere in the clone are the user's business and must
        # not block a push; only files that could collide with ours matter.
        if self._run("status", "--porcelain", "--untracked-files=no").stdout.strip():
            return True
        out = self._run("status", "--porcelain", "--", books_dir).stdout
        return any(line.startswith("??") for line in out.splitlines())

    def head(self) -> str:
        return self._run("rev-parse", "HEAD").stdout.strip()

    def fetch(self) -> None:
        self._run("fetch", "origin")

    def pull_rebase(self) -> None:
        self.fetch()
        r = self._run("rebase", f"origin/{self.branch}", check=False)
        if r.returncode != 0:
            # Leave the clone usable for the caller's rollback.
            self._run("rebase", "--abort", check=False)
            raise GitError(r.stderr)

    def commit(self, paths: list[Path], message: str) -> str:
        self._run("add", "--", *(self._rel(p) for p in paths))
        self._run("commit", "-m", message)
        return self.head()

    def push(self) -> None:
        refspec = f"HEAD:refs/heads/{self.branch}"
        r = self._run("push", "origin", refspec, check=False)
        if r.returncode == 0:
            return
        # Only a lost race is worth retrying; auth/network errors won't change.
        if "rejected" not in r.stderr and "fetch first" not in r.stderr:
            raise GitError(r.stderr)
        self.pull_rebase()
        self._run("push", "origin", refspec)

    def rollback(self, pre_head: str, touched: list[Path]) -> None:
        # Mixed reset (never --hard) drops only our commit and keeps the working
        # tree, so unrelated user files survive; then we fix up just our paths.
        self._run("reset", "--mixed", pre_head)
        for path in touched:
            rel = self._rel(path)
            existed = self._run("cat-file", "-e", f"{pre_head}:{rel}", check=False).returncode == 0
            if existed:
                self._run("checkout", pre_head, "--", rel)
            else:
                (self.repo_dir / rel).unlink(missing_ok=True)

    def remote_file(self, rel_path: str) -> str | None:
        r = self._run("show", f"origin/{self.branch}:{rel_path}", check=False)
        return r.stdout if r.returncode == 0 else None
