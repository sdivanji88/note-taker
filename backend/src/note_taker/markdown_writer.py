import re
from datetime import tzinfo
from pathlib import Path

import yaml

from note_taker.models import Book, Capture, Highlight, Source

# Anchored to a whole line: highlight text is always "> "-prefixed, so quoted text can
# never forge a marker and cause a real highlight to be skipped.
_MARKER_RE = re.compile(r"^<!-- nt:highlight=(\S+) -->$", re.MULTILINE)


def _heading(capture: Capture, tz: tzinfo) -> str:
    parts = []
    if capture.page is not None:
        parts.append(f"p.{capture.page}")
    if capture.chapter:
        parts.append(capture.chapter)
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
        lines += [f"**Note:** {highlight.note}", ""]
    lines.append(f"<!-- nt:highlight={highlight.id} -->")
    return "\n".join(lines) + "\n"


def render_new_file(book: Book) -> str:
    meta = {"title": book.title, "author": book.author, "kind": str(book.kind.value)}
    # allow_unicode keeps non-ASCII titles readable in the user's notes repo.
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
    return f"---\n{front}---\n\n# {book.title}\n"


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
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    seen = existing_marker_ids(existing) if existing is not None else set()
    fresh = [(c, h) for c, h in sorted(items, key=lambda ch: ch[0].captured_at) if h.id not in seen]
    if not fresh:
        return []
    blocks = [render_section(c, h, tz) for c, h in fresh]
    # Existing text is never rewritten (user hand-edits survive); we only add to its tail.
    base = render_new_file(book) if existing is None else existing
    if not base.endswith("\n"):
        base += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((base + "\n" + "\n".join(blocks)).encode("utf-8"))
    return [h.id for _, h in fresh]
