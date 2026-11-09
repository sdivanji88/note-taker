import os
import subprocess
from pathlib import Path

# Local commands finish in well under a second; this only stops a wedged git
# (a stale lock, a hook waiting on input) from hanging a request forever.
LOCAL_TIMEOUT_S = 20.0

# The session token must not leak to git, its hooks or credential helpers.
_SECRET_ENV = ("NOTE_TAKER_TOKEN",)


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

    def __init__(
        self, repo_dir: Path, remote_url: str, branch: str, network_timeout_s: float = 60.0
    ):
        self.repo_dir = Path(repo_dir)
        self.remote_url = remote_url
        self.branch = branch
        self.network_timeout_s = network_timeout_s
        env = {k: v for k, v in os.environ.items() if k not in _SECRET_ENV}
        # No terminal prompts (there is no terminal; git would block on stdin),
        # paths are never globs, and English messages so push can recognise a
        # rejected (non-fast-forward) push in stderr.
        env.update(GIT_TERMINAL_PROMPT="0", GIT_LITERAL_PATHSPECS="1", LC_ALL="C")
        self._env = env

    def _exec(self, argv: list[str], timeout_s: float) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                argv, check=False, capture_output=True, text=True,
                stdin=subprocess.DEVNULL, env=self._env, timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            name = argv[3] if argv[1] == "-C" else argv[1]
            raise GitError(f"git {name} timed out after {timeout_s:g}s") from None

    def _run(
        self, *args: str, check: bool = True, timeout_s: float | None = None
    ) -> subprocess.CompletedProcess:
        r = self._exec(
            ["git", "-C", str(self.repo_dir), *args],
            LOCAL_TIMEOUT_S if timeout_s is None else timeout_s,
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
        r = self._exec(
            ["git", "clone", "--branch", self.branch, "--", self.remote_url, str(self.repo_dir)],
            self.network_timeout_s,
        )
        if r.returncode != 0:
            raise GitError(r.stderr)

    def check_remote(self, timeout_s: float | None = None) -> None:
        r = self._exec(
            ["git", "ls-remote", "--exit-code", "--heads", "--", self.remote_url, self.branch],
            self.network_timeout_s if timeout_s is None else timeout_s,
        )
        if r.returncode != 0:
            raise GitError(r.stderr or f"branch {self.branch!r} not found on remote")

    def is_dirty(self, books_dir: str) -> bool:
        # Untracked files elsewhere in the clone are the user's business and must
        # not block a push; only files that could collide with ours matter.
        if self._run("status", "--porcelain", "--untracked-files=no").stdout.strip():
            return True
        # Explicit =all: a user config of showUntrackedFiles=no would hide the very
        # files rollback could otherwise delete.
        out = self._run("status", "--porcelain", "--untracked-files=all", "--", books_dir).stdout
        return any(line.startswith("??") for line in out.splitlines())

    def current_branch(self) -> str | None:
        """The checked-out branch, or None for a detached HEAD."""
        r = self._run("symbolic-ref", "--quiet", "--short", "HEAD", check=False)
        if r.returncode == 1:  # --quiet: exit 1 means detached, anything else is an error
            return None
        if r.returncode != 0:
            raise GitError(r.stderr)
        return r.stdout.strip()

    def origin_url(self) -> str | None:
        # The URL as configured, not `git remote get-url`: that applies the user's
        # insteadOf rewrites, so a clone made from the configured URL would not match it.
        r = self._run("config", "--get", "remote.origin.url", check=False)
        return r.stdout.strip() if r.returncode == 0 else None

    def head(self) -> str:
        return self._run("rev-parse", "HEAD").stdout.strip()

    def fetch(self, timeout_s: float | None = None) -> None:
        self._run("fetch", "origin", timeout_s=timeout_s or self.network_timeout_s)

    def pull_rebase(self, timeout_s: float | None = None) -> None:
        self.fetch(timeout_s)
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
        r = self._run("push", "origin", refspec, check=False, timeout_s=self.network_timeout_s)
        if r.returncode == 0:
            return
        # Only a lost race is worth retrying; auth/network errors won't change.
        if "rejected" not in r.stderr and "fetch first" not in r.stderr:
            raise GitError(r.stderr)
        self.pull_rebase()
        self._run("push", "origin", refspec, timeout_s=self.network_timeout_s)

    def _repo_relative(self, path: Path) -> str:
        """Repo-relative posix path, or ValueError if it escapes the repo.

        Resolves symlinks on the parent (not the final component) so legitimate
        paths survive macOS /var -> /private/var and a symlinked leaf is never
        followed out of the repo by a later unlink.
        """
        root = self.repo_dir.resolve()
        p = Path(path)
        abs_path = p if p.is_absolute() else root / p
        resolved = abs_path.parent.resolve() / abs_path.name
        try:
            rel = resolved.relative_to(root)
        except ValueError:
            raise ValueError(f"path outside repo: {path}") from None
        if rel == Path(".") or (resolved.is_dir() and not resolved.is_symlink()):
            raise ValueError(f"not a file path: {path}")
        return rel.as_posix()

    def _exists_at(self, rev: str, rel: str) -> bool:
        # ls-tree exits 0 with empty output for an absent path, so a non-zero exit
        # is a real git error and must not be mistaken for "did not exist".
        r = self._run("ls-tree", "--name-only", rev, "--", rel)
        return bool(r.stdout.strip())

    def rollback(self, pre_head: str, touched: list[Path]) -> None:
        # Mixed reset (never --hard) drops only our commit and keeps the working
        # tree, so unrelated user files survive. A rebase may have pulled other
        # people's changes into the tree; those paths differ between pre_head and
        # HEAD (and are clean by the dirty-tree precondition), so they are restored
        # too. Everything is validated and planned before the first mutation.
        rels = {self._repo_relative(p) for p in touched}
        diff = self._run("diff", "--name-only", "--no-renames", "-z", pre_head, "HEAD")
        rels.update(name for name in diff.stdout.split("\0") if name)
        plan = {rel: self._exists_at(pre_head, rel) for rel in sorted(rels)}

        self._run("reset", "--mixed", pre_head)
        for rel, existed in plan.items():
            if existed:
                self._run("checkout", pre_head, "--", rel)
            else:
                target = self.repo_dir / rel
                if target.is_file() or target.is_symlink():
                    target.unlink()

    def remote_file(self, rel_path: str) -> str | None:
        r = self._run("show", f"origin/{self.branch}:{rel_path}", check=False)
        return r.stdout if r.returncode == 0 else None
