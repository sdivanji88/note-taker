# Session Handoff — note-taker

> Read this at the start of every session. Update it before ending every session.

**Last updated:** 2026-11-22 (Session 4: Tesseract + photo-path e2e on `feat/ollama-live-validation`)

---

## What was accomplished

- **Session 4 (Tesseract + photo-path e2e):** tesseract 5.5.1 already on PATH (`brew`). Real-binary Tesseract tests (29) and imaging OSD/rotation (5) pass. `bash scripts/ui-test.sh`: vitest 145, build, Playwright **2/2** including photo path (~5.6s) with synthetic yellow-highlight PNGs. `tesseract-extractor` and `e2e-readme` evidence updated; both `pass`. HSV on real GPS fixtures still optional residual.
- **Session 3 (Ollama live validation, Pass 2 close):** no prompt change (page=None on 3/9, one note repeating highlight text: accepted residuals, user-editable). Added `done_reason == "length"` -> `ExtractionError` with a unit test. Live suite re-run: 2 passed in 382.68 s. `ollama-extractor` is now `pass`.
- **Session 3 (Ollama live validation, Pass 1):** live bakeoff on qwen2.5vl:3b, qwen2.5vl:7b and granite3.2-vision. Winner and default: `qwen2.5vl:7b` (3b: page=None on p163; granite: no match + 180 s timeout). Real fix found: Ollama's default 4096-token context truncated the JSON (`done_reason=length`), so `OllamaVisionExtractor` now sends `options.num_ctx=8192` (unit-tested). Both `-m live` tests pass with the env override unset (p163 and the 9-photo fixture report; ~430 s then, ~383 s in the Pass 2 re-run). Schema unchanged (nullable unions accepted).

- All 16 plan tasks were built test-first by subagents, each with its own spec+quality review and fix loop, then a final whole-branch review and one final fix wave (12 commits). Branch `feat/note-taker-v1` is ~50 commits ahead of `main` (merge base `9c894d0`); nothing has been merged or pushed.
- Backend (Python/FastAPI, `backend/`): batch store, append-only markdown writer, book catalog, safe git publisher, idempotent push service with crash recovery, extraction queue, Ollama and Tesseract extractors, expiry janitor, token-guarded REST API + SSE. **423 tests pass** (2 skipped need Tesseract; 2 `-m live` tests deselected).
- Frontend (Electron + React, `frontend/`): hardened shell that spawns the backend, typed API client, batch list/grid, one-page-at-a-time review editor with autosave, settings + repo connection. **145 tests pass**; the Kindle-path e2e test passes.
- Gates: `scripts/architecture-review.sh` passes (one documented composition-root exemption), `scripts/lint.sh` is clean and now reports honestly.

## What remains

1. **Fix first** (found by the last review, not fixed): `PushService.recover()` fetches with the default 60 s network timeout inside the FastAPI lifespan, longer than Electron's 20 s readiness budget — after a crash mid-push on a slow remote the app can fail to start. One line: `git.fetch(timeout_s=_SYNC_TIMEOUT_S)` in `backend/src/note_taker/push_service.py` (~:167), plus a test with a hanging fetch. Details: `docs/deferred-findings.md`.
2. **Optional:** tune yellow HSV / two-column merge on real GPS fixture photos if phone OCR misses highlights (synthetic e2e already green).
3. Work through the "Should fix soon" list in `docs/deferred-findings.md`.
4. Decide how to integrate `feat/ollama-live-validation` (merge/PR).

## Blockers / decisions made

- **Decision:** execution was superpowers:subagent-driven-development; every ruling the controller took on the user's behalf is in the git-ignored ledger `.superpowers/sdd/2026-11-08-note-taker/progress.md` (lines starting `Ruling:`), which was kept. The important ones: the bbox overlay was dropped (the backend does not persist boxes); rotating a `ready` capture changes the view only (re-running extraction would overwrite edits); capture edits are refused while pending/extracting/pushing; an expiry warning counts only if given in the current window; the push refuses when the clone is on the wrong branch or `origin` differs from Settings; `origin_url` is compared as the raw config string.
- **Decision:** the real Electron data dir is `~/Library/Application Support/note-taker-frontend/` (package name), not `note-taker`.
- **Side effect to know about:** earlier real-window checks left only Chromium cache files in that directory (no settings, batches or notes). Safe to delete.
- **Needs from user:** nothing blocks; finish choice for this branch (merge / PR / keep).

## Files modified

- **Branch `feat/ollama-live-validation`** (vs `main`): `backend/src/note_taker/models.py` (`NOTE_TAKER_OLLAMA_MODEL` default, whitespace-stripped), `backend/src/note_taker/extractors/ollama.py` (`num_ctx=8192`, truncation -> `ExtractionError` + warning log), `backend/tests/test_models.py`, `backend/tests/test_ollama_extractor.py` (+ live tests), `README.md`, `docs/deferred-findings.md`, `feature_list.json`, `session-handoff.md`, `quality-document.md`, `evaluator-rubric.md`, and the design/plan under `docs/superpowers/`.
- **Branch `feat/note-taker-v1`:** Everything under `backend/`, `frontend/`, `scripts/`, `docs/`, `README.md`, `CLAUDE.md` and the harness trackers (`feature_list.json`, `claude-progress.md`, `quality-document.md`, `evaluator-rubric.md`, this file). `git log main..feat/note-taker-v1` lists the commits.

## Benchmark results (if applicable)

None. Performance targets in `docs/RELIABILITY.md` are unmeasured (the image endpoint re-encodes the full photo per request — see deferred findings).

## Next session — start here

Read `CLAUDE.md`, then `docs/deferred-findings.md`. Branch `feat/ollama-live-validation` has Ollama Pass 1+2, Tesseract binary verification, and photo-path e2e green. Next: `recover()` timeout fix (item 1), or integrate the branch. `scripts/ui-test.sh` passed 2026-11-22 (Kindle + photo).
