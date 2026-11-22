import re
from datetime import tzinfo
from pathlib import Path

import yaml

from note_taker.models import Book, Capture, Highlight, Source

# Anchored to a whole line: highlight text is always "> "-prefixed, so quoted text can
# never forge a marker and cause a real highlight to be skipped.
_MARKER_RE = re.compile(r"^<!-- nt:highlight=(\S+) -->$", re.MULTILINE)


def _one_line(s: str) -> str:
    # A newline in a heading or title would end the Markdown heading and turn the rest
    # into body text (or a different heading level). str.split() covers every line separator.
    return " ".join(s.split())


def _note_block(note: str) -> str:
    # Continuation lines are indented so no line of a note can start at column 0, which is
    # the only place a marker is recognised. splitlines() (not split("\n")) because the
    # marker check normalises \r and \r\n, and other Unicode separators render as breaks.
    # Their own leading whitespace is dropped: on top of our 2 spaces it would reach 4 (or a
    # tab) and render as a code block. lstrip() on the note also keeps leading blank lines
    # from leaving "**Note:** " dangling with nothing after it.
    first, *rest = note.lstrip().splitlines()
    return "\n".join(
        [f"**Note:** {first}", *(f"  {line.lstrip()}" if line.strip() else "" for line in rest)]
    )


def _heading(capture: Capture, tz: tzinfo) -> str:
    parts = []
    if capture.page is not None:
        parts.append(f"p.{capture.page}")
    if chapter := _one_line(capture.chapter or ""):
        parts.append(chapter)
    parts.append(capture.captured_at.astimezone(tz).strftime("%Y-%m-%d %H:%M"))
    return "## " + " · ".join(parts)


def render_section(capture: Capture, highlight: Highlight, tz: tzinfo) -> str:
    lines = [_heading(capture, tz), ""]
    if capture.source == Source.kindle:
        lines += ["*Source: Kindle*", ""]
    # Prefix every line (blank ones become a bare ">") so the text can't escape the
    # blockquote and be parsed as headings, lists or rules.
    lines += [f"> {line}" if line else ">" for line in highlight.text.splitlines() or [""]]
    lines.append("")
    if highlight.note and highlight.note.strip():
        lines += [_note_block(highlight.note), ""]
    lines.append(f"<!-- nt:highlight={highlight.id} -->")
    return "\n".join(lines) + "\n"


def render_new_file(book: Book) -> str:
    meta = {"title": book.title, "author": book.author, "kind": str(book.kind.value)}
    # allow_unicode keeps non-ASCII titles readable in the user's notes repo.
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
    return f"---\n{front}---\n\n# {_one_line(book.title)}\n"


def read_frontmatter(text: str) -> dict | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 3)
    if end == -1:
        return None
    try:
        data = yaml.safe_load(text[4:end + 1])
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def existing_marker_ids(text: str) -> set[str]:
    return set(_MARKER_RE.findall(text))


def append_highlights(
    path: Path, book: Book, items: list[tuple[Capture, Highlight]], tz: tzinfo
) -> list[str]:
    # Bytes, not read_text(): universal-newline translation would hide CRLF/CR from us.
    raw = path.read_bytes() if path.exists() else None
    # An empty or blank file has no frontmatter to preserve, so it is treated as missing and
    # gets the header; otherwise the book would never get a title or kind.
    if raw is not None and not raw.strip():
        raw = None
    # Normalised copy for marker detection only; never written back.
    seen = (
        existing_marker_ids(raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n"))
        if raw is not None
        else set()
    )
    fresh = [(c, h) for c, h in sorted(items, key=lambda ch: ch[0].captured_at) if h.id not in seen]
    if not fresh:
        return []
    body = "\n".join(render_section(c, h, tz) for c, h in fresh)
    path.parent.mkdir(parents=True, exist_ok=True)
    if raw is None:
        path.write_bytes((render_new_file(book) + "\n" + body).encode("utf-8"))
    else:
        # Append-only so user hand-edits survive byte-for-byte and a crash can't truncate
        # the file. New sections use LF regardless of the file's existing newline style.
        lead = "\n" if raw.endswith(b"\n") else "\n\n"
        with path.open("ab") as f:
            f.write((lead + body).encode("utf-8"))
    return [h.id for _, h in fresh]
