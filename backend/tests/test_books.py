import pytest

from note_taker.books import BookCatalog, BookNotFound
from note_taker.models import Kind


@pytest.fixture
def repo(tmp_path):
    return tmp_path / "clone"


@pytest.fixture
def catalog(data_paths, repo):
    return BookCatalog(data_paths, lambda: repo, lambda: "books")


def write_book(repo, slug, text):
    (repo / "books").mkdir(parents=True, exist_ok=True)
    (repo / "books" / f"{slug}.md").write_text(text, encoding="utf-8")


def test_lists_repo_and_pending_books(catalog, repo):
    write_book(repo, "zen", "---\ntitle: Zen\nauthor: A\nkind: fiction\n---\n\nbody\n")
    catalog.create("Atomic Habits", "James Clear", Kind.non_fiction)
    books = catalog.list()
    assert [(b.slug, b.title, b.pending) for b in books] == [
        ("atomic-habits", "Atomic Habits", True),
        ("zen", "Zen", False),
    ]
    assert books[1].author == "A" and books[1].kind == Kind.fiction


def test_missing_books_dir_and_pending_file_means_no_books(catalog):
    assert catalog.list() == []


def test_create_existing_slug_returns_repo_book(catalog, repo, data_paths):
    write_book(repo, "dune", "---\ntitle: Dune\nauthor: Frank\nkind: fiction\n---\n")
    book = catalog.create("Dune", "Someone Else", Kind.non_fiction)
    assert (book.slug, book.author, book.kind, book.pending) == ("dune", "Frank", Kind.fiction, False)
    assert not data_paths.pending_books_file.exists()


def test_create_existing_pending_returns_pending_book(catalog):
    first = catalog.create("Dune", "Frank", Kind.fiction)
    again = catalog.create("Dune", "Other", Kind.non_fiction)
    assert again == first and first.pending
    assert len(catalog.list()) == 1


def test_pending_visible_across_catalog_instances(catalog, data_paths, repo):
    catalog.create("Dune", "Frank", Kind.fiction)
    other = BookCatalog(data_paths, lambda: repo, lambda: "books")
    assert [b.slug for b in other.list()] == ["dune"]
    assert other.get("dune").pending is True


def test_repo_wins_over_pending_in_list(catalog, repo):
    catalog.create("Dune", "Frank", Kind.fiction)
    write_book(repo, "dune", "---\ntitle: Dune\nkind: fiction\n---\n")
    books = catalog.list()
    assert len(books) == 1 and books[0].pending is False


def test_prune_pending_after_file_exists(catalog, repo, data_paths):
    catalog.create("Dune", "Frank", Kind.fiction)
    catalog.create("Emma", "Jane", Kind.fiction)
    write_book(repo, "dune", "---\ntitle: Dune\nkind: fiction\n---\n")
    catalog.prune_pending()
    assert [b.slug for b in BookCatalog(data_paths, lambda: repo, lambda: "books").list() if b.pending] == ["emma"]


def test_prune_pending_without_pending_file_is_noop(catalog, data_paths):
    catalog.prune_pending()
    assert not data_paths.pending_books_file.exists()


@pytest.mark.parametrize(
    "text",
    [
        "no frontmatter here\n",
        "---\n: : [bad yaml\n---\n",
        "---\ntitle: X\nkind: poetry\n---\n",
        "---\nauthor: nobody\n---\n",
    ],
)
def test_bad_frontmatter_falls_back_to_stem(catalog, repo, text):
    write_book(repo, "my-book", text)
    (book,) = catalog.list()
    assert book.slug == "my-book"
    assert book.kind == Kind.non_fiction
    assert book.title in ("my-book", "X")


def test_bad_frontmatter_title_is_stem_when_unusable(catalog, repo):
    write_book(repo, "my-book", "garbage")
    assert catalog.list()[0].title == "my-book"


def test_non_utf8_book_file_does_not_crash(catalog, repo):
    (repo / "books").mkdir(parents=True)
    (repo / "books" / "bin.md").write_bytes(b"\xff\xfe\x00bad")
    assert catalog.list()[0].title == "bin"


def test_settings_callables_reevaluated(data_paths, tmp_path):
    state = {"repo": tmp_path / "a", "dir": "books"}
    cat = BookCatalog(data_paths, lambda: state["repo"], lambda: state["dir"])
    write_book(tmp_path / "a", "one", "---\ntitle: One\nkind: fiction\n---\n")
    assert [b.slug for b in cat.list()] == ["one"]
    state["repo"] = tmp_path / "b"
    assert cat.list() == []
    (tmp_path / "b" / "notes").mkdir(parents=True)
    (tmp_path / "b" / "notes" / "two.md").write_text("---\ntitle: Two\nkind: fiction\n---\n")
    state["dir"] = "notes"
    assert [b.slug for b in cat.list()] == ["two"]


def test_get_unknown_raises(catalog):
    with pytest.raises(BookNotFound):
        catalog.get("nope")


def test_book_path(catalog, repo):
    assert catalog.book_path("dune") == repo / "books" / "dune.md"


BAD_SLUGS = ["..", "../x", "a/b", "", "Dune", "/etc/passwd", "a--b", "-a", "a-"]


@pytest.mark.parametrize("slug", BAD_SLUGS)
def test_get_rejects_unsafe_slug(catalog, slug):
    with pytest.raises(BookNotFound):
        catalog.get(slug)


@pytest.mark.parametrize("slug", BAD_SLUGS)
def test_book_path_rejects_unsafe_slug(catalog, slug):
    with pytest.raises(ValueError):
        catalog.book_path(slug)
