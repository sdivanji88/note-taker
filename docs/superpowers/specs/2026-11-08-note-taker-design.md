# Note Taker — Design

Date: 2026-11-08
Status: Approved for planning
Next steps: `/superpowers:writing-plans` on this document, then `/generate-agent-harness:generate-agent-harness` for session handoff artifacts.

Legend used throughout: **[user]** = decided by the user in the design interview. **[call]** = designer's call, open to the builder/user to revisit.

---

## 1. Intent and why

The user reads both fiction (e.g. *Permutation City*, tracking plot points) and work-related non-fiction (e.g. *A Philosophy of Software Design*, *Measure What Matters*, *Engineering Management for the Rest of Us*). They want a quick way to **recall their takeaways from a book and apply them at work**. They've already experienced this payoff: lessons from *A Philosophy of Software Design* were easy to reuse because the book was read on Kindle, where highlights are digital.

Physical books lose that. The user marks paper books with a yellow highlighter and sometimes writes a handwritten margin note (e.g. "Insurance fraud is a main plot point?" next to a highlighted passage on p.163). Sometimes there's no note, only highlights.

Note Taker turns those highlights, from photos of physical pages or pasted Kindle text, into **one markdown file per book in a git repo the user owns**, so a book's takeaways can be reread in one place.

## 2. Goals, non-goals, anti-goals

### Goals
- Turn a photo (PNG/JPEG) of a highlighted physical page into structured highlights: highlighted text only (not the whole page), the handwritten margin note if present, and the printed page number. **[user]**
- Accept Kindle highlights as pasted text through the same review flow. **[user]**
- Save each highlight with: book, date & time, page (optional), chapter (optional), user note (optional). **[user]**
- Let the user review and edit every draft before anything is written to git. **[user]**
- Upload many photos at once (one reading session = one batch). **[user]**
- Write to a GitHub repo the user specifies. **[user]**
- Extractor is configurable: OCR or a vision model. **[user]**

### Non-goals (v1) **[call]**
- Search, tagging, or browsing highlights inside the app (the repo + any markdown viewer is the reading surface).
- Importing Kindle's "My Clippings.txt" / exported notebooks.
- Capturing directly from a phone (photos are moved to the Mac by the user, e.g. AirDrop / Photos export).
- Cloud extractors (OpenAI, Anthropic, Google Vision, etc.).
- Multi-user, sync, or accounts.
- HEIC input (user specified PNG/JPEG; HEIC can be added later).
- Storing photos in the notes repo.

### Anti-goals (what would make it a failure even if it works) **[user]**
- **Piles of half-reviewed batches** accumulating out of sight.
- **Local storage that keeps growing.** The local store must only ever hold in-progress work; the notes repo is the long-term record.

## 3. User flow **[user]** unless marked

1. While reading, the user photographs highlighted pages. Nothing else happens.
2. Later, on their Mac, they open the Electron app and **drop many photos at once**, creating a **batch**.
3. **Batch grid screen** (chosen layout "B: grid first, then step through"):
   - Drop zone ("Drop photos here or click to choose").
   - "Book for all" selector for the batch (pick an existing book or create one).
   - Thumbnail grid; each thumbnail shows status: pending, extracting (…), ready (✓), failed (✗ + reason).
   - Extraction runs in the background as soon as photos land.
   - The user can remove bad/duplicate shots before reviewing.
   - "Review 1 of N →" opens the review screen.
4. **Review screen** (chosen layout "A: one page at a time"):
   - Header: book selector (overrides the batch default for this capture) and the active extractor (shown, switchable in settings).
   - Left: the photo; **[call]** highlighted regions outlined if the extractor returns boxes.
   - Right: editable fields: Highlight text, My note, Page, Chapter, Captured (date & time).
   - **[call]** If a page has several separate highlighted passages, each appears as its own highlight block, and the user can add or remove blocks.
   - Navigation ◀ k of N ▶. Actions: Discard, Save draft (implicit autosave is fine), Approve.
   - "Push all approved" writes approved captures to the repo.
5. **Kindle path**: in a batch, "Add Kindle highlight" opens the same review editor with no photo. The user pastes the text and fills in note/page/chapter. **[call]** One batch can mix photos and Kindle pastes.
6. On app open, **unfinished batches are listed** with Resume / Discard, plus expiry warnings. **[call]**

### Batch lifecycle **[user]**
- **Several batches may be open at once.**
- When a batch is pushed successfully, **its local files and photos are deleted**.
- **Uncommitted batches expire** after a configurable period, **default 30 days**, **with a warning** before deletion.
  - **[call]** The warning shows from 7 days before expiry (configurable) as a banner on app open and a badge on the batch.
  - **[call]** An expired batch is deleted only after a warning has been shown at least once (`warned_at` set). If the app wasn't opened during the warning window, the user gets the warning on the next open, and deletion happens on the following launch or janitor run no sooner than 24h later.
  - **[call]** Any edit to a batch resets `updated_at`, and expiry counts from `updated_at`.
- Discarding a batch deletes it immediately (with a confirm dialog).

## 4. Output format in the notes repo **[user]: one file per book, a section per highlight**

Path: `books/<slug>.md` in the configured notes repo. **[call]** `<slug>` = title lowercased, kebab-cased, ASCII-folded (e.g. `permutation-city`). The folder name `books/` is configurable.

```markdown
---
title: Permutation City
author: Greg Egan
kind: fiction
---

# Permutation City

## p.163 · 2026-11-08 21:14

> 'I'm sorry, I can't have explained things very well. I'm designing a planet
> that "could" exist in the Autoverse, in the broadest sense of the word. It's a
> *mathematical possibility*. But it's too large to be run on a real computer.
> It's not some VR—'
> Hayden cut her off. 'I understand that perfectly. That doesn't mean Durham's
> clients would have grasped the distinction. Technical details about the
> Autoverse aren't exactly general knowledge.'

**Note:** Insurance fraud is a main plot point?

## p.170 · Chapter 12 · 2026-11-08 21:20

> ...
```

Rules **[call]**:
- Section heading: `## ` + `p.<page>` (if any) + ` · <chapter>` (if any) + ` · YYYY-MM-DD HH:MM` (local time). If there's no page or chapter, the heading is just the timestamp.
- `source: kindle` captures add a line `*Source: Kindle*` under the heading. Photo is the default and gets no line.
- `**Note:**` line omitted when the note is empty.
- New sections are **appended** to the end of the file in `captured_at` order within the batch. Existing content is never rewritten. The user may hand-edit the file freely, and the writer only appends.
- If the file doesn't exist, it's created with frontmatter + `# Title`.
- The frontmatter is the source of truth for book metadata. The app's book list = scan of `books/*.md` frontmatter.

`captured_at` **[call]**: photo EXIF `DateTimeOriginal` (when the user was reading), falling back to file mtime, then upload time. For Kindle pastes it's the time of the paste (editable).

## 5. How it's built **[user]: Python backend, React for the Electron frontend, Ollama for vision models**

```
┌────────────────────────────────────┐
│ Electron (main) + React (renderer) │  Batch grid · Review editor · Settings
│ spawns & stops the backend         │
└──────────────┬─────────────────────┘
               │ HTTP on 127.0.0.1:<port>  (REST + SSE progress)
┌──────────────▼─────────────────────────────────────────────┐
│ Python backend (FastAPI)                                   │
│  BatchStore     batches/<id>/batch.json + photos/          │
│  Extractor ───► OllamaVisionExtractor | TesseractExtractor │
│  ExtractionQueue (background worker, per-capture jobs)     │
│  MarkdownWriter append sections to books/<slug>.md         │
│  GitPublisher   pull/commit/push the local clone           │
│  Janitor        expiry warnings + deletion                 │
└──────┬───────────────┬───────────────────┬─────────────────┘
       ▼               ▼                   ▼
   Ollama (local)   Tesseract (local)   Notes repo clone ──► GitHub
```

- **Everything runs locally. No cloud calls** except `git push`. **[call]**, inferred from choosing Ollama.
- **Backend**: Python 3.12+, FastAPI + uvicorn, Pydantic models, `uv` for env/deps. **[call]**
- **Frontend**: Electron + React + TypeScript, built with Vite. **[call]** for TS and Vite.
- **Process model [call]**: Electron main picks a free port, generates a random per-launch token, and spawns the backend with both. The backend binds to `127.0.0.1` only and requires the `X-Session-Token` header on every request. Electron kills the backend on quit.
- **Local data dir [call]**: `~/Library/Application Support/note-taker-frontend/` — Electron derives it from the frontend package name (via Electron `app.getPath('userData')`, passed to the backend):
  - `settings.json`
  - `batches/<batch_id>/batch.json` and `batches/<batch_id>/photos/<capture_id>.<ext>`
  - `repo/` is the local clone of the notes repo, unless the user points at an existing clone.
- **No database [call]**: one JSON file per batch. Deleting a batch = deleting its folder, so nothing grows unbounded (anti-goal). Writes are atomic (write temp + rename).

### 5.1 Extractors **[user]: configurable, OCR or vision model via Ollama**

Common interface:

```python
class Extractor(Protocol):
    name: str
    def health(self) -> HealthStatus: ...
    def extract(self, image_path: Path) -> ExtractionResult: ...

class ExtractedHighlight(BaseModel):
    text: str
    bbox: tuple[int, int, int, int] | None   # x, y, w, h in image px, optional

class ExtractionResult(BaseModel):
    highlights: list[ExtractedHighlight]      # may be empty
    note: str | None                          # handwritten margin note
    page: int | None                          # printed page number
    chapter: str | None                       # if a running header shows it
    raw: dict                                 # extractor-specific debug payload
```

- **OllamaVisionExtractor** (default **[call]**): sends the image (EXIF-orientation-corrected, downscaled to a max long edge of ~2000px **[call]**) with a prompt asking for only the highlighted passages, any handwritten note, the printed page number, and the chapter if visible. Uses Ollama's structured output (`format` = JSON schema) to get `ExtractionResult`. Settings: Ollama base URL (default `http://localhost:11434`) and model name. The builder picks and documents a default vision model after trying candidates (e.g. Qwen2.5-VL / Llama 3.2 Vision) against sample photos.
- **TesseractExtractor [call]**: plain OCR can't tell highlights apart, so it (1) finds highlighter regions with an OpenCV HSV color mask (yellow by default, hue range configurable), (2) OCRs only those regions with Tesseract and merges adjacent lines into passages, (3) OCRs the top/bottom margins for a page number. It does **not** read handwriting, so `note` is `None` and the user types it during review.
- A failed extraction marks the capture `failed` with an error message. The user can retry (optionally with the other extractor) or fill in the fields by hand.

### 5.2 Git publishing **[call]**
- Settings hold: remote URL, branch (default `main`), local clone path, commit author name/email (default from global git config).
- Uses the user's existing git credentials (SSH agent or credential helper) by shelling out to `git`. The app stores no tokens.
- `POST /batches/{id}/push`:
  1. `git pull --rebase` on the clone. If that fails, abort and report.
  2. For each approved capture (sorted by `captured_at`), append its highlights to the right `books/<slug>.md`, creating the file if needed.
  3. One commit per batch: `notes: <N> highlights from <book titles>`.
  4. `git push`. If it's rejected as non-fast-forward, pull --rebase and retry once.
  5. **Only after a successful push** delete the batch folder. On any failure the working tree is reset to the pre-push HEAD, the batch is kept, and the error is shown.
- Discarded captures in a batch are simply not written.

## 6. Core entities **[call]** (fields from **[user]** metadata list)

```
Settings  (settings.json, singleton)
  notes_repo: { remote_url, branch="main", local_path, books_dir="books" }
  extractor:  { kind: "ollama" | "tesseract",
                ollama: { base_url, model },
                tesseract: { highlight_hsv_range, lang="eng" } }
  batches:    { expiry_days=30, warn_days_before=7 }

Book      (lives in the notes repo, books/<slug>.md frontmatter)
  slug, title, author?, kind: "fiction" | "non-fiction"

Batch     (local, temporary: batches/<id>/batch.json)
  id (ulid), default_book_slug?, created_at, updated_at,
  status: "open" | "pushing" | "pushed" | "discarded",
  warned_at?, captures: [Capture]
  expires_at = updated_at + expiry_days      (derived)

Capture   (one photo or one Kindle paste)
  id (ulid), source: "photo" | "kindle", image_file?, image_sha256?,
  book_slug? (overrides batch default), page?, chapter?, captured_at,
  status: "pending" | "extracting" | "ready" | "failed" | "approved" | "pushed" | "discarded",
  error?, extractor_used?, highlights: [Highlight]

Highlight
  id, text, note?
  (page, chapter, captured_at, book are inherited from the Capture)

PendingBook  (global: pending_books.json in the data dir)
  slug, title, author?, kind. Removed once books/<slug>.md exists in the clone
```

Relations: Book 1—n Highlight (through Capture.book_slug, or the batch default). Batch 1—n Capture. Capture 1—n Highlight.

Capture state machine:
```
pending → extracting → ready ──approve──► approved
              │          └──discard──► discarded
              └─► failed ─retry─► extracting
                     └─manual edit─► ready
approved ─unapprove─► ready
approved ─push succeeds─► pushed
(kindle captures start at ready)
```
A capture can be approved only if it has ≥1 highlight with non-empty text and a resolved book.

## 7. API (local REST, JSON) **[call]**

All routes require the `X-Session-Token` header. Errors use `{ "error": { "code", "message" } }`.

| Method & path | Purpose |
|---|---|
| `GET /health` | Status of the extractor (Ollama reachable + model present / Tesseract installed), repo clone, and git remote |
| `GET /settings` · `PUT /settings` | Read/update settings (validated) |
| `GET /books` | List books by scanning `books/*.md` frontmatter in the clone (after a fast `git pull`, failures non-fatal), plus pending books flagged `pending: true` |
| `POST /books` | `{title, author?, kind}` → adds a PendingBook (global, visible to all batches). The file is created on the first push that uses it. If the slug already exists, return the existing book **[call]** |
| `GET /batches` | List open batches with counts by status, `expires_at`, `expiring_soon` |
| `POST /batches` | `{default_book_slug?}` → new Batch |
| `GET /batches/{id}` | Full batch with captures |
| `PATCH /batches/{id}` | `{default_book_slug}` |
| `DELETE /batches/{id}` | Discard the batch and delete its folder |
| `POST /batches/{id}/captures` | multipart `files[]` (PNG/JPEG) → creates photo captures and queues extraction; or JSON `{source:"kindle", highlights:[…], book_slug?}` |
| `GET /captures/{id}/image` | Serves the photo to the UI |
| `PATCH /captures/{id}` | Edit `highlights`, `book_slug`, `status` (approve / unapprove / discard) |
| `POST /captures/{id}/retry` | `{extractor?}` re-run extraction |
| `DELETE /captures/{id}` | Remove from the batch and delete the photo |
| `GET /batches/{id}/events` | SSE stream: `capture.status_changed`, `capture.extracted`, `batch.push_progress` |
| `POST /batches/{id}/push` | Write, commit, push, then delete the batch. Returns `{commit_sha, files_changed, highlights_written}` |
| `POST /janitor/run` | Runs expiry warnings and deletions (also runs on backend start and every 6h) |

Pending books **[call]**: a book created in the app but not yet pushed lives in the global `pending_books.json`, so every open batch can see it, until the first push that uses it writes `books/<slug>.md`. A slug collision with an existing file reuses that book.

## 8. Error handling and edge cases **[call]**
- Photos that aren't PNG/JPEG are rejected at upload with a per-file error. EXIF orientation is applied before extraction and display.
- No highlights found → capture `ready` with an empty highlights list, and the UI shows "No highlight detected. Add one manually or discard."
- Ollama not running or the model missing → `/health` reports it, uploads still succeed, captures stay `pending`, and the UI offers "Retry" once it's healthy.
- Duplicate photo (same SHA-256 already in the batch) → warn and skip.
- Push while extraction is running → only approved captures are written. Unapproved captures are left out, the batch remains with them, and it's deleted only once it's empty.
  - This refines "delete a done batch": a batch is *done* when every capture is pushed or discarded.
- App crash mid-push → `status: "pushing"` on restart triggers a check: if the commit is on the remote, mark the captures pushed and clean up. Otherwise reset to `open`.

## 9. Testing **[call]**
- Backend: pytest. Unit tests for MarkdownWriter (golden files), slugging, the Janitor (time frozen), the state machine, and BatchStore atomicity. Integration test of `/push` against a temp bare git repo as the remote. Extractors tested behind a `FakeExtractor`. Real Ollama/Tesseract tests are opt-in (`-m live`) using sample photos in `backend/tests/fixtures/` (the user should supply a few real highlighted-page photos, including the *Permutation City* p.163 example).
- Frontend: component tests (Vitest + Testing Library) for the grid and editor, and one Playwright-Electron smoke test: drop photos → review → approve → push to a temp repo.

## 10. Suggested repo layout **[call]**
```
backend/    pyproject.toml, src/note_taker/{api,store,extractors,writer,git,janitor}/, tests/
frontend/   package.json, electron/ (main, preload), src/ (React renderer)
docs/superpowers/specs/   this document
```

## 11. Left to the builder
- The default Ollama vision model and the prompt wording (pick by testing on real photos).
- Exact HSV thresholds and line-merging heuristics for the Tesseract path.
- UI styling, the settings screen layout, and keyboard shortcuts in the review editor.
- Packaging/distribution of the Electron app (dev-mode run is fine for v1). Bundling vs requiring a system Python/Tesseract (document the prerequisites).
- Polling interval details and SSE reconnection.

## 12. Builder-check resolutions **[call]**

A pre-planning review raised these. All were settled as designer's calls, and they take precedence over anything above that conflicts.

1. **Multi-highlight captures.** Page, chapter, captured_at, book and source sit on the **Capture** and are shared by all its highlights. The review editor shows them once per page, and each highlight block has its own text + note. The extractor's single `note` attaches to the first highlight, and the user can move it. The writer emits one `##` section per highlight, all with the capture's heading data.
2. **Idempotent, safe push.**
   - Each written section ends with a hidden marker `<!-- nt:highlight=<highlight_id> -->`. Before appending, the writer skips any highlight whose marker is already in the file, so retries never duplicate.
   - On success, the pushed captures become `pushed`. A batch is deleted when every capture is `pushed` or `discarded`. A later push of the same batch makes another commit, which is fine.
   - Commit message trailer: `Note-Taker-Batch: <batch_id>`.
   - **Push refuses to run if the clone has uncommitted changes or untracked files under `books/`** and tells the user. The app never runs `git reset --hard` on user work. On failure it restores only the files it touched (`git checkout -- <files>`) and drops its own unpushed commit (`git reset --soft`/`--mixed` back to the pre-push HEAD, which only works because the tree was clean beforehand).
   - Crash recovery for `pushing`: after a fetch, scan the remote branch's book files for the markers and mark the matching captures `pushed`. The rest go back to `approved`.
3. **Pending books** are global (see §6/§7).
4. **The clone.** By default the app runs `git clone <remote_url>` into `<data dir>/repo/` from the settings screen ("Connect repo"). It validates that the remote is reachable and the branch exists, and shows git's stderr on auth failure. The user may instead point at an existing clone. The same dirty-tree refusal and never-hard-reset rules then protect their work. `/health` reports the clone state.
5. **Expiry** applies to any batch that still has captures not `pushed`/`discarded`, including approved-but-unpushed ones. Expiry counts from the batch's `updated_at`. A push or edit resets it.
6. **Extraction queue.** There's a single worker with a concurrency of 1 (local VLMs are memory-hungry), configurable. It runs in FIFO order across batches, with a per-capture timeout of 180s (configurable). Captures left `pending` because the extractor was unhealthy are picked up automatically when `/health` turns healthy (checked every 30s while any are pending). Expected batch size is roughly 5–30 photos.
7. **Platform.** v1 is macOS only (the user's machine), run in dev mode. Documented prerequisites are Ollama (with the chosen model pulled), Tesseract (`brew install tesseract`), `uv`, and Node 20+. Live-extractor and Playwright-Electron tests run locally and are not required in CI.
8. **Bounding-box overlay** is nice-to-have. Draw it when `bbox` is present and drop it silently otherwise. Not required for v1 acceptance.

## 13. Decision log (for later sessions)

| # | Decision | By |
|---|---|---|
| D1 | Inputs: photos (PNG/JPEG) of physical pages, and pasted Kindle highlight text | user |
| D2 | Metadata: book, date & time, page?, chapter?, note? | user |
| D3 | Local Electron app, batch upload, edit drafts before pushing to GitHub | user |
| D4 | Extractor configurable: OCR or vision model | user |
| D5 | Review screen: one page at a time, photo left / fields right | user |
| D6 | Multi-photo upload: grid first, then step through; push all approved at the end | user |
| D7 | Output: one markdown file per book, one section per highlight | user |
| D8 | Stack: Python backend, React + Electron frontend, Ollama for vision | user |
| D9 | Several open batches allowed. Done batch → delete local files/photos. Uncommitted batches expire (default 30d, configurable) with a warning | user |
| D10 | Anti-goal: piles of half-reviewed batches, growing local storage | user |
| D11 | No database: JSON file + photos folder per batch | call |
| D12 | FastAPI on 127.0.0.1 with a per-launch session token. Electron spawns the backend | call |
| D13 | Tesseract path = yellow mask (OpenCV) + OCR of the regions only. No handwriting | call |
| D14 | Push via the local clone + the user's existing git credentials. One commit per batch. Delete only after a successful push | call |
| D15 | captured_at from photo EXIF, falling back to mtime, then upload time | call |
| D16 | One capture can yield several highlights | call |
| D17 | Photos never committed to the notes repo | call |
| D18 | Fully local. No cloud extractors in v1 | call |
| D19 | Page, chapter and time on the capture. Note per highlight. Hidden per-highlight markers make push idempotent | call |
| D20 | Push refuses on a dirty clone. Never hard-resets user work. Default clone lives in the app data dir | call |
| D21 | Extraction concurrency 1, auto-resume when the extractor is healthy. macOS-only v1 | call |
