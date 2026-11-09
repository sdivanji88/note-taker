# Note Taker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local macOS Electron app that turns photos of highlighted book pages (and pasted Kindle highlights) into reviewed markdown sections, appended to one file per book in a user-owned GitHub repo.

**Architecture:**
- A Python FastAPI backend, bound to 127.0.0.1 and guarded by a per-launch token, owns everything that isn't UI:
  - per-batch JSON storage
  - pluggable extractors (Ollama vision / Tesseract+OpenCV)
  - the markdown writer
  - git publishing
  - expiry
- An Electron + React (TypeScript) frontend spawns the backend and provides the batch grid, the one-page-at-a-time review editor, and settings.
- Phase 1 (Tasks 1–11) produces a fully tested headless backend. Phase 2 (Tasks 12–16) adds the desktop UI on top of it.

**Tech Stack:**
- Backend: Python 3.12, uv, FastAPI, uvicorn, Pydantic v2, httpx, Pillow, opencv-python-headless, pytesseract, PyYAML, python-ulid, sse-starlette, pytest, respx, freezegun.
- Frontend: Node 20, electron-vite (react-ts template), React 18, TypeScript, Vitest, @testing-library/react, Playwright (`_electron`).

**Spec:** `docs/superpowers/specs/2026-11-08-note-taker-design.md`. Read it fully. §12 "Builder-check resolutions" overrides anything earlier in the spec.

## Global Constraints

- macOS only, dev-mode run. Prerequisites: Ollama, Tesseract (`brew install tesseract`), `uv`, Node 20+.
- Fully local: the only network calls are to Ollama (`http://localhost:11434` default) and `git` remotes.
- Inputs: PNG and JPEG only. Reject other types per file.
- Backend binds `127.0.0.1` only. Every request must carry the `X-Session-Token` header, or it gets a 401.
- Local data dir = Electron `app.getPath('userData')` (`~/Library/Application Support/note-taker/`), holding:
  - `settings.json`
  - `pending_books.json`
  - `batches/<id>/batch.json` + `batches/<id>/photos/<capture_id>.<ext>`
  - `repo/`
- No database. All JSON writes are atomic (write a temp file in the same dir, then `os.replace`).
- Defaults:
  - `expiry_days=30`, `warn_days_before=7`
  - delete an expired batch only if `warned_at` is ≥24h old
  - Ollama base URL `http://localhost:11434`
  - `branch="main"`, `books_dir="books"`
  - extraction concurrency 1, per-capture timeout 180s, health re-check every 30s while captures are pending
  - janitor runs on backend start and every 6h
  - downscale images to a max long edge of 2000px before Ollama
- Output file `books/<slug>.md`: YAML frontmatter `title`, `author`, `kind` (`fiction` | `non-fiction`), then `# <title>`. Sections are only ever appended.
- Section heading: `## ` + `p.<page>` (if any) + ` · <chapter>` (if any) + ` · YYYY-MM-DD HH:MM` (local time). No page and no chapter → `## YYYY-MM-DD HH:MM`.
- Each section ends with `<!-- nt:highlight=<highlight_id> -->`. A highlight whose marker is already in the file is never written again.
- Commits: one per push. Message `notes: <N> highlights from <comma-separated book titles>`, a blank line, then the trailer `Note-Taker-Batch: <batch_id>`.
- Never `git reset --hard`. Refuse to push when there are tracked changes anywhere in the clone or untracked files under `books_dir`.
- Photos are never committed to the notes repo.
- IDs are ULIDs (strings).

## Review Focus

1. **Highlight text with blank lines, a leading `>`, or markdown characters** (pasted Kindle text often has paragraph breaks). Every line, including blank ones, must stay inside the blockquote, so the section doesn't break apart. → test `test_render_multiparagraph_text_stays_quoted` in Task 3.
2. **Book titles with punctuation, colons or non-ASCII** (e.g. "Measure What Matters: OKRs", "Ćirković’s Notes"). They must give a stable ASCII slug and valid YAML frontmatter. → tests `test_slugify_cases` and `test_frontmatter_with_colon_roundtrips` in Task 3.
3. **Photos with no EXIF, with EXIF rotation, or rotated in the pixels with *no* orientation tag** (real fixture `PXL_20261109_120732142.jpg` is 4080×3072 with sideways text and EXIF orientation=1). `captured_at` must fall back to the file mtime. The image must be upright before extraction and display: EXIF first, then a detected or user-set `Capture.rotation`. → tests `test_load_upright_applies_orientation`, `test_load_upright_applies_extra_rotation`, `test_detect_rotation_on_sideways_image` and `test_captured_at_falls_back_to_mtime` in Task 7, and `test_rotate_button_patches_rotation_and_offers_retry` in Task 14.
4. **Ollama returns malformed JSON, `page` as a string like `"163"`, or no highlights.** The first becomes a `failed` capture with a readable error. The second is coerced to an int. The third becomes `ready` with an empty list, which can't be approved. → tests in Task 8 and `test_approve_requires_text_and_book` in Task 11.
5. **Two batches pushing to the same book at once** (several open batches is a user requirement). Pushes are serialized by a process-wide lock, and both sets of sections land in order without corrupting the file. → test `test_concurrent_pushes_serialize` in Task 6.

---

## File Structure

```
backend/
  pyproject.toml                         # uv project, deps, pytest config (markers: live)
  src/note_taker/
    __main__.py                          # CLI: --port --token --data-dir → uvicorn
    models.py                            # all Pydantic entities + enums
    paths.py                             # DataPaths: every on-disk location
    jsonio.py                            # atomic read/write helpers
    settings_store.py                    # load/save Settings
    batch_store.py                       # Batch CRUD, photos, sha dedupe, delete
    slug.py                              # slugify()
    markdown_writer.py                   # render sections, append with markers, frontmatter
    books.py                             # BookCatalog: repo scan + pending_books.json
    git_publisher.py                     # thin git CLI wrapper
    push_service.py                      # push orchestration + crash recovery
    imaging.py                           # load_upright, captured_at, downscale
    events.py                            # EventBus (thread-safe pub/sub for SSE)
    extractors/{__init__,base,fake,ollama,tesseract,factory}.py
    extraction_queue.py                  # worker thread, timeout, auto-resume
    janitor.py                           # expiry warnings + deletion
    api/{__init__,app,auth,deps,routes_settings,routes_books,routes_batches,routes_captures,routes_system}.py
  tests/
    conftest.py                          # tmp data dir, image factory, bare-repo fixture
    test_*.py                            # one per module
frontend/
  package.json, electron.vite.config.ts, tsconfig*.json, vitest.config.ts, playwright.config.ts
  electron/main/index.ts                 # window + backend lifecycle + IPC
  electron/main/backend.ts               # spawn/stop/wait-for-health
  electron/preload/index.ts              # exposes window.noteTaker.getConfig()
  src/api/types.ts                       # TS mirrors of backend models
  src/api/client.ts                      # typed fetch wrapper + SSE subscribe
  src/App.tsx                            # simple state router: list | grid | review | settings
  src/screens/{BatchList,BatchGrid,ReviewEditor,Settings}.tsx
  src/components/{BookSelect,HighlightBlock,Thumb,ExpiryBanner}.tsx
  tests/*.test.tsx, e2e/smoke.spec.ts
README.md                                # prerequisites + dev run
```

---

## Phase 1 — Backend

### Task 1: Backend scaffold, models, paths, settings store

**Files:**
- Create: `backend/pyproject.toml`, `backend/src/note_taker/{__init__,models,paths,jsonio,settings_store}.py`, `backend/tests/conftest.py`
- Test: `backend/tests/test_models.py`, `backend/tests/test_settings_store.py`

**Interfaces:**
- Produces (`models.py`):
  - Enums (`StrEnum`):
    - `Source{photo,kindle}`
    - `Kind{fiction,non_fiction="non-fiction"}`
    - `CaptureStatus{pending,extracting,ready,failed,approved,pushed,discarded}`
    - `BatchStatus{open,pushing,pushed,discarded}`
    - `ExtractorKind{ollama,tesseract}`
  - `Highlight(id: str = ulid, text: str, note: str | None = None)`
  - `Capture(id, source, image_file: str | None, image_sha256: str | None, rotation: int = 0 (clockwise degrees applied after EXIF; validator: one of 0/90/180/270), book_slug: str | None, page: int | None, chapter: str | None, captured_at: datetime, status: CaptureStatus, error: str | None, extractor_used: str | None, highlights: list[Highlight] = [])`
  - `Batch(id, default_book_slug: str | None, created_at, updated_at, status: BatchStatus = open, warned_at: datetime | None, captures: list[Capture] = [])`
    - method `is_finished() -> bool`: True iff there's ≥1 capture and all captures are `pushed`/`discarded`
    - method `expires_at(expiry_days: int) -> datetime`
  - `Book(slug, title, author: str | None, kind: Kind, pending: bool = False)`
  - `PendingBook(slug, title, author, kind)`
  - `ExtractedHighlight(text: str, bbox: tuple[int,int,int,int] | None = None)`
  - `ExtractionResult(highlights: list[ExtractedHighlight] = [], note, page: int | None, chapter, raw: dict = {})`, where `page` has a `field_validator` coercing numeric strings and returning None for non-numeric
  - `NotesRepoSettings(remote_url: str = "", branch="main", local_path: str | None = None, books_dir="books")`
  - `OllamaSettings(base_url="http://localhost:11434", model="qwen2.5vl:7b")`
  - `TesseractSettings(hsv_low=(20,80,120), hsv_high=(40,255,255), lang="eng")`
  - `ExtractorSettings(kind=ExtractorKind.ollama, ollama, tesseract, concurrency=1, timeout_s=180)`
  - `BatchSettings(expiry_days=30, warn_days_before=7)`
  - `Settings(notes_repo, extractor, batches)`
  - All datetimes are timezone-aware.
- Produces (`paths.py`): `DataPaths(root: Path)` with properties `settings_file`, `pending_books_file`, `batches_dir`, `default_repo_dir`, and methods `batch_dir(id)`, `batch_file(id)`, `photos_dir(id)`. Plus `repo_dir(settings) -> Path` (the `local_path` if set, else `default_repo_dir`).
- Produces (`jsonio.py`): `write_json_atomic(path: Path, data: dict) -> None`, `read_json(path: Path) -> dict | None`.
- Produces (`settings_store.py`): `SettingsStore(paths: DataPaths)` with `.load() -> Settings` (defaults if the file is missing) and `.save(s: Settings) -> None`.
- Produces (`conftest.py` fixtures):
  - `data_paths` (a DataPaths on `tmp_path`)
  - `make_image(tmp_path)` factory: `(name, fmt="PNG", highlight_text="mathematical possibility", plain_text="other words", exif_orientation=None, exif_datetime=None, pixel_rotation=0) -> Path`. `pixel_rotation` (degrees, clockwise) rotates the drawn pixels with no EXIF tag, to mimic a sideways photo. It draws black text on white, with a yellow (255,235,59) rectangle behind `highlight_text`.

- [ ] **Step 1: Scaffold.**
  - Run `uv init --package --name note-taker backend` (Python 3.12).
  - Add the deps from the Tech Stack.
  - Configure `[tool.pytest.ini_options] markers = ["live: needs real Ollama/Tesseract"]` and `addopts = "-m 'not live'"`.
- [ ] **Step 2: Write failing tests**

```python
def test_page_coerced_from_string():
    assert ExtractionResult(page="163").page == 163
    assert ExtractionResult(page="xvi").page is None

def test_batch_is_finished():
    b = make_batch(statuses=["pushed", "discarded"]); assert b.is_finished()
    assert not make_batch(statuses=["pushed", "approved"]).is_finished()
    assert not make_batch(statuses=[]).is_finished()

def test_expires_at_counts_from_updated_at():
    b = make_batch(updated_at=dt(2026, 11, 1))
    assert b.expires_at(30) == dt(2026, 12, 1)

def test_settings_defaults_and_roundtrip(data_paths):
    store = SettingsStore(data_paths)
    s = store.load()
    assert s.batches.expiry_days == 30 and s.extractor.timeout_s == 180 and s.notes_repo.branch == "main"
    s.extractor.kind = ExtractorKind.tesseract; store.save(s)
    assert SettingsStore(data_paths).load().extractor.kind == "tesseract"

def test_write_json_atomic_leaves_no_temp_files(tmp_path):
    write_json_atomic(tmp_path / "a.json", {"x": 1})
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]
```
- [ ] **Step 3: Run** `cd backend && uv run pytest -q`. Expected: FAIL (import errors).
- [ ] **Step 4: Implement** the interfaces above.
- [ ] **Step 5: Run** `uv run pytest -q`. Expected: PASS.
- [ ] **Step 6: Commit** `git add backend && git commit -m "feat(backend): scaffold, models, settings store"`

### Task 2: BatchStore

**Files:**
- Create: `backend/src/note_taker/batch_store.py`
- Test: `backend/tests/test_batch_store.py`

**Interfaces:**
- Consumes: `DataPaths`, `Batch`, `Capture`, `write_json_atomic`.
- Produces: `class BatchStore(paths: DataPaths, now: Callable[[], datetime] = utcnow)` with:
  - `create(default_book_slug: str | None) -> Batch`
  - `get(batch_id) -> Batch` (raises `BatchNotFound`)
  - `list() -> list[Batch]` (sorted by `created_at`)
  - `save(batch, touch: bool = True) -> Batch` (`touch` sets `updated_at=now()`)
  - `add_photo(batch_id, filename: str, data: bytes) -> Capture`
    - raises `UnsupportedImage` for anything that isn't PNG or JPEG, sniffed by magic bytes, not by extension
    - raises `DuplicatePhoto` when the SHA-256 is already in the batch
    - writes `photos/<capture_id>.<png|jpg>`
    - status `pending`
    - `captured_at` from `imaging.captured_at` (stub with `now()` until Task 7, then wire it in)
  - `add_kindle(batch_id, highlights: list[Highlight], book_slug, page, chapter, captured_at | None) -> Capture` (status `ready`)
  - `update_capture(batch_id, capture: Capture) -> Batch`
  - `remove_capture(batch_id, capture_id)` (also deletes the photo)
  - `find_capture(capture_id) -> tuple[Batch, Capture]`
  - `photo_path(batch_id, capture) -> Path`
  - `delete(batch_id)` (`shutil.rmtree` of the batch dir)
  - A module-level `threading.RLock` guards read-modify-write.

- [ ] **Step 1: Write failing tests:**
  - `test_create_get_list_roundtrip`
  - `test_add_photo_rejects_gif_and_dedupes_by_sha`: a GIF raises `UnsupportedImage`; adding the same PNG bytes twice raises `DuplicatePhoto`
  - `test_add_photo_writes_file_and_pending_capture`
  - `test_save_touch_false_keeps_updated_at`
  - `test_delete_removes_folder`: afterwards `paths.batch_dir(id)` doesn't exist and `list()` is empty
  - `test_remove_capture_deletes_photo`
- [ ] **Step 2: Run** `uv run pytest tests/test_batch_store.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `BatchStore`.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(backend): JSON-per-batch store`

### Task 3: Slug and MarkdownWriter

**Files:**
- Create: `backend/src/note_taker/slug.py`, `backend/src/note_taker/markdown_writer.py`
- Test: `backend/tests/test_slug.py`, `backend/tests/test_markdown_writer.py`, `backend/tests/golden/permutation-city.md`

**Interfaces:**
- Produces:
  - `slugify(title: str) -> str`:
    1. NFKD-normalize and drop non-ASCII
    2. delete `'` and `’`
    3. lowercase
    4. turn runs of non-`[a-z0-9]` into `-`
    5. strip leading/trailing `-`
    6. an empty result becomes `"untitled"`
  - `render_section(capture: Capture, highlight: Highlight, tz: tzinfo) -> str`
  - `render_new_file(book: Book) -> str` (frontmatter via `yaml.safe_dump(sort_keys=False)`, then `\n# <title>\n`)
  - `read_frontmatter(text: str) -> dict | None`
  - `existing_marker_ids(text: str) -> set[str]`
  - `append_highlights(path: Path, book: Book, items: list[tuple[Capture, Highlight]], tz) -> list[str]`
    - returns the IDs it actually wrote
    - creates the file if it's missing
    - skips IDs whose marker is already present
    - writes items sorted by `capture.captured_at`
    - joins sections to the existing text with exactly one blank line between blocks
- The section format is pinned by the golden file:

```markdown
## p.163 · 2026-11-08 21:14

> 'I'm sorry, I can't have explained things very well.
>
> Hayden cut her off.

**Note:** Insurance fraud is a main plot point?

<!-- nt:highlight=01HXYZ -->
```
- Kindle captures add `*Source: Kindle*` plus a blank line right after the heading. `**Note:**` is omitted when the note is empty or None. Every line of the text gets `> `, and blank lines become a bare `>`.

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.parametrize("title,slug", [
    ("Permutation City", "permutation-city"),
    ("Measure What Matters: OKRs", "measure-what-matters-okrs"),
    ("Ćirković’s Notes", "cirkovics-notes"),
    ("A Philosophy of Software Design", "a-philosophy-of-software-design"),
    ("!!!", "untitled"),
])
def test_slugify_cases(title, slug): assert slugify(title) == slug

def test_heading_variants(): ...  # page+chapter → "## p.170 · Chapter 12 · 2026-11-08 21:20"; neither → "## 2026-11-08 21:14"
def test_render_multiparagraph_text_stays_quoted(): ...  # "a\n\nb" → "> a\n>\n> b"; text starting with ">" still prefixed
def test_kindle_source_line_and_no_empty_note(): ...
def test_frontmatter_with_colon_roundtrips(tmp_path):
    book = Book(slug="m", title="Measure What Matters: OKRs", author="John Doerr", kind="non-fiction")
    assert read_frontmatter(render_new_file(book))["title"] == "Measure What Matters: OKRs"
def test_append_creates_file_matching_golden(tmp_path): ...
def test_append_is_idempotent(tmp_path):
    first = append_highlights(p, book, items, tz); second = append_highlights(p, book, items, tz)
    assert second == [] and p.read_text().count("nt:highlight=") == len(items)
def test_append_preserves_user_edits(tmp_path): ...  # pre-existing hand-written text stays byte-identical as a prefix
```
- [ ] **Step 2: Run** `uv run pytest tests/test_slug.py tests/test_markdown_writer.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(backend): slugify and append-only markdown writer`

### Task 4: BookCatalog

**Files:**
- Create: `backend/src/note_taker/books.py`
- Test: `backend/tests/test_books.py`

**Interfaces:**
- Consumes: `DataPaths`, `read_frontmatter`, `slugify`, `Book`, `PendingBook`.
- Produces: `class BookCatalog(paths: DataPaths, repo_dir: Callable[[], Path], books_dir: Callable[[], str])` with:
  - `list() -> list[Book]`: repo books from `books/*.md` frontmatter, plus pending books with `pending=True`, de-duplicated by slug with the repo winning, sorted by title. A file with missing or invalid frontmatter falls back to `title` = the filename stem, `kind=non-fiction`.
  - `create(title, author, kind) -> Book`: returns the existing book if the slug already exists in the repo or the pending list. Otherwise it appends to `pending_books.json`.
  - `get(slug) -> Book` (raises `BookNotFound`)
  - `prune_pending() -> None`: drops pending entries whose `books/<slug>.md` now exists
  - `book_path(slug) -> Path`

- [ ] **Step 1: Write failing tests:**
  - `test_lists_repo_and_pending_books`
  - `test_create_existing_slug_returns_repo_book`
  - `test_pending_visible_across_catalog_instances`
  - `test_prune_pending_after_file_exists`
  - `test_bad_frontmatter_falls_back_to_stem`
- [ ] **Step 2: Run** `uv run pytest tests/test_books.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(backend): book catalog with global pending books`

### Task 5: GitPublisher

**Files:**
- Create: `backend/src/note_taker/git_publisher.py`
- Test: `backend/tests/test_git_publisher.py`
- Modify: `backend/tests/conftest.py`, adding a `bare_remote` fixture: `git init --bare -b main` with one seed commit containing `README.md`. It yields the remote path.

**Interfaces:**
- Produces:
  - `class GitError(Exception)` with `.stderr: str`
  - `class GitPublisher(repo_dir: Path, remote_url: str, branch: str)`, shelling out with `subprocess.run(["git", "-C", repo_dir, ...], check=False, capture_output=True, text=True)`. Methods:
    - `is_cloned() -> bool`
    - `clone() -> None`: `git clone --branch <branch> <remote> <repo_dir>`. Raises `GitError` carrying git's stderr on auth/branch failure.
    - `is_dirty(books_dir: str) -> bool`: tracked changes anywhere (`status --porcelain --untracked-files=no` non-empty) OR untracked files under `books_dir` (`status --porcelain -- <books_dir>` showing `??`)
    - `head() -> str`
    - `pull_rebase() -> None`
    - `commit(paths: list[Path], message: str) -> str`: returns the SHA
    - `push() -> None`: on a rejected non-fast-forward, `pull_rebase()` then retry once. Raises `GitError` on a second failure.
    - `rollback(pre_head: str, touched: list[Path]) -> None`: `git reset --mixed <pre_head>`, then `git checkout -- <touched that existed at pre_head>`, then delete touched files that were untracked at pre_head. **Never `--hard`.**
    - `fetch() -> None`
    - `remote_file(rel_path: str) -> str | None`: `git show origin/<branch>:<rel_path>`, None if missing
    - `check_remote() -> None`: `git ls-remote --exit-code --heads <remote> <branch>`, raises `GitError`

- [ ] **Step 1: Write failing tests**, all against `bare_remote` with real git:
  - `test_clone_and_is_cloned`
  - `test_clone_bad_branch_raises_with_stderr`
  - `test_is_dirty_tracked_and_untracked_books`: an untracked file outside `books/` is not dirty
  - `test_commit_and_push_reaches_remote`
  - `test_push_retries_after_non_ff`: a second clone pushes first, and ours still lands
  - `test_rollback_restores_files_and_head_without_touching_other_files`: an untracked file outside `books/` survives the rollback
  - `test_remote_file_after_fetch`
- [ ] **Step 2: Run** `uv run pytest tests/test_git_publisher.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(backend): git publisher with safe rollback`

### Task 6: PushService

**Files:**
- Create: `backend/src/note_taker/push_service.py`, `backend/src/note_taker/events.py`
- Test: `backend/tests/test_push_service.py`, `backend/tests/test_events.py`

**Interfaces:**
- Consumes: `BatchStore`, `BookCatalog`, `GitPublisher`, `append_highlights`, `Settings`.
- Produces (`events.py`): `class EventBus` with:
  - `publish(batch_id: str, type: str, data: dict) -> None`
  - `subscribe(batch_id) -> queue.Queue`
  - `unsubscribe(batch_id, q)`
  - Event types: `capture.status_changed`, `capture.extracted`, `batch.push_progress`. Thread-safe.
- Produces (`push_service.py`):
  - `class PushError(Exception)` with `.code` in {`dirty_repo`, `not_cloned`, `nothing_to_push`, `git_failed`}
  - `PushResult(commit_sha: str, files_changed: list[str], highlights_written: int, batch_deleted: bool)`
  - `class PushService(store, books, git_factory: Callable[[], GitPublisher], settings: Callable[[], Settings], events, tz)` with `push(batch_id) -> PushResult` and `recover() -> None`.
  - A module-level `threading.Lock` serializes all pushes.
- `push` algorithm (it decides ordering, so it's spelled out):
  1. Take the lock. Raise `not_cloned` or `dirty_repo` up front.
  2. Collect `approved` captures. If there are none, raise `nothing_to_push`.
  3. Set batch status `pushing` (`save(touch=False)`).
  4. `pull_rebase`, then record `pre = head()`.
  5. Group by resolved book (`capture.book_slug or batch.default_book_slug`), then call `append_highlights` for each book file. Collect the touched paths.
  6. If nothing was written (all markers already present), skip the commit, mark the captures `pushed`, and go to step 9.
  7. `commit(touched, message)` with the Global Constraints format, then `push()`.
  8. On any `GitError` in steps 4–7: `rollback(pre, touched)`, set the batch back to `open`, keep the captures `approved`, and raise `git_failed` with the stderr.
  9. Mark the captures `pushed`, set the batch to `open`, `save(touch=True)`, `books.prune_pending()`.
  10. If `batch.is_finished()`, call `store.delete(id)`.
  11. Publish `batch.push_progress` at each stage.
- `recover()`: for each batch in `pushing`, `fetch`, then for every approved capture, if all its highlight markers appear in `remote_file(books/<slug>.md)` mark it `pushed`. Set the batch to `open`, and delete it if it's finished.

- [ ] **Step 1: Write failing tests** with a real `bare_remote` plus a cloned `GitPublisher`:
  - `test_push_writes_commits_and_deletes_finished_batch`: the remote file contains the section, the commit message has the `Note-Taker-Batch:` trailer, and the batch folder is gone
  - `test_push_keeps_batch_with_unapproved_captures`: pushed captures become `pushed`, the batch still exists, and `updated_at` was bumped
  - `test_push_refuses_dirty_repo`: `PushError.code == "dirty_repo"` and the batch is untouched
  - `test_push_failure_rolls_back`: point the remote at a nonexistent path after clone; the local HEAD is unchanged, the book file is restored, the captures are still `approved`, and the batch is `open`
  - `test_retry_after_partial_success_does_not_duplicate`: simulate a crash after push by pushing and then restoring the old batch JSON; the second push writes 0 and creates no new commit
  - `test_recover_marks_pushed_from_remote_markers`
  - `test_concurrent_pushes_serialize`: two threads push two batches for the same book; both succeed, the remote file has both sections, and markers are unique
  - `test_eventbus_fanout`
- [ ] **Step 2: Run** `uv run pytest tests/test_push_service.py tests/test_events.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(backend): idempotent push service with recovery`

### Task 7: Imaging, extractor interface, FakeExtractor, ExtractionQueue

**Files:**
- Create: `backend/src/note_taker/imaging.py`, `backend/src/note_taker/extractors/{__init__,base,fake,factory}.py`, `backend/src/note_taker/extraction_queue.py`
- Modify: `backend/src/note_taker/batch_store.py` (use `imaging.captured_at` in `add_photo`)
- Test: `backend/tests/test_imaging.py`, `backend/tests/test_extraction_queue.py`

**Interfaces:**
- Produces (`imaging.py`):
  - `load_upright(path: Path, rotation: int = 0) -> PIL.Image.Image`: `ImageOps.exif_transpose`, then rotate clockwise by `rotation` degrees
  - `detect_rotation(path: Path) -> int`: clockwise degrees (0/90/180/270) needed to make the text upright, from Tesseract OSD (`pytesseract.image_to_osd`) on a downscaled grayscale copy of the EXIF-corrected image. Returns 0 when Tesseract is missing, OSD fails, or its confidence is below 2.0. Never raises.
  - `captured_at(path: Path, fallback: datetime) -> datetime`: EXIF `DateTimeOriginal` (tag 36867) interpreted as local time, then the file mtime, then `fallback`
  - `downscaled_jpeg_bytes(path: Path, max_edge: int = 2000, rotation: int = 0) -> bytes` (upright via `load_upright(path, rotation)`)
- Produces (`extractors/base.py`):
  - `class ExtractionError(Exception)`
  - `HealthStatus(ok: bool, detail: str)`
  - `class Extractor(Protocol)` with `name: str`, `health() -> HealthStatus`, `extract(image_path: Path, rotation: int = 0) -> ExtractionResult` (extractors must work on `load_upright(image_path, rotation)`)
- Produces (`extractors/fake.py`): `FakeExtractor(result: ExtractionResult | None = None, delay_s: float = 0, error: str | None = None, healthy: bool = True)`
- Produces (`extractors/factory.py`): `build_extractor(s: ExtractorSettings, kind: ExtractorKind | None = None) -> Extractor`. Fill in the Ollama/Tesseract branches in Tasks 8–9; until then it raises `NotImplementedError`.
- Produces (`extraction_queue.py`): `class ExtractionQueue(store, extractor_provider: Callable[[ExtractorKind | None], Extractor], events, concurrency: int = 1, timeout_s: float = 180, health_interval_s: float = 30)` with:
  - `start()`
  - `stop()`
  - `enqueue(batch_id, capture_id, kind: ExtractorKind | None = None)`
  - `resume_pending() -> int`
- `ExtractionQueue` behavior:
  - FIFO order.
  - Before the first extraction of a photo capture whose `rotation` is 0, it calls `imaging.detect_rotation` and stores the result in `capture.rotation`. Later retries keep whatever the capture holds (the user may have changed it). It passes `capture.rotation` to `extract`.
  - It checks extractor health before each job. If unhealthy, the capture stays `pending` with `error="extractor unavailable: <detail>"`. A background loop calls `resume_pending()` every `health_interval_s` while any `pending` captures exist.
  - It runs `extract` in a `ThreadPoolExecutor` with `future.result(timeout=timeout_s)`.
  - On success: capture `ready`, `highlights` = the extracted texts (the extractor's `note` goes on the first highlight), `page`/`chapter` set only if the user hasn't already set them, `extractor_used` = the extractor name. It publishes `capture.extracted`.
  - On `ExtractionError` or timeout: `failed` with the error message (`"timed out after 180s"` for timeouts).
  - It publishes `capture.status_changed` on every transition.
  - It saves with `touch=False`, so background work doesn't reset expiry.

- [ ] **Step 1: Write failing tests:**
  - `test_load_upright_applies_orientation`: `make_image(exif_orientation=6)`; width and height come out swapped
  - `test_captured_at_from_exif`
  - `test_captured_at_falls_back_to_mtime`
  - `test_downscale_caps_long_edge`
  - `test_queue_success_sets_ready_and_note_on_first_highlight`
  - `test_queue_empty_result_is_ready_with_no_highlights`
  - `test_queue_error_sets_failed`
  - `test_queue_timeout_sets_failed`: `delay_s=2`, `timeout_s=0.2`
  - `test_queue_unhealthy_leaves_pending_then_resumes`: flip `healthy`, then call `resume_pending()`
  - `test_queue_does_not_touch_updated_at`
  - `test_queue_fifo_order`
  - `test_load_upright_applies_extra_rotation`: `make_image(pixel_rotation=90)`; `load_upright(p, 270)` has the original orientation
  - `test_detect_rotation_on_sideways_image` (skip if no tesseract): text image with `pixel_rotation=90` → `detect_rotation` returns 270; upright image → 0
  - `test_detect_rotation_returns_zero_without_tesseract` (monkeypatch)
  - `test_queue_sets_detected_rotation_once_and_keeps_user_value`: a capture with `rotation=90` is not overwritten
- [ ] **Step 2: Run** `uv run pytest tests/test_imaging.py tests/test_extraction_queue.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same command plus the full suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat(backend): imaging helpers and extraction queue`

### Task 8: OllamaVisionExtractor

**Files:**
- Create: `backend/src/note_taker/extractors/ollama.py`
- Modify: `backend/src/note_taker/extractors/factory.py`
- Test: `backend/tests/test_ollama_extractor.py`

**Interfaces:**
- Produces: `OllamaVisionExtractor(base_url: str, model: str, timeout_s: float = 180)` with `name = "ollama:<model>"`.
  - `health()`: `GET /api/tags`. ok iff it responds and `model` is listed. The detail says "Ollama not reachable at …" or "model <m> not pulled (run: ollama pull <m>)".
  - `extract(path, rotation=0)`: `POST /api/chat` with:
    - `{"model": m, "stream": false, "format": <ExtractionResult JSON schema without raw>, "options": {"temperature": 0}, "messages": [{"role": "user", "content": PROMPT, "images": [b64(downscaled_jpeg_bytes(path, rotation=rotation))]}]}`
    - It parses `message.content` as JSON into `ExtractionResult` and stores the response body in `raw`.
    - An HTTP error, invalid JSON, or schema mismatch raises `ExtractionError` with a short message.
- PROMPT (exact copy, tune later during live testing):
  > "This is a photo of a printed book page. Return ONLY text that is marked with a highlighter (usually yellow), as separate passages in reading order, transcribed exactly. Ignore unhighlighted text. If there is handwritten text in the margins, return it as `note`. Return the printed page number as `page` and the chapter title as `chapter` if a running header shows it; otherwise null."

- [ ] **Step 1: Write failing tests** with `respx`:
  - `test_extract_parses_structured_content`: assert the request body has `format`, `images[0]` as non-empty base64, and `stream` false
  - `test_page_string_is_coerced`
  - `test_malformed_json_raises_extraction_error`
  - `test_http_500_raises_extraction_error`
  - `test_health_reports_missing_model`
  - `@pytest.mark.live test_live_extract_sample_p163`: runs on `backend/tests/fixtures/sample-p163.jpg` (committed) and asserts "mathematical possibility" is in some highlight and `page == 163`
  - `@pytest.mark.live test_live_all_local_fixtures_report`: for every local `PXL_*.jpg` (skipped if none), runs extraction with `detect_rotation` applied, prints highlights/note/page per photo, and asserts no `ExtractionError`. Used to pick the default model; not a pass/fail accuracy test
- [ ] **Step 2: Run** `uv run pytest tests/test_ollama_extractor.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement**, and wire the `ollama` branch in `build_extractor`.
- [ ] **Step 4: Run** the same command. Expected: PASS. Optionally run `uv run pytest -m live tests/test_ollama_extractor.py` with Ollama running and record the chosen default model in the README.
- [ ] **Step 5: Commit** `feat(backend): ollama vision extractor`

### Task 9: TesseractExtractor

**Files:**
- Create: `backend/src/note_taker/extractors/tesseract.py`
- Modify: `backend/src/note_taker/extractors/factory.py`
- Test: `backend/tests/test_tesseract_extractor.py`

**Interfaces:**
- Produces:
  - `find_highlight_regions(img_bgr: np.ndarray, hsv_low, hsv_high) -> list[tuple[int,int,int,int]]`:
    1. `cv2.inRange` on HSV
    2. morphological close with a horizontal kernel (≈25×5)
    3. external contours, dropping boxes under 0.1% of the image area
    4. sort top-to-bottom
  - `group_into_passages(boxes, line_gap_px) -> list[list[box]]`: vertically adjacent boxes (gap < 1.5× median box height) form one passage
  - `TesseractExtractor(hsv_low, hsv_high, lang="eng")` with `name="tesseract"`:
    - `health()`: `shutil.which("tesseract")`
    - `extract(image_path, rotation=0)`: work on `load_upright(image_path, rotation)`; OCR each region with `--psm 6` and join a passage's lines with spaces; OCR the top and bottom 8% strips with `--psm 7` and take the first standalone 1–4 digit number as `page`; `note=None`, `chapter=None`

- [ ] **Step 1: Write failing tests:**
  - `test_find_regions_on_synthetic_image`: one yellow box → one region overlapping the drawn rectangle
  - `test_no_yellow_returns_empty`
  - `test_group_adjacent_lines_into_one_passage`
  - `@pytest.mark.skipif(no tesseract) test_extract_reads_only_highlighted_text`: "mathematical" is in the result, "other" is not
  - `test_health_false_when_binary_missing` (monkeypatch `shutil.which`)
- [ ] **Step 2: Run** `uv run pytest tests/test_tesseract_extractor.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement**, and wire the `tesseract` branch in `build_extractor`.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(backend): tesseract highlight extractor`

### Task 10: Janitor

**Files:**
- Create: `backend/src/note_taker/janitor.py`
- Test: `backend/tests/test_janitor.py`

**Interfaces:**
- Produces:
  - `JanitorReport(warned: list[str], deleted: list[str])`
  - `class Janitor(store, settings: Callable[[], Settings], now: Callable[[], datetime])` with `run() -> JanitorReport`
  - `expiring_soon(batch, settings, now) -> bool`, which the API reuses
- Rules (pinned by the spec; tests use `freezegun`/an injected `now`):
  - Only batches that aren't finished are considered. Empty batches count as unfinished.
  - `exp = batch.expires_at(expiry_days)`.
  - If `now >= exp - warn_days_before` and `warned_at is None`: set `warned_at=now` with `save(touch=False)` and report it as warned.
  - If `now >= exp` and `warned_at` is set and `now - warned_at >= 24h`: `store.delete` and report it as deleted.
  - `expiring_soon` is true iff `now >= exp - warn_days_before`.

- [ ] **Step 1: Write failing tests:**
  - `test_no_action_before_warning_window`: day 22
  - `test_warns_at_day_23_without_touching_updated_at`
  - `test_expired_but_never_warned_gets_warned_not_deleted`: day 40 with `warned_at=None` → warned
  - `test_deletes_24h_after_warning_when_expired`
  - `test_finished_batches_ignored`
  - `test_custom_expiry_days_from_settings`: expiry 10 days → warns on day 3
- [ ] **Step 2: Run** `uv run pytest tests/test_janitor.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(backend): batch expiry janitor`

### Task 11: FastAPI app, routes, SSE, CLI entrypoint

**Files:**
- Create: `backend/src/note_taker/api/{__init__,app,auth,deps,routes_settings,routes_books,routes_batches,routes_captures,routes_system}.py`, `backend/src/note_taker/__main__.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `AppConfig(data_dir: Path, token: str, tz: tzinfo = local)`
  - `create_app(config: AppConfig, extractor_provider: Callable[[ExtractorKind | None], Extractor] | None = None, git_factory: Callable[[], GitPublisher] | None = None) -> FastAPI`
    - On startup it runs `push_service.recover()`, then `janitor.run()`, then `queue.start()`, and schedules the janitor every 6h.
  - CLI: `python -m note_taker --port <int> --token <str> --data-dir <path>` → `uvicorn.run(app, host="127.0.0.1", port=port)`.
- Routes: exactly the spec §7 table, plus `POST /repo/connect` (runs `check_remote()` then `clone()`; a `GitError` becomes 400 with stderr). Response details:
  - `GET /batches` → `[{id, default_book_slug, created_at, updated_at, expires_at, expiring_soon, warned_at, counts: {<status>: n}}]`
  - `POST /batches/{id}/captures`: multipart `files` → `{created: [Capture], rejected: [{filename, reason}]}`, enqueueing each created capture. JSON body with `source:"kindle"` → `Capture`.
  - `PATCH /captures/{id}` body `{highlights?, book_slug?, page?, chapter?, captured_at?, rotation?, status?}` (`rotation` must be 0/90/180/270, otherwise 422). Allowed status transitions follow the spec §6 state machine. Approving requires ≥1 highlight with non-empty stripped text AND a resolvable book (capture or batch default, repo or pending); otherwise 422 with code `not_approvable`. Any PATCH touches `updated_at`.
  - `POST /captures/{id}/retry` `{extractor?}` → status `pending`, re-enqueued.
  - `GET /captures/{id}/image` → the upright image (`load_upright(path, capture.rotation)` re-encoded as JPEG).
  - `GET /batches/{id}/events` → `EventSourceResponse` from `EventBus.subscribe`.
  - `POST /batches/{id}/push` → `PushResult`. `PushError` codes map to: `dirty_repo` 409, `not_cloned` 409, `nothing_to_push` 400, `git_failed` 502.
  - `GET /health` → `{extractor: {kind, ok, detail}, repo: {cloned, dirty, path}, remote: {ok, detail}}`
  - Errors use the shape `{"error": {"code", "message"}}`.
- Auth: middleware compares `X-Session-Token` with `hmac.compare_digest` and returns 401 `{"error":{"code":"unauthorized",...}}`. For `/captures/{id}/image` and `/batches/{id}/events` (which `<img>` and `EventSource` can't add headers to), it also accepts a `?token=` query param.

- [ ] **Step 1: Write failing tests** using `TestClient` with a `FakeExtractor` provider and `bare_remote`:
  - `test_requires_token`
  - `test_token_query_param_allowed_only_for_image_and_events`
  - `test_create_batch_upload_png_and_reject_gif`
  - `test_upload_runs_extraction_to_ready`: poll `GET /batches/{id}` up to 2s
  - `test_kindle_capture_starts_ready`
  - `test_approve_requires_text_and_book`: empty highlights → 422 `not_approvable`, and no book → 422
  - `test_patch_touches_updated_at`
  - `test_patch_rotation_validates_and_image_endpoint_serves_rotated`: rotation 45 → 422; rotation 90 swaps the served image's width/height
  - `test_books_create_pending_then_listed_with_flag`
  - `test_repo_connect_then_health_reports_cloned`
  - `test_full_flow_push_deletes_batch`: connect repo, create book, upload, approve, push → 200; then `GET /batches/{id}` → 404 and the remote has `books/permutation-city.md`
  - `test_push_dirty_repo_409`
  - `test_list_batches_includes_expiry_fields`
  - `test_events_stream_emits_status_changed`: read the first SSE event
- [ ] **Step 2: Run** `uv run pytest tests/test_api.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest -q` (full suite). Expected: all PASS. Manual check: `uv run python -m note_taker --port 8765 --token t --data-dir /tmp/nt`, then `curl -H 'X-Session-Token: t' localhost:8765/health` returns JSON.
- [ ] **Step 5: Commit** `feat(backend): REST API, SSE, and CLI entrypoint`

---

## Phase 2 — Desktop app

### Task 12: Electron scaffold, backend lifecycle, typed API client

**Files:**
- Create: `frontend/` from `npm create @quick-start/electron@latest frontend -- --template react-ts`, then `frontend/electron/main/{index,backend}.ts`, `frontend/electron/preload/index.ts`, `frontend/src/api/{types,client}.ts`, `frontend/vitest.config.ts`
- Test: `frontend/tests/client.test.ts`

**Interfaces:**
- Produces (`backend.ts`): `startBackend(opts: {backendDir: string, dataDir: string}): Promise<{baseUrl: string, token: string, stop: () => Promise<void>}>`
  - finds a free port via `net.createServer().listen(0)`
  - creates the token with `crypto.randomBytes(32).toString('hex')`
  - spawns `uv run --project <backendDir> python -m note_taker --port P --token T --data-dir D`
  - polls `GET /health` with the token every 250ms for up to 20s, and rejects with the captured stderr on timeout
  - `stop()` sends SIGTERM, then SIGKILL after 3s
  - `backendDir` = `path.resolve(__dirname, '../../../backend')` in dev, overridable with the `NOTE_TAKER_BACKEND_DIR` env var. `dataDir` = `app.getPath('userData')`, overridable with `NOTE_TAKER_DATA_DIR` (used by the e2e test).
- Produces (`main/index.ts`): starts the backend before creating the window; handles IPC `backend:config` → `{baseUrl, token}`; stops the backend on `before-quit`; shows an error dialog with stderr if startup fails.
- Produces (`preload/index.ts`): `contextBridge.exposeInMainWorld('noteTaker', { getConfig: () => ipcRenderer.invoke('backend:config') })`.
- Produces (`types.ts`): TS mirrors of `Settings, Book, Batch (+expires_at, expiring_soon, counts), Capture, Highlight, CaptureStatus, PushResult, Health, ApiError`. Field names are identical to the backend JSON (snake_case).
- Produces (`client.ts`): `createClient(cfg: {baseUrl: string, token: string})` returning methods that map 1:1 to routes:
  - `getHealth`, `getSettings`, `putSettings`, `connectRepo`
  - `listBooks`, `createBook`
  - `listBatches`, `createBatch`, `getBatch`, `patchBatch`, `deleteBatch`
  - `uploadPhotos(batchId, files: File[])`, `addKindle(batchId, body)`
  - `patchCapture`, `retryCapture`, `deleteCapture`
  - `imageUrl(captureId) -> string` (with `?token=`)
  - `subscribe(batchId, onEvent) -> () => void` (an `EventSource` with `?token=`)
  - `push(batchId)`
  - Non-2xx responses throw `ApiError {status, code, message}`.

- [ ] **Step 1: Write failing tests** (Vitest, mocked `fetch`):
  - `sends token header`
  - `throws ApiError with backend code on 409`
  - `imageUrl includes token query`
  - `uploadPhotos posts multipart with files field`
- [ ] **Step 2: Run** `cd frontend && npx vitest run`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npx vitest run`. Expected: PASS. Manual check: `npm run dev` opens a window, and the devtools console `await window.noteTaker.getConfig()` returns `{baseUrl, token}`.
- [ ] **Step 5: Commit** `feat(frontend): electron scaffold, backend lifecycle, api client`

### Task 13: Batch list and batch grid screens

**Files:**
- Create: `frontend/src/App.tsx` (replacing the template), `frontend/src/screens/{BatchList,BatchGrid}.tsx`, `frontend/src/components/{BookSelect,Thumb,ExpiryBanner}.tsx`
- Test: `frontend/tests/BatchList.test.tsx`, `frontend/tests/BatchGrid.test.tsx`

**Interfaces:**
- Consumes: the `createClient` methods. A React context `ApiContext` provides the client; tests inject a fake.
- Produces:
  - `App` routes with a state union: `{screen:"list"} | {screen:"grid", batchId} | {screen:"review", batchId, index} | {screen:"settings"}`
  - `<BookSelect value onChange allowCreate />`: lists `listBooks()` with pending books suffixed " (new)". "+ New book…" opens an inline form (title, author, kind) that calls `createBook`.
- BatchList (app home):
  - lists open batches: created date, default book title, counts, expiry date
  - `<ExpiryBanner>` at the top when any batch has `expiring_soon`, with the text: `"<n> batch(es) will be deleted soon: <date>. Resume or discard them."`
  - buttons per batch: Resume (→ grid) and Discard (confirm → `deleteBatch`)
  - "New batch" → `createBatch` → grid
  - "Settings" link
  - shows a banner linking to Settings when `getHealth().repo.cloned` is false
- BatchGrid (chosen layout B):
  - drop zone plus a file picker (accept `image/png,image/jpeg`, multiple), calling `uploadPhotos`; per-file rejections are shown inline
  - a "Book for all" `<BookSelect>` → `patchBatch({default_book_slug})`
  - a thumbnail grid using `imageUrl`, with status badges: pending "…", extracting spinner, ready ✓, failed ✗ + error tooltip, approved ✓✓, discarded faded, pushed hidden
  - multi-select plus "Remove selected" (`deleteCapture`)
  - "Add Kindle highlight" → `addKindle` with one empty highlight, then opens review at that index
  - "Review 1 of N →" → review at index 0
  - "Push all approved (n)", disabled when n=0; it shows the `PushResult` summary or the error message (409 dirty repo → "Your notes repo has uncommitted changes. Commit or stash them, then push again.")
  - live updates via `subscribe` → re-fetch the batch on each event

- [ ] **Step 1: Write failing tests:**
  - `shows expiry banner when a batch is expiring_soon`
  - `discard asks for confirmation then deletes`
  - `grid renders badge per capture status`
  - `uploading files calls uploadPhotos and shows rejected reasons`
  - `push button disabled with zero approved and shows dirty-repo message on 409`
- [ ] **Step 2: Run** `npx vitest run tests/BatchList.test.tsx tests/BatchGrid.test.tsx`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(frontend): batch list and batch grid`

### Task 14: Review editor

**Files:**
- Create: `frontend/src/screens/ReviewEditor.tsx`, `frontend/src/components/HighlightBlock.tsx`
- Test: `frontend/tests/ReviewEditor.test.tsx`

**Interfaces:**
- Consumes: `getBatch`, `patchCapture`, `retryCapture`, `imageUrl`, `BookSelect`.
- Layout (chosen layout A):
  - header: `<BookSelect>` (capture override; shows the batch default as a placeholder) and the active extractor name from `getSettings`
  - left: the photo (`imageUrl`), with outline boxes drawn for any highlight `bbox` when present; Kindle captures show "Kindle highlight" instead
  - right, shared capture fields: Page (number), Chapter, Captured (`datetime-local`)
  - right, then one `<HighlightBlock>` per highlight (Highlight textarea + My note textarea + remove), plus "+ Add highlight"
  - footer: ◀ `k of N` ▶ (over non-pushed captures), Discard, Approve / Unapprove, Retry (only when `failed`, with an extractor choice)
  - above the photo: a **Rotate ↻** button that patches `rotation` by +90 (mod 360), refreshes the photo, and then offers "Re-run extraction" (`retryCapture`)
- Autosave: debounce field edits by 600ms → `patchCapture`. Flush pending edits before navigating or approving.
- Approve: on a 422 `not_approvable`, show "Add highlight text and choose a book before approving."
- Keyboard: ←/→ navigate (when focus isn't in a text field), ⌘↵ approves and moves to the next capture.

- [ ] **Step 1: Write failing tests** (fake timers):
  - `renders one block per highlight with shared page field`
  - `edits autosave after 600ms debounce`
  - `approve flushes pending edits before patching status`
  - `shows not_approvable message on 422`
  - `retry visible only for failed captures`
  - `test_rotate_button_patches_rotation_and_offers_retry`: clicking ↻ on a capture with rotation 270 patches `rotation: 0` and shows "Re-run extraction"
  - `next/prev navigation skips pushed captures`
- [ ] **Step 2: Run** `npx vitest run tests/ReviewEditor.test.tsx`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(frontend): one-page-at-a-time review editor`

### Task 15: Settings screen and repo connection

**Files:**
- Create: `frontend/src/screens/Settings.tsx`
- Test: `frontend/tests/Settings.test.tsx`

**Interfaces:**
- Consumes: `getSettings`, `putSettings`, `connectRepo`, `getHealth`.
- Sections:
  - **Notes repo:** remote URL, branch, optional "Use existing clone" path (a text field; an Electron folder picker via a new IPC `dialog:pickFolder` is optional), books folder. "Connect repo" calls `connectRepo` and shows git's stderr verbatim on failure.
  - **Extractor:** Ollama vs Tesseract radio; Ollama base URL and model; concurrency; timeout seconds.
  - **Batches:** expiry days, warning days before.
  - **Health panel:** extractor / repo / remote status from `getHealth`, plus a "Re-check" button.
- Save → `putSettings`. Number inputs must be validated as ≥1 before saving.

- [ ] **Step 1: Write failing tests:**
  - `loads and saves settings`
  - `connect repo shows stderr on failure`
  - `rejects expiry days below 1`
  - `health panel shows model-not-pulled detail`
- [ ] **Step 2: Run** `npx vitest run tests/Settings.test.tsx`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(frontend): settings and repo connection`

### Task 16: End-to-end smoke test and README

**Files:**
- Create: `frontend/e2e/smoke.spec.ts`, `frontend/playwright.config.ts`, (`backend/tests/fixtures/README.md` and `sample-p163.jpg` already exist and are committed with this plan; do not re-create)
- Modify: `README.md`
- Test: `frontend/e2e/smoke.spec.ts`

**Interfaces:**
- The test sets `NOTE_TAKER_DATA_DIR` to a temp dir and pre-writes `settings.json` with `extractor.kind = "tesseract"` and `notes_repo.remote_url` = a temp bare repo created in `beforeAll` (`git init --bare -b main` plus a seed commit). It skips if `tesseract` isn't on PATH.
- Flow:
  1. launch with `_electron.launch({ args: ['.'] })`
  2. Settings → Connect repo
  3. New batch → create the book "Permutation City" (fiction)
  4. upload two generated PNGs (written by the test with a yellow highlight via node-canvas, or committed as `e2e/fixtures/*.png`)
  5. wait for ✓ badges → Review → approve both
  6. Push
  7. assert `git -C <clone of bare> show HEAD:books/permutation-city.md` contains two `nt:highlight=` markers, and the batch list is empty
- README:
  - what the app does
  - prerequisites (macOS, Ollama + `ollama pull <default model>`, `brew install tesseract`, uv, Node 20+)
  - `cd backend && uv sync && uv run pytest`
  - `cd frontend && npm i && npm run dev`
  - where data lives
  - how to run live tests (`uv run pytest -m live`, `npx playwright test`)

- [ ] **Step 1: Write the e2e test.**
- [ ] **Step 2: Run** `cd frontend && npx playwright test`. Expected: FAIL at first if any wiring is missing. Fix the wiring until it passes (fixes belong to the owning task's files).
- [ ] **Step 3: Run** the full verification:
  - `cd backend && uv run pytest -q`
  - `cd frontend && npx vitest run && npx playwright test`
  - Expected: all pass.
- [ ] **Step 4: Write the README.**
- [ ] **Step 5: Commit** `test: electron e2e smoke; docs: README with prerequisites`

---

## Spec coverage map

| Spec item | Task |
|---|---|
| Photo → highlights / note / page (§2, §5.1) | 7, 8, 9 |
| Kindle paste through the same flow (§3.5) | 11, 13, 14 |
| Metadata: book, time, page, chapter, note (§2, §6, §12.1) | 1, 3, 14 |
| Batch grid (B) and one-page review (A) (§3) | 13, 14 |
| Several batches, delete on done, 30d expiry with warning (§3, §12.5) | 2, 6, 10, 13 |
| One file per book, append-only, markers (§4, §12.2) | 3, 6 |
| Global pending books (§7, §12.3) | 4 |
| Clone / connect repo, dirty refusal, no hard reset (§5.2, §12.2, §12.4) | 5, 6, 11, 15 |
| Extraction queue concurrency, timeout, auto-resume (§12.6) | 7 |
| Local-only, token-guarded backend spawned by Electron (§5) | 11, 12 |
| Error/edge cases (§8) | 2, 6, 7, 8, 11 |
| Testing strategy (§9) | all; 16 for e2e |
| bbox overlay, nice-to-have (§12.8) | 14 |
