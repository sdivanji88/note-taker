# Session Handoff — note-taker

> Read this at the start of every session. Update it before ending every session.

**Last updated:** 2026-11-21 (Session 3: Ollama live validation Pass 1 + Pass 2 on branch `feat/ollama-live-validation`; Session 2 built v1)

---

## What was accomplished

- **Session 3 (Ollama live validation, Pass 2 close):** no prompt change (page=None on 3/9, one note repeating highlight text: accepted residuals, user-editable). Added `done_reason == "length"` -> `ExtractionError` with a unit test. Live suite re-run: 2 passed in 382.68 s. `ollama-extractor` is now `pass`.
- **Session 3 (Ollama live validation, Pass 1):** live bakeoff on qwen2.5vl:3b, qwen2.5vl:7b and granite3.2-vision. Winner and default: `qwen2.5vl:7b` (3b: page=None on p163; granite: no match + 180 s timeout). Real fix found: Ollama's default 4096-token context truncated the JSON (`done_reason=length`), so `OllamaVisionExtractor` now sends `options.num_ctx=8192` (unit-tested). Both `-m live` tests pass with the env override unset (p163 and the 9-photo fixture report, ~430 s). Schema unchanged (nullable unions accepted). Tesseract is still unverified.

- All 16 plan tasks were built test-first by subagents, each with its own spec+quality review and fix loop, then a final whole-branch review and one final fix wave (12 commits). Branch `feat/note-taker-v1` is ~50 commits ahead of `main` (merge base `9c894d0`); nothing has been merged or pushed.
- Backend (Python/FastAPI, `backend/`): batch store, append-only markdown writer, book catalog, safe git publisher, idempotent push service with crash recovery, extraction queue, Ollama and Tesseract extractors, expiry janitor, token-guarded REST API + SSE. **423 tests pass** (2 skipped need Tesseract; 2 `-m live` tests deselected).
- Frontend (Electron + React, `frontend/`): hardened shell that spawns the backend, typed API client, batch list/grid, one-page-at-a-time review editor with autosave, settings + repo connection. **145 tests pass**; the Kindle-path e2e test passes.
- Gates: `scripts/architecture-review.sh` passes (one documented composition-root exemption), `scripts/lint.sh` is clean and now reports honestly.

## What remains

1. **Fix first** (found by the last review, not fixed): `PushService.recover()` fetches with the default 60 s network timeout inside the FastAPI lifespan, longer than Electron's 20 s readiness budget — after a crash mid-push on a slow remote the app can fail to start. One line: `git.fetch(timeout_s=_SYNC_TIMEOUT_S)` in `backend/src/note_taker/push_service.py` (~:167), plus a test with a hanging fetch. Details: `docs/deferred-findings.md`.
2. **Tesseract, HSV, and the photo-path e2e** (Tesseract was not installed where this was built): `brew install tesseract`, then run the photo-path e2e (`bash scripts/ui-test.sh`) and tune the yellow HSV range and rotation detection on the 7 real photos in `backend/tests/fixtures/` (gitignored — they carry GPS; only `sample-p163.jpg` is committed). Ollama Pass 1 is done; `qwen2.5vl:7b` is the tested default.
3. Work through the "Should fix soon" list in `docs/deferred-findings.md`.
4. Decide how to integrate the branch (merge/PR) — see below.

## Blockers / decisions made

- **Decision:** execution was superpowers:subagent-driven-development; every ruling the controller took on the user's behalf is in the git-ignored ledger `.superpowers/sdd/2026-11-08-note-taker/progress.md` (lines starting `Ruling:`), which was kept. The important ones: the bbox overlay was dropped (the backend does not persist boxes); rotating a `ready` capture changes the view only (re-running extraction would overwrite edits); capture edits are refused while pending/extracting/pushing; an expiry warning counts only if given in the current window; the push refuses when the clone is on the wrong branch or `origin` differs from Settings; `origin_url` is compared as the raw config string.
- **Decision:** the real Electron data dir is `~/Library/Application Support/note-taker-frontend/` (package name), not `note-taker`.
- **Side effect to know about:** earlier real-window checks left only Chromium cache files in that directory (no settings, batches or notes). Safe to delete.
- **Needs from user:** nothing blocks; next work is Tesseract/HSV/photo-path e2e (item 2).

## Files modified

Everything under `backend/`, `frontend/`, `scripts/`, `docs/`, `README.md`, `CLAUDE.md` and the harness trackers (`feature_list.json`, `claude-progress.md`, `quality-document.md`, `evaluator-rubric.md`, this file). `git log main..feat/note-taker-v1` lists the commits.

## Benchmark results (if applicable)

None. Performance targets in `docs/RELIABILITY.md` are unmeasured (the image endpoint re-encodes the full photo per request — see deferred findings).

## Next session — start here

Read `CLAUDE.md`, then `docs/deferred-findings.md`. Check out `feat/ollama-live-validation`. Ollama is done (Pass 1 + 2). Next: Tesseract, the yellow HSV range, and the photo-path e2e (item 2). The `recover()` timeout fix (item 1) is still open. Run `bash scripts/test.sh`, `scripts/integration.sh`, `scripts/architecture-review.sh`, `scripts/lint.sh` and `scripts/ui-test.sh` before changing anything else; those gates passed at the end of session 2, and the Ollama `-m live` suite passed in session 3.
