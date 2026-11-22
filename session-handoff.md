# Session Handoff — note-taker

> Read this at the start of every session. Update it before ending every session.

**Last updated:** 2026-11-22 (session 6: polish branch `polish/deferred-findings`, not pushed, not merged; this orchestration pass re-ran the gates after the bookkeeping edits)

---

## What was accomplished

- **Session 6:** On `polish/deferred-findings` (branched from `main` after PR #3) closed every "Should fix soon" item in `docs/deferred-findings.md` except Ollama, plus the origin-comparison residual and the wrong-branch/remote notice residual. The recover-fetch timeout was already fixed on main (`7f792c9`, PR #3, session 5). Nothing from the polish list was deferred. Ten commits, one area each:
  - `bb9cb55` storage: corrupt `settings.json` is quarantined (`settings.json.corrupt`) and defaults are used; `BatchStore.list()` skips corrupt/unreadable `batch.json` and stray files (the old `list_readable()` is gone); tracebacks are redacted.
  - `a185d27` markdown: forged-marker note lines, heading collapse for chapter/title, 0-byte book file, duplicate highlight ids in a PATCH.
  - `2625988` push: `same_remote` URL equivalence; a failure after a good `git push` reopens the batch and logs "pushed but bookkeeping failed".
  - `560de31` extraction: OSD `timeout=30`, quiet health tick, margin note kept without highlights, `captured_at` catches any EXIF failure.
  - `ad9195c` api: `health.repo.problem`, `error.fields` on 422, `DELETE ?only_if_empty=true`, cached ≤2000 px previews with `ETag` and `Cache-Control: private, no-cache`.
  - `dd92c00` ui: SSE `onState` / `useBatchUpdates`, Discard reload, thumbnail numbering and empty state, page text input validation, 409/422 save-error copy, Cmd+Enter IME/read-only guard, silent stderr in `backend.test.ts`.
  - `01c9b12` ui: repo-problem notice and HealthPanel row, per-batch expiring pill, Settings 422 field focus, back-out cleanup of an empty batch or blank Kindle capture.
  - `749f5ea` tests: gaps closed, e2e back-out test.
  - `7e9f1e5`, `410f11c` review fixes from a manual code review (findings M1, M2, m1-m9, mostly fixed): tolerant `list()`, strict `same_remote` for paths, one warning per bad batch, `BatchNotFound` in finish = done, `clone_problem` None while a push holds the lock, settings load/save lock, note continuation whitespace, blank-Kindle delete safety, pill wording.
- Bookkeeping is in the working tree and not committed: `feature_list.json`, `claude-progress.md`, `evaluator-rubric.md`, and `quality-document.md`, plus `docs/ARCHITECTURE.md`, `docs/PRODUCT.md`, `docs/RELIABILITY.md`, and `docs/deferred-findings.md` (fixed items struck through, new "Found while polishing" section).

## Validation gates (be honest about these)

| Gate | Result |
|------|--------|
| `scripts/test.sh` | Re-run in this orchestration pass after the bookkeeping edits: exit 0. pytest 548 passed, 2 deselected in 46.60s; vitest 252 passed in 2.41s. |
| `scripts/integration.sh` | Re-run in this orchestration pass after the bookkeeping edits: exit 0. 231 passed in 25.97s. |
| `scripts/ui-test.sh` | Re-run in this orchestration pass after the bookkeeping edits: exit 0. vitest 252, typecheck + electron-vite build succeeded, Playwright 3 passed in 16.3s (Kindle smoke, back-out e2e, photo path). |
| `scripts/lint.sh` | Re-run in this orchestration pass after the bookkeeping edits: exit 0. ruff clean, frontend typecheck passed. |
| `scripts/architecture-review.sh` | Re-run in this orchestration pass after the bookkeeping edits: exit 1. **Not a pass.** Static stage clean (no file over 500 lines, no file over 15 imports). The LLM stage did not run: Claude CLI OAuth session expired (`Failed to authenticate`), and the script recorded `AUDIT_ERROR`. The exit 1 is that auth line, not an architecture-rule violation. |
| `scripts/code-review.sh` | Re-run in this orchestration pass after the bookkeeping edits: exit 0, but the LLM stage did not run (placeholder in `.claude-review.md`, same expired OAuth). **Not verified.** A manual code review (M1, M2, m1-m9) stands in for it. |

## What remains

1. Re-authenticate the `claude` CLI, then re-run `scripts/architecture-review.sh` (hard gate) and `scripts/code-review.sh` (soft) and review the reports.
2. Review and merge the PR for `polish/deferred-findings` (not yet pushed; no PR exists).
3. Open items in `docs/deferred-findings.md` under "Found while polishing (2026-11-22)": hidden corrupt `batch.json` (optionally count skipped batches in `/health`), silent settings reset, finished batch with failed `delete_if` never expires, empty batch/blank Kindle left after a crash, image route O(open batches) before the 304, odd "0 highlights / 0 files" on a retry after a bookkeeping failure, lazy previews.
4. Still open from before: the Ollama residuals and the Known limitations (unchanged); optional HSV tuning on real GPS fixture photos; packaging out of scope.

## Blockers / decisions made

- **Blocker:** `claude` CLI OAuth session expired (environmental). Blocks the architecture-review LLM stage and `code-review.sh`. Needs the user to sign in again.
- Architect's contracts won over the designer's proposals: `repo.problem` lives under `health.repo` (not a separate `health.publisher`), and 422s carry a structured `error.fields` list while `message` stays the human text (no client-side message parsing).
- Back-out is delete-on-back-out (`DELETE ?only_if_empty=true`), not lazy creation of the batch/capture, so the existing create-then-edit flow and its tests stay as they are.
- Previews are served with an `ETag` and `no-cache` (revalidate, 304) rather than long-lived caching, so a rotation shows at once.

## Clean-state checklist walk-through (no boxes ticked in `clean-state-checklist.md`)

- Build: re-run in this orchestration pass after the bookkeeping edits, inside `scripts/ui-test.sh` (exit 0): typecheck + electron-vite build succeeded. `uv sync` and `npm ci` were not part of that run.
- Architecture: static stage clean (no file over 500 lines, no file over 15 imports). LLM stage did not run (`scripts/architecture-review.sh` exit 1, OAuth expired, `AUDIT_ERROR`). Not a pass. `docs/ARCHITECTURE.md` updated.
- Runtime / smoke: re-run in this orchestration pass after the bookkeeping edits. Playwright 3 passed in 16.3s (Kindle smoke, back-out e2e, photo path).
- Logging: plain-text stdlib logging with redaction, now also covering tracebacks; still not structured JSON (quality grade stays C).
- Data integrity: covered by tests (markers, forged-marker, bookkeeping retry). Not walked item by item.
- Performance: unmeasured. The image route is still O(open batches) per request.
- Repository: `.claude-review.md` and `ocr_debug.log` are gitignored and untracked. `feature_list.json`, `claude-progress.md`, `evaluator-rubric.md`, `quality-document.md`, `docs/ARCHITECTURE.md`, `docs/PRODUCT.md`, `docs/RELIABILITY.md`, and `docs/deferred-findings.md` are updated in the working tree and not committed.
- Scripts: see the gate table.

## Files modified (polish branch)

- Backend: `batch_store.py`, `books.py`, `janitor.py`, `jsonio.py`, `redact.py`, `settings_store.py`, `markdown_writer.py`, `push_service.py`, `extraction_queue.py`, `imaging.py`, `paths.py`, `api/` (`deps`, `errors`, `routes_*`), plus new/extended tests (`test_previews.py`, `test_push_bookkeeping.py`, `test_redact.py` new).
- Frontend: `api/client.ts`, `api/types.ts`, `hooks/useBatchUpdates.ts`, `hooks/useCaptureDraft.ts`, `components/` (`CapturePane`, `HealthPanel`, `Thumb`), `screens/` (`BatchGrid`, `BatchList`, `ReviewEditor`, `Settings`, `settingsForm`), `format.ts`, `review/`, `styles.css`, tests and `e2e/smoke.spec.ts`.
- Docs, in the working tree and not committed: `feature_list.json`, `claude-progress.md`, `evaluator-rubric.md`, `quality-document.md`, `session-handoff.md`, `docs/ARCHITECTURE.md`, `docs/PRODUCT.md`, `docs/RELIABILITY.md`, `docs/deferred-findings.md`.

## Benchmark results (if applicable)

- This orchestration pass, after the bookkeeping edits: pytest 548 passed, 2 deselected in 46.60s; vitest 252 passed in 2.41s; integration 231 passed in 25.97s; Playwright 3 passed in 16.3s (Kindle smoke, back-out e2e, photo path). `scripts/architecture-review.sh` exit 1 is expired OAuth, not a pass. `scripts/code-review.sh` wrote only a placeholder.
- Not benchmarked: image preview latency, `GET /batches` with many batches.

## Next session — start here

1. Sign in to the `claude` CLI again; run `bash scripts/architecture-review.sh` and `bash scripts/code-review.sh`; fix anything real they report.
2. Push `polish/deferred-findings`, open the PR, review and merge it.
3. Then decide whether any "Found while polishing" item is worth doing; otherwise stop.
