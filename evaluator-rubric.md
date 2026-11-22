# Evaluator Rubric — note-taker

> Evaluate every feature against its DoD criteria. Update after each feature is completed.

## Overall Assessment

**Project**: note-taker
**Description**: Local macOS Electron app that turns photos of yellow-highlighted book pages (or pasted Kindle highlights) into reviewed markdown sections appended to one file per book (`books/<slug>.md`) in a user-owned GitHub repo, extracted by a configurable OCR (Tesseract) or local vision model (Ollama).
**Evaluator**: Automated gates + independent subagent reviews (per task and whole branch); manual real-window checks by the implementers
**Date**: 2026-11-22

### Scoring (1-5 scale)

| Criterion | Score | Notes |
|-----------|-------|-------|
| backend-scaffold-models | 5 | Clean models/paths/atomic JSON; approved with 0 fix rounds. |
| batch-store | 4 | Review caught an unvalidated batch id (rmtree hazard), fixed. `BatchStore.list()` skips a corrupt `batch.json` (`bb9cb55`, `7e9f1e5`); a skipped batch stays hidden (Found while polishing). |
| markdown-writer | 4 | Byte-preserving append + markers. Note-line marker forgery, a newline in a heading, and a 0-byte book file are fixed (`a185d27`, `7e9f1e5`). Score unchanged this pass. |
| book-catalog | 4 | Quarantine + slug-only listing after review; unlocked create deferred. |
| git-publisher | 4 | Rollback/dirty-check hardened after review, timeouts added in the final wave; hung-rebase corner case accepted. |
| push-service | 4 | Idempotent, crash-recoverable, snapshot-compare, branch guard. The recover() fetch timeout is fixed on main (session 5). `same_remote` and bookkeeping reopen (`2625988`, `7e9f1e5`). |
| extraction-queue | 4 | Per-run claim tokens, outcome gating; unexpected-exception leftovers deferred. |
| ollama-extractor | 4 | Live-validated on `qwen2.5vl:7b` (p163 + 9 fixtures, ~383 s); `num_ctx=8192`, truncation fails the capture. Residuals: page=None on 3/9, one repeated note (user-editable). |
| tesseract-extractor | 4 | Real binary verified: session 5 and `feature_list.json` record tesseract 5.5.1 and the photo-path e2e. HSV thresholds on real GPS fixture photos still un-tuned. |
| janitor | 4 | Warning must belong to the current window; skips pushing batches. |
| rest-api | 4 | Strong trust boundary (token, whitelists, caps, masking); small deferred items. |
| electron-shell | 4 | Hardened window, process-group kill, readable startup errors; startup-failure dialog not driven in a GUI. |
| batch-screens | 4 | Safe rendering, confirm dialog, upload handling; polish items deferred. |
| review-editor | 4 | Autosave never drops edits after review fixes. IME composition is ignored and a bad page such as "12a" is flagged in the field (`dd92c00`). Photo-capture rotate/Retry and keyboard shortcuts are still not driven in a real window. |
| settings-screen | 4 | Masked-URL round trip and credential notice correct. A 422 focuses the first mapped field and counts the fields in the alert (`01c9b12`). |
| e2e-readme | 4 | Hermetic e2e, honest README. The photo path has run (tesseract 5.5.1, synthetic yellow-highlight PNGs). |

### Overall: 4.1 / 5

`tesseract-extractor` moved from 3 to 4. Every other row stays. No row is 5. (5 + 15×4) / 16 = 4.1.

### Harness File Assessment

| File | Present | Quality | Notes |
|------|---------|---------|-------|
| CLAUDE.md | Yes | Good | Updated for the plan workflow and test commands; ~135 lines. |
| feature_list.json | Yes | Good | 22 features (16 plan tasks plus the six polish rows), each pass with commit and test evidence. |
| claude-progress.md | Yes | Good | Through session 6. |
| session-handoff.md | Yes | Good | Polish branch, unverified LLM gates, and the Found-while-polishing list. Updated in the working tree, not committed. |
| clean-state-checklist.md | Yes | Good | Project-specific; verified through gate scripts, not item by item. |
| evaluator-rubric.md | Yes | Good | This file |
| quality-document.md | Yes | Good | Grades and trend filled in. |

### Documentation Assessment

| File | Present | Quality | Notes |
|------|---------|---------|-------|
| docs/ARCHITECTURE.md | Yes | Good | Data dir corrected to `note-taker-frontend`. |
| docs/PRODUCT.md | Yes | Good | Filled from the spec. |
| docs/RELIABILITY.md | Yes | Good | Plain-text logging and timeouts documented. |
| docs/architecture-rules.md | Yes | Template | Unchanged template rules. |
| docs/deferred-findings.md | Yes | Good | Added in session 2: residual fix, should-fix list, accepted limitations. |

### Validation Gate Results

| Gate | Type | Status | Notes |
|------|------|--------|-------|
| scripts/test.sh | Hard | Pass | Re-run in this orchestration pass after the bookkeeping edits: exit 0. pytest 548 passed, 2 deselected in 46.60s; vitest 252 passed in 2.41s. |
| scripts/integration.sh | Hard | Pass | Re-run in this orchestration pass after the bookkeeping edits: exit 0. 231 passed in 25.97s. |
| scripts/ui-test.sh | Separate | Pass | Re-run in this orchestration pass after the bookkeeping edits: exit 0. vitest 252, typecheck + electron-vite build succeeded, Playwright 3 passed in 16.3s (Kindle smoke, back-out e2e, photo path). |
| scripts/architecture-review.sh | Hard | Unverified | Re-run in this orchestration pass after the bookkeeping edits: exit 1. Not a pass. Static stage clean (no file over 500 lines, no file over 15 imports). LLM stage did not run: Claude CLI OAuth session expired (`Failed to authenticate`), script recorded `AUDIT_ERROR`. The exit 1 is that auth line, not an architecture-rule violation. |
| scripts/lint.sh | Soft | Pass | Re-run in this orchestration pass after the bookkeeping edits: exit 0. ruff clean, frontend typecheck passed. Honest since session 2. |
| scripts/code-review.sh | Soft | Not verified | Re-run in this orchestration pass after the bookkeeping edits: exit 0, but the LLM stage did not run (placeholder in `.claude-review.md`, same expired OAuth). Not a pass. A manual code review (M1, M2, m1-m9) stands in for it. |

### Summary

The core flow (drop → extract → review → approve → push → clean up, plus the Kindle path and expiry with warning) is implemented carefully and covered by real-git and real-window tests. The reviews were effective: they found and fixed several data-loss and safety bugs that the original tests had not caught (an unvalidated delete path, CRLF rewrites, unsafe rollback, stale expiry warnings, silent edit loss, orphaned backend, pushing the wrong branch, a startup hang with a configured remote, and a lint script that reported clean while ruff failed).

The polish items above are closed: a corrupt `batch.json` no longer breaks `list()`, note-line marker forgery and heading newlines are fixed, the recover-fetch startup hang is fixed on main, IME and page-field polish and Settings focus are in, the photo path has been run, and Tesseract has been run with the real binary (5.5.1). Ollama residuals (page null on 3 of 9 fixtures, one repeated note) and the Found-while-polishing list in `docs/deferred-findings.md` remain.
