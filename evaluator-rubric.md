# Evaluator Rubric — note-taker

> Evaluate every feature against its DoD criteria. Update after each feature is completed.

## Overall Assessment

**Project**: note-taker
**Description**: Local macOS Electron app that turns photos of yellow-highlighted book pages (or pasted Kindle highlights) into reviewed markdown sections appended to one file per book (`books/<slug>.md`) in a user-owned GitHub repo, extracted by a configurable OCR (Tesseract) or local vision model (Ollama).
**Evaluator**: Automated gates + independent subagent reviews (per task and whole branch); manual real-window checks by the implementers
**Date**: 2026-11-09

### Scoring (1-5 scale)

| Criterion | Score | Notes |
|-----------|-------|-------|
| backend-scaffold-models | 5 | Clean models/paths/atomic JSON; approved with 0 fix rounds. |
| batch-store | 4 | Review caught an unvalidated batch id (rmtree hazard), fixed; later gaps (single corrupt batch.json breaks `list()`) deferred. |
| markdown-writer | 4 | Byte-preserving append + markers; note-line marker forgery and newline-in-heading deferred. |
| book-catalog | 4 | Quarantine + slug-only listing after review; unlocked create deferred. |
| git-publisher | 4 | Rollback/dirty-check hardened after review, timeouts added in the final wave; hung-rebase corner case accepted. |
| push-service | 4 | Idempotent, crash-recoverable, snapshot-compare, branch guard; residual: recover() fetch timeout can block startup. |
| extraction-queue | 4 | Per-run claim tokens, outcome gating; unexpected-exception leftovers deferred. |
| ollama-extractor | 3 | Well tested with mocks; never run against a real Ollama (model and schema unverified). |
| tesseract-extractor | 3 | Region finding tested on synthetic images; never run with the real binary. |
| janitor | 4 | Warning must belong to the current window; skips pushing batches. |
| rest-api | 4 | Strong trust boundary (token, whitelists, caps, masking); small deferred items. |
| electron-shell | 4 | Hardened window, process-group kill, readable startup errors; startup-failure dialog not driven in a GUI. |
| batch-screens | 4 | Safe rendering, confirm dialog, upload handling; polish items deferred. |
| review-editor | 4 | Autosave never drops edits after review fixes; IME/number-input polish deferred. |
| settings-screen | 4 | Masked-URL round trip and credential notice correct; focus/race polish deferred. |
| e2e-readme | 4 | Hermetic e2e, honest README; photo-path test never run. |

### Overall: 4.0 / 5

### Harness File Assessment

| File | Present | Quality | Notes |
|------|---------|---------|-------|
| CLAUDE.md | Yes | Good | Updated for the plan workflow and test commands; ~135 lines. |
| feature_list.json | Yes | Good | 14 pass, 2 partial, each with commit and test evidence. |
| claude-progress.md | Yes | Good | Sessions 1 and 2. |
| session-handoff.md | Yes | Good | States the residual fix, live-tool verification and branch state. |
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
| scripts/test.sh | Hard | Pass | 423 backend + 145 frontend; 2 skipped (no Tesseract). |
| scripts/integration.sh | Hard | Pass | 188 backend integration tests. |
| scripts/architecture-review.sh | Hard | Pass | Stage 1 clean with the documented composition-root exemption; stage 2 PASS. |
| scripts/lint.sh | Soft | Pass | Honest since session 2. |
| scripts/code-review.sh | Soft | Not run | Independent reviews were done per task and for the whole branch. |

### Summary

The core flow (drop → extract → review → approve → push → clean up, plus the Kindle path and expiry with warning) is implemented carefully and covered by real-git and real-window tests. The reviews were effective: they found and fixed several data-loss and safety bugs that the original tests had not caught (an unvalidated delete path, CRLF rewrites, unsafe rollback, stale expiry warnings, silent edit loss, orphaned backend, pushing the wrong branch, a startup hang with a configured remote, and a lint script that reported clean while ruff failed).

What needs work: the two extractors have never run against the real tools or real photos, so accuracy and the default model are unknown; one startup path (recover() fetch timeout after a crash mid-push on a slow remote) is still open; and a list of smaller robustness and UI-polish items is recorded in `docs/deferred-findings.md`.
