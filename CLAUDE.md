# note-taker

## Intent

Note Taker is a local macOS desktop app that turns highlights from books into a personal, git-backed knowledge base. The user photographs yellow-highlighted pages of physical books (or pastes Kindle highlight text), drops a batch of photos into an Electron app, reviews and edits drafts extracted by a configurable OCR (Tesseract) or local vision model (Ollama), and pushes approved highlights as markdown sections appended to one file per book (`books/<slug>.md`) in a GitHub repo they own, so they can recall a book's takeaways and apply them at work.

**User story:** As a reader of fiction and work-related non-fiction who marks paper books with a highlighter and margin notes, when I finish a reading session I want to drop my page photos into one app, fix what the extractor got wrong, and push them to my notes repo, so that every takeaway from a book is in one markdown file I can reread later.

## Services

- **backend** (`backend/`) — FastAPI on 127.0.0.1:<random port>, token-guarded. Owns batch storage, extraction queue, markdown writer, git publishing, expiry janitor.
- **frontend** (`frontend/`) — Electron main process (spawns/stops backend) + React renderer (batch list, batch grid, review editor, settings).
- **External (local):** Ollama at `http://localhost:11434`, Tesseract binary, `git` CLI with the user's existing credentials.

## Dependencies

- Backend: fastapi, uvicorn, pydantic, httpx, pillow, opencv-python-headless, pytesseract, pyyaml, python-ulid, sse-starlette; dev: pytest, respx, freezegun
- Frontend: electron, electron-vite, react, typescript; dev: vitest, @testing-library/react, @playwright/test
- System: Ollama, Tesseract, git, uv, Node 20+

## Build, test, run

```bash
# Build
(cd backend && uv sync) && (cd frontend && npm ci && npm run build)

# Test (unit)
if [ -d backend ]; then (cd backend && uv run pytest -q); else echo "backend/ not created yet (plan Task 1)"; fi
if [ -f frontend/package.json ]; then (cd frontend && npx vitest run); else echo "frontend/ not created yet (plan Task 12)"; fi

# Integration tests
# Real-git integration tests (no Ollama needed). Live extractor tests are manual: (cd backend && uv run pytest -m live)
if [ -f backend/tests/test_api.py ]; then (cd backend && uv run pytest -q tests/test_git_publisher.py tests/test_push_service.py tests/test_push_recovery.py tests/test_api.py tests/test_api_*.py); else echo "integration tests not created yet (plan Tasks 5, 6, 11)"; fi

# UI / end-to-end tests (Electron e2e; separate gate, not run by scripts/integration.sh)
# bash scripts/ui-test.sh   # vitest + build + Playwright

# Run locally
cd frontend && npm run dev   # spawns the backend; or backend alone: cd backend && uv run python -m note_taker --port 8765 --token dev --data-dir /tmp/nt
```

## Key files

- `docs/superpowers/specs/2026-11-08-note-taker-design.md` — the design spec (§12 overrides earlier sections; §13 decision log)
- `docs/superpowers/plans/2026-11-08-note-taker.md` — 16-task implementation plan (source of truth for file names, interfaces, tests)
- `backend/src/note_taker/` — models, batch_store, markdown_writer, git_publisher, push_service, extraction_queue, extractors/, janitor, api/
- `frontend/electron/main/` (backend lifecycle), `frontend/src/screens/` (BatchList, BatchGrid, ReviewEditor, Settings)

## Gotchas

- **Never `git reset --hard`** in the notes repo; push refuses on a dirty clone. Photos are never committed.
- **Markdown is append-only**; each section ends with `<!-- nt:highlight=<id> -->` and writes are skipped if the marker exists (idempotent retries).
- Background extraction saves with `touch=False` so it doesn't reset batch expiry; user edits do.
- Expired batches are deleted only ≥24h after `warned_at` was set.
- `<img>`/`EventSource` can't send headers → token via `?token=` allowed only on `/captures/{id}/image` and `/batches/{id}/events`.
- Default tests exclude `-m live` (real Ollama/Tesseract). Phone photos may carry EXIF rotation, or be sideways in the pixels with no tag — always go through `load_upright(path, capture.rotation)`.
- Fixture photos carry GPS: only `backend/tests/fixtures/sample-p163.jpg` is committed; never commit unstripped phone photos.
- `.superpowers/` is brainstorm scratch (gitignored).

## Architecture rules (summary)

This project follows complexity-management principles (Ousterhout-style). Full rules in [docs/architecture-rules.md](docs/architecture-rules.md).

Five rules that override convenience:

1. **Deep modules over shallow** — simple interface, powerful implementation. If a module's interface is nearly as complex as its implementation, it isn't earning its keep.
2. **Hide information, don't leak it** — if changing one module forces changes in another, find and fix the leak.
3. **Pull complexity downward** — better for one module to be slightly more complex than for ten callers to be.
4. **Define errors out of existence** — prefer redefining the operation over throwing exceptions for every edge case.
5. **Comment the why, not the what** — code shows what; comments explain intent, constraints, and trade-offs.

## How Claude should work on this project

**Building v1 = executing the plan.** Work through [the plan](docs/superpowers/plans/2026-11-08-note-taker.md) task by task with **`superpowers:subagent-driven-development`** (the user chose this). The plan is the source of truth for file names, interfaces and tests. The [spec](docs/superpowers/specs/2026-11-08-note-taker-design.md) is the source of truth for intent, and its §12 overrides earlier sections. Never build on `main`; use a feature branch. Use `developer.md` / `code-reviewer.md` in `.claude/agents/` as role guidance for the implementer and reviewer subagents. Start each session with [session-handoff.md](session-handoff.md).

For changes **outside the plan**:
For any **non-trivial change** (anything beyond a typo, single-line fix, or trivial rename), dispatch the orchestrator subagent first:

```
Agent(subagent_type="orchestrator", prompt="<the task>")
```

The orchestrator will route through `architect → developer → tester → code-reviewer` (and `designer` if UI work). Subagents live in `.claude/agents/`.

For trivial changes, edit directly.

## Definition of Done

A feature is done when **all** of:

1. **Hard gates pass:** `scripts/test.sh`, `scripts/integration.sh`, `scripts/architecture-review.sh`. These block.
2. **Soft gates reported:** `scripts/lint.sh`, `scripts/code-review.sh`. Reports must be present and reviewed; warnings allowed.
3. App / service runs end-to-end (manual or scripted smoke test).
4. Feature appears in `feature_list.json` with `status: "pass"` and concrete `evidence`.
5. Structured logging added at service boundaries and failure paths.
6. `docs/` is updated (ARCHITECTURE.md if structure changed, PRODUCT.md if user story changed, RELIABILITY.md if performance characteristics changed).
7. `session-handoff.md`, `feature_list.json`, and `claude-progress.md` updated.
8. `clean-state-checklist.md` passes (run through it manually).
9. `evaluator-rubric.md` scored for the feature.
10. `quality-document.md` grades reflect current state.

## Session handoff & progress

Before ending a session, update [session-handoff.md](session-handoff.md) (what was accomplished, what remains, blockers, files modified, benchmarks) and append an entry to [claude-progress.md](claude-progress.md) (append-only session log with duration, goal, accomplishments, decisions, issues). Read both at the start of every session.

## Quality tracking

- [evaluator-rubric.md](evaluator-rubric.md) — per-feature scoring (1-5) with evidence notes, harness file assessment, validation gate results
- [quality-document.md](quality-document.md) — living quality report with letter grades per dimension, evidence of quality, benchmark results, quality trend over sessions

Update both after completing each feature.

## Clean state

Before merging, run through [clean-state-checklist.md](clean-state-checklist.md). It covers build, architecture, runtime, logging, data integrity, performance, repository, and scripts — each tailored to this project.

## Documentation map

- [docs/PRODUCT.md](docs/PRODUCT.md) — intent, user stories, scope
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system structure, modules, data flow
- [docs/RELIABILITY.md](docs/RELIABILITY.md) — performance targets, scale, observability
- [docs/architecture-rules.md](docs/architecture-rules.md) — full architecture rules
- [feature_list.json](feature_list.json) — feature inventory with pass/fail status
- [session-handoff.md](session-handoff.md) — current session state for next session
- [claude-progress.md](claude-progress.md) — append-only session log (duration, goals, decisions, benchmarks)
- [evaluator-rubric.md](evaluator-rubric.md) — per-feature scoring with evidence
- [quality-document.md](quality-document.md) — living quality report with grades and trend

## Tech stack & deployment

**Stack:** Backend: Python 3.12, uv, FastAPI/uvicorn, Pydantic v2, httpx, Pillow, OpenCV (headless), pytesseract, PyYAML. Frontend: Electron + React 19 + TypeScript via electron-vite. Extractors: Ollama vision model (local) or Tesseract OCR. Storage: JSON file + photos folder per batch in the Electron userData dir; notes in a git clone pushed to GitHub. No database.

**Deployment:** macOS only, dev-mode run (`npm run dev` in frontend/, which spawns the backend via `uv run`). Backend binds 127.0.0.1 with a per-launch token. Packaging/distribution is out of scope for v1. Prerequisites: Ollama (+ pulled vision model), `brew install tesseract`, uv, Node 20+.

**Performance targets:** Single local user. Per-photo extraction ≤180s timeout (concurrency 1, Ollama on a Mac); API calls other than extraction/push respond in <200ms locally; a push of a 30-photo batch completes in <30s excluding network.

**Scale targets:** One user, one machine. Batches of ~5–30 photos; several open batches at once. Local storage holds only in-progress batches (deleted on push or after 30-day expiry with warning) — it must not grow unbounded. Notes repo grows by markdown text only (no photos).
