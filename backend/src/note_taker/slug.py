import re
import unicodedata


def slugify(title: str) -> str:
    # Stable ASCII-only slug: it names the book's file, so it must never depend on locale
    # or on characters a filesystem/git remote might mangle.
    ascii_only = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    # Apostrophes are dropped (not turned into '-') so "Cirkovic's" stays one word.
    no_quotes = ascii_only.replace("'", "").replace("’", "")
    slug = re.sub(r"[^a-z0-9]+", "-", no_quotes.lower()).strip("-")
    return slug or "untitled"
