from datetime import UTC, timedelta, timezone
from pathlib import Path

from note_taker.markdown_writer import (
    append_highlights,
    existing_marker_ids,
    read_frontmatter,
    render_new_file,
    render_section,
)
from note_taker.models import Book, Capture, Highlight, Kind, Source
from conftest import dt

GOLDEN = Path(__file__).parent / "golden" / "permutation-city.md"
BOOK = Book(slug="permutation-city", title="Permutation City", author="Greg Egan", kind=Kind.fiction)


def cap(page=None, chapter=None, source=Source.photo, at=None):
    return Capture(source=source, page=page, chapter=chapter, captured_at=at or dt(2026, 11, 8, 21, 14))


def hl(text="x", note=None, id="H1"):
    return Highlight(id=id, text=text, note=note)


def golden_items():
    # Deliberately out of chronological order: the writer must sort.
    later = (cap(170, "Chapter 12", at=dt(2026, 11, 8, 21, 20)), hl("Dust theory.", id="01HABC"))
    earlier = (
        cap(163),
        hl(
            "'I'm sorry, I can't have explained things very well.\n\nHayden cut her off.",
            note="Insurance fraud is a main plot point?",
            id="01HXYZ",
        ),
    )
    return [later, earlier]


def test_heading_variants():
    both = render_section(cap(170, "Chapter 12", at=dt(2026, 11, 8, 21, 20)), hl(), UTC)
    assert both.startswith("## p.170 · Chapter 12 · 2026-11-08 21:20\n")
    neither = render_section(cap(), hl(), UTC)
    assert neither.startswith("## 2026-11-08 21:14\n")
    page_only = render_section(cap(5), hl(), UTC)
    assert page_only.startswith("## p.5 · 2026-11-08 21:14\n")
    chapter_only = render_section(cap(chapter="Intro"), hl(), UTC)
    assert chapter_only.startswith("## Intro · 2026-11-08 21:14\n")


def test_heading_uses_local_tz():
    tz = timezone(timedelta(hours=-5))
    assert render_section(cap(), hl(), tz).startswith("## 2026-11-08 16:14\n")


def test_render_multiparagraph_text_stays_quoted():
    out = render_section(cap(), hl("a\n\nb"), UTC)
    assert "\n> a\n>\n> b\n" in out


def test_text_with_leading_gt_and_markdown_stays_inside_quote():
    out = render_section(cap(), hl("> nested\n\n# not a heading\n---\n- item"), UTC)
    body = out.split("\n\n", 1)[1].rsplit("\n\n", 1)[0]
    assert all(line == ">" or line.startswith("> ") for line in body.splitlines())
    assert "> > nested" in body
    assert "> # not a heading" in body


def test_kindle_source_line_and_no_empty_note():
    out = render_section(cap(source=Source.kindle), hl("t", note=""), UTC)
    assert out.startswith("## 2026-11-08 21:14\n\n*Source: Kindle*\n\n> t\n")
    assert "**Note:**" not in out
    assert "**Note:**" not in render_section(cap(), hl("t", note=None), UTC)
    assert "*Source: Kindle*" not in render_section(cap(), hl(), UTC)


def test_section_ends_with_marker():
    assert render_section(cap(), hl(id="ABC"), UTC).endswith("<!-- nt:highlight=ABC -->\n")


def test_frontmatter_with_colon_roundtrips():
    book = Book(slug="m", title="Measure What Matters: OKRs", author="John Doerr", kind="non-fiction")
    fm = read_frontmatter(render_new_file(book))
    assert fm["title"] == "Measure What Matters: OKRs"
    assert fm["kind"] == "non-fiction"


def test_frontmatter_roundtrips_awkward_titles():
    for title in ["Ćirković’s Notes", "Yes: No # maybe", "'Quoted'", '"Dq": x', "- dash", "123"]:
        book = Book(slug="s", title=title, author="A: B", kind=Kind.fiction)
        fm = read_frontmatter(render_new_file(book))
        assert fm["title"] == title and fm["author"] == "A: B"


def test_read_frontmatter_none_cases():
    assert read_frontmatter("# no frontmatter\n") is None
    assert read_frontmatter("---\n: : bad: [\n---\n") is None


def test_existing_marker_ids():
    text = "x\n<!-- nt:highlight=A -->\n\n<!-- nt:highlight=B -->\n"
    assert existing_marker_ids(text) == {"A", "B"}


def test_quoted_marker_lookalike_is_not_a_marker():
    out = render_section(cap(), hl("> <!-- nt:highlight=FAKE -->\n<!-- nt:highlight=FAKE2 -->", id="REAL"), UTC)
    assert existing_marker_ids(out) == {"REAL"}


def test_append_creates_file_matching_golden(tmp_path):
    p = tmp_path / "books" / "permutation-city.md"
    written = append_highlights(p, BOOK, golden_items(), UTC)
    assert written == ["01HXYZ", "01HABC"]
    assert p.read_text(encoding="utf-8") == GOLDEN.read_text(encoding="utf-8")


def test_append_is_idempotent(tmp_path):
    p = tmp_path / "b.md"
    items = golden_items()
    first = append_highlights(p, BOOK, items, UTC)
    snapshot = p.read_text()
    second = append_highlights(p, BOOK, items, UTC)
    assert len(first) == 2
    assert second == [] and p.read_text() == snapshot
    assert p.read_text().count("nt:highlight=") == len(items)


def test_append_only_writes_new_ids(tmp_path):
    p = tmp_path / "b.md"
    items = golden_items()
    append_highlights(p, BOOK, items[:1], UTC)
    assert append_highlights(p, BOOK, items, UTC) == ["01HXYZ"]


def test_append_preserves_user_edits(tmp_path):
    p = tmp_path / "b.md"
    append_highlights(p, BOOK, golden_items()[:1], UTC)
    edited = p.read_text() + "\nMy own thoughts, no trailing newline"
    p.write_bytes(edited.encode())
    append_highlights(p, BOOK, golden_items(), UTC)
    out = p.read_bytes()
    assert out.startswith(edited.encode())
    assert out.endswith(b"My own thoughts, no trailing newline\n\n" + render_section(*golden_items()[1], UTC).encode())


def test_append_exactly_one_blank_line_between_blocks(tmp_path):
    p = tmp_path / "b.md"
    p.write_text("---\ntitle: T\n---\n\n# T\n")
    append_highlights(p, BOOK, golden_items(), UTC)
    assert "\n\n\n" not in p.read_text()


def test_append_empty_items_writes_nothing(tmp_path):
    p = tmp_path / "b.md"
    assert append_highlights(p, BOOK, [], UTC) == []
    assert not p.exists()
