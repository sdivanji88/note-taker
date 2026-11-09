# Architecture — note-taker

> System structure, modules, data flow, and design decisions. Update whenever module boundaries change.

## System overview

Note Taker is a local macOS desktop app that turns highlights from books into a personal, git-backed knowledge base. The user photographs yellow-highlighted pages of physical books (or pastes Kindle highlight text), drops a batch of photos into an Electron app, reviews and edits drafts extracted by a configurable OCR (Tesseract) or local vision model (Ollama), and pushes approved highlights as markdown sections appended to one file per book (`books/<slug>.md`) in a GitHub repo they own, so they can recall a book's takeaways and apply them at work.

## High-level diagram

Full design in `docs/superpowers/specs/2026-11-08-note-taker-design.md` (§5). Electron spawns a token-guarded local FastAPI backend; the backend talks to Ollama/Tesseract and a local git clone of the notes repo.

```mermaid
flowchart LR
    A[User] --> B[Electron + React UI]
    B --> C[FastAPI backend (127.0.0.1)]
    B --> D[Notes repo clone → GitHub]
    C --> E[(Datastore)]
    D --> E
```

## Modules

- **backend** (`backend/`) — FastAPI on 127.0.0.1:<random port>, token-guarded. Owns batch storage, extraction queue, markdown writer, git publishing, expiry janitor.
- **frontend** (`frontend/`) — Electron main process (spawns/stops backend) + React renderer (batch list, batch grid, review editor, settings).
- **External (local):** Ollama at `http://localhost:11434`, Tesseract binary, `git` CLI with the user's existing credentials.

For each module, document:
- **Responsibility:** one-line statement of what it owns.
- **Interface:** the narrow surface other modules use to interact with it.
- **Hidden:** what the module deliberately keeps private (data structures, algorithms, external integrations).
- **Why deep:** what complexity this module absorbs so callers don't have to.

## Data flow

1. User drops photos in BatchGrid → `POST /batches/{id}/captures` (multipart) → BatchStore writes `photos/<capture_id>.<ext>`, capture `pending` → ExtractionQueue.enqueue
2. Queue worker (concurrency 1) checks extractor health → `extract(image)` (Ollama `/api/chat` with JSON-schema `format`, or Tesseract on yellow-masked regions) → capture `ready` (or `failed`); SSE `capture.status_changed` / `capture.extracted`
3. ReviewEditor edits → `PATCH /captures/{id}` (autosave) → approve
4. "Push all approved" → `POST /batches/{id}/push` → PushService: lock → dirty check → pull --rebase → MarkdownWriter appends sections with `nt:highlight` markers → one commit (`Note-Taker-Batch:` trailer) → push → captures `pushed` → delete batch folder if finished

## Persistence model

File-based, no database. Data dir `~/Library/Application Support/note-taker-frontend/` (Electron userData; override with `NOTE_TAKER_DATA_DIR`): `settings.json`, `pending_books.json`, `batches/<id>/batch.json` + `photos/`, `repo/` (default clone).
Entities (spec §6, §12.1): Settings; Book (frontmatter of `books/<slug>.md`); PendingBook; Batch 1—n Capture; Capture 1—n Highlight. Page/chapter/captured_at/book live on Capture; text/note on Highlight. Capture states: pending → extracting → ready|failed → approved → pushed (| discarded). No migrations: models are versionless JSON in v1; add a `schema_version` field if the shape changes.

## External dependencies

- Backend: fastapi, uvicorn, pydantic, httpx, pillow, opencv-python-headless, pytesseract, pyyaml, python-ulid, sse-starlette; dev: pytest, respx, freezegun
- Frontend: electron, electron-vite, react, typescript; dev: vitest, @testing-library/react, @playwright/test
- System: Ollama, Tesseract, git, uv, Node 20+

For each, document **why** this dependency exists and **what would have to change** if it were removed.

## Design decisions (ADRs)

Record significant decisions inline here or as separate files in `docs/decisions/`. Each entry:

- **Decision:** what was decided
- **Context:** what forced the decision
- **Alternatives considered:** what else was on the table
- **Trade-offs accepted:** what we gave up

### Initial decisions

See the decision log D1–D21 in the spec (§13). Highlights: Python/FastAPI backend + Electron/React frontend + Ollama (user); JSON-per-batch store instead of a DB (call); append-only markdown with idempotency markers (call); push refuses on dirty clone, never hard-resets (call); fully local, 127.0.0.1 + per-launch token (call).

## Open architectural questions

- Default Ollama vision model and prompt (decide in plan Task 8 against real photos)
- Tesseract highlight HSV thresholds for real lighting conditions (Task 9)
- Whether `schema_version` is needed in batch.json before v1 ships

## How this doc stays accurate

Update this doc as part of the Definition of Done whenever:
- A new module is added or removed
- A module's interface changes
- Data flow changes
- A significant external dependency is added
- A design decision is reversed or refined

The `architect` subagent reads this file at the start of every non-trivial change.
