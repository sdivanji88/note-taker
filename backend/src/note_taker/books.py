# The list() method shadows the builtin inside the class body; lazy annotations keep list[...] valid.
from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from note_taker.jsonio import read_json, write_json_atomic
from note_taker.markdown_writer import read_frontmatter
from note_taker.models import Book, Kind, PendingBook
from note_taker.paths import DataPaths
from note_taker.slug import slugify

# Exactly what slugify emits. Slugs name files under the repo, so anything else
# (".." or path separators in particular) must never reach the filesystem.
_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class BookNotFound(Exception):
    pass


class BookCatalog:
    """The repo is the record of which books exist; pending books bridge the gap until first push.

    repo_dir and books_dir are callables because settings can change at runtime.
    """

    def __init__(
        self, paths: DataPaths, repo_dir: Callable[[], Path], books_dir: Callable[[], str]
    ):
        self._paths = paths
        self._repo_dir = repo_dir
        self._books_dir = books_dir

    def list(self) -> list[Book]:
        by_slug = {b.slug: b for b in self._pending()}
        # Repo entries overwrite pending ones: once pushed, the file is authoritative.
        by_slug.update({b.slug: b for b in self._repo_books()})
        return sorted(by_slug.values(), key=lambda b: b.title.lower())

    def create(self, title: str, author: str | None, kind: Kind) -> Book:
        slug = slugify(title)
        for book in self.list():
            if book.slug == slug:
                return book
        pending = self._read_pending()
        pending.append(PendingBook(slug=slug, title=title, author=author, kind=kind))
        self._write_pending(pending)
        return Book(slug=slug, title=title, author=author, kind=kind, pending=True)

    def get(self, slug: str) -> Book:
        if _SLUG_RE.match(slug):
            for book in self.list():
                if book.slug == slug:
                    return book
        raise BookNotFound(slug)

    def prune_pending(self) -> None:
        pending = self._read_pending()
        kept = [p for p in pending if not self._file_exists(p.slug)]
        if len(kept) != len(pending):
            self._write_pending(kept)

    def book_path(self, slug: str) -> Path:
        if not _SLUG_RE.match(slug):
            raise ValueError(f"invalid book slug: {slug!r}")
        return self._books_path() / f"{slug}.md"

    def _books_path(self) -> Path:
        return self._repo_dir() / self._books_dir()

    def _file_exists(self, slug: str) -> bool:
        # Tolerates a corrupt pending entry: an unsafe slug simply has no file.
        return _SLUG_RE.match(slug) is not None and self.book_path(slug).exists()

    def _repo_books(self) -> list[Book]:
        directory = self._books_path()
        if not directory.is_dir():
            return []
        return [self._read_book_file(p) for p in directory.glob("*.md")]

    def _read_book_file(self, path: Path) -> Book:
        # A hand-edited or foreign file must still show up in the picker rather than break listing.
        fallback = Book(slug=path.stem, title=path.stem, kind=Kind.non_fiction)
        try:
            meta = read_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            return fallback
        if not meta:
            return fallback
        try:
            return Book(
                slug=path.stem,
                title=meta.get("title") or path.stem,
                author=meta.get("author"),
                kind=meta.get("kind", Kind.non_fiction),
            )
        except ValidationError:
            return fallback

    def _pending(self) -> list[Book]:
        return [Book(**p.model_dump(), pending=True) for p in self._read_pending()]

    def _read_pending(self) -> list[PendingBook]:
        data = read_json(self._paths.pending_books_file)
        if not data:
            return []
        try:
            return [PendingBook(**item) for item in data.get("books", [])]
        except (ValidationError, TypeError, AttributeError):
            return []

    def _write_pending(self, pending: list[PendingBook]) -> None:
        write_json_atomic(
            self._paths.pending_books_file, {"books": [p.model_dump(mode="json") for p in pending]}
        )
