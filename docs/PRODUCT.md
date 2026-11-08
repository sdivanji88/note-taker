# Product — note-taker

> Why this project exists, who it serves, and what's in/out of scope. Update when the user story or scope changes.

## Intent

Note Taker is a local macOS desktop app that turns highlights from books into a personal, git-backed knowledge base. The user photographs yellow-highlighted pages of physical books (or pastes Kindle highlight text), drops a batch of photos into an Electron app, reviews and edits drafts extracted by a configurable OCR (Tesseract) or local vision model (Ollama), and pushes approved highlights as markdown sections appended to one file per book (`books/<slug>.md`) in a GitHub repo they own, so they can recall a book's takeaways and apply them at work.

## Primary user story

As a reader of fiction and work-related non-fiction who marks paper books with a highlighter and margin notes, when I finish a reading session I want to drop my page photos into one app, fix what the extractor got wrong, and push them to my notes repo, so that every takeaway from a book is in one markdown file I can reread later.

## Jobs to be done

- When I finish a reading session with photos of highlighted pages, I want to drop them all in at once and fix the drafts, so that my takeaways land in my notes repo without retyping.
- When I highlight in Kindle, I want to paste the highlight into the same review flow, so that physical and Kindle reading end up in one place.
- When I want to apply a work book (e.g. *A Philosophy of Software Design*), I want one markdown file per book, so that I can reread every takeaway in one sitting.

## Scope

### In scope

- Batch upload of PNG/JPEG page photos; Kindle highlight paste
- Extraction of highlighted text only, handwritten margin note, printed page number (Ollama vision model or Tesseract + highlight color mask, configurable)
- One-page-at-a-time review/edit with approve/discard
- Append highlights as markdown sections to `books/<slug>.md` in the user's GitHub repo; one commit per push
- Batch lifecycle: several open batches, delete on done, 30-day expiry (configurable) with warning

### Out of scope

- Search, tagging or browsing inside the app (the repo is the reading surface)
- Importing Kindle "My Clippings" / exported notebooks
- Phone capture, cloud extractors, multi-user/sync, HEIC input
- Committing photos to the notes repo
- Packaging/distribution (dev-mode run in v1)

## Success metrics

How we'd know this is working in production:

- **Adoption:** The single user uses it for every reading session that produces highlights
- **Engagement:** Highlights pushed per week; how often the user rereads `books/*.md`
- **Reliability:** No duplicate or lost highlights across retries/crashes; no half-reviewed batches piling up; local data dir stays small
- **Performance:** see [RELIABILITY.md](RELIABILITY.md)

## Feature inventory

The canonical list of features lives in [feature_list.json](../feature_list.json). Each feature has a `status` (`pass` / `partial` / `todo` / `fail`) and concrete `evidence`. Keep that file in sync with reality.

## Roadmap

1. Plan Phase 1 (backend, Tasks 1–11)
2. Plan Phase 2 (desktop app, Tasks 12–16)
3. Choose the default Ollama model using real photos
4. Post-v1 candidates: Kindle clippings import, HEIC, phone capture

## Non-users / anti-personas

Not for teams, sharing, or public publishing; not a reading app or a general OCR/document scanner. Single reader, own repo.
