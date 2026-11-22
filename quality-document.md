# Quality Document — note-taker

> Living quality report. Update after each major feature or session. Grades reflect current state, not aspirations.

## Scoring Summary

| Dimension | Grade | Notes |
|-----------|-------|-------|
| Build & Compile | A | `npm run build` (typecheck + electron-vite) clean; `uv sync` clean; no warnings in test output. |
| Feature Completeness | A- | 22 of 22 features `pass` (16 plan tasks plus 6 polish rows). Ollama live-validated on `qwen2.5vl:7b`; Tesseract 5.5.1 and the photo-path e2e were already recorded before this pass. Ollama residuals and the Found-while-polishing list remain. |
| Test Coverage | B+ | 548 backend tests (2 deselected live; real git against a bare remote, concurrent pushes, crash recovery), 252 vitest, 231 integration, Playwright 3 (Kindle smoke, back-out e2e, photo path). Re-run in this orchestration pass after the bookkeeping edits. Ollama live tests stay deselected by default. |
| Documentation | B | README, ARCHITECTURE, PRODUCT, RELIABILITY and the spec are current; `docs/deferred-findings.md` lists what is open. No user-facing screenshots/walkthrough. |
| Architecture Adherence | A- | Static stage clean this orchestration pass (no file over 500 lines, no file over 15 imports). The LLM stage was not verified: Claude CLI OAuth expired (`Failed to authenticate`), `scripts/architecture-review.sh` exit 1 (`AUDIT_ERROR`). That exit is auth, not an architecture-rule violation, and it is not a pass. |
| Structured Logging | C | Plain-text stdlib logging to stderr (forwarded to the `npm run dev` terminal), with credential/token redaction. `exc_info`, chained causes, and `stack_info` are masked. Ids in log lines but not structured JSON. DoD item 5 asks for structured logging at boundaries. |
| Performance | C | Unmeasured. Targets in RELIABILITY.md are unverified. The image route does not re-encode a 12 MP photo on every request: the first view decodes it to a ≤2000 px cache; repeats are a file read or a 304. Lookup is still O(open batches). |
| Harness Quality | B | Trackers, handoff and deferred-findings updated in the working tree through session 6 (not committed). `clean-state-checklist.md` was exercised through the gate scripts, not walked item by item. |

## Overall Grade: B

**Grading scale**: A = production-ready, no known issues. B = functional, minor gaps. C = works but significant gaps. D = partially functional. F = broken.

Held at B (not higher) because performance is unmeasured, logging is still plain text, and Ollama residuals plus the Found-while-polishing list remain.

## Evidence of Quality

### Build
`cd frontend && npm run build` passes; `npm run typecheck` clean for node and web; `cd backend && uv sync` clean.

### Runtime
The Kindle path runs end to end in a real Electron window against a real backend and a local bare git repo (create batch → add highlights → edit → approve → push → markdown file with markers and a commit with the batch trailer → local batch deleted): passed on 4 consecutive runs and again after the final fix wave. Settings, batch list/grid and review editor were each driven once in a real window. Not driven: photo capture rotate/Retry, live SSE updates, keyboard shortcuts, discard.

### Observability
Backend logs are plain text via stdlib logging with token and URL-credential redaction at the handler; stderr is forwarded to the terminal in dev. No metrics, no log files (by design: no unbounded local growth).

### Performance (benchmark results)
Not benchmarked. Operation timeouts are enforced instead: git 20 s local / 60 s network, `/health` remote check 5 s, `/books` sync 10 s, extraction 180 s, readiness probe is I/O-free.

## Verified Against

- `clean-state-checklist.md`: build, architecture, data-integrity and script items verified via the gate scripts; runtime smoke test = e2e Kindle path.
- `evaluator-rubric.md`: 4.1 / 5 overall.
- `feature_list.json`: 22 of 22 at status "pass".
- `scripts/test.sh`: exit 0 this orchestration pass, after the bookkeeping edits. pytest 548 passed, 2 deselected in 46.60s; vitest 252 passed in 2.41s.
- `scripts/integration.sh`: exit 0 this orchestration pass. 231 passed in 25.97s.
- `scripts/ui-test.sh`: exit 0 this orchestration pass. vitest 252, typecheck + electron-vite build succeeded, Playwright 3 passed in 16.3s (Kindle smoke, back-out e2e, photo path).
- `scripts/architecture-review.sh`: exit 1 this orchestration pass. Not a pass. Static stage clean (no file over 500 lines, no file over 15 imports). LLM stage did not run: OAuth expired (`Failed to authenticate`), script recorded `AUDIT_ERROR`. The exit 1 is auth, not an architecture-rule violation. The hard gate is not claimed.
- `scripts/lint.sh`: exit 0 this orchestration pass. ruff clean, frontend typecheck passed. Honest since session 2 (it once reported clean while ruff found 17 errors).
- `scripts/code-review.sh`: exit 0, but the LLM stage did not run (placeholder in `.claude-review.md`, same expired OAuth). Not verified. Not a pass. A manual code review (M1, M2, m1-m9) stands in for it.

## Quality Trend

| Session | Date | Overall | Features passing | Notes |
|---------|------|---------|------------------|-------|
| 1 | 2026-11-08T16:09:58Z | n/a | 0 of 16 | Initial: design, plan, harness |
| 2 | 2026-11-09 | B | 14 of 16 (+2 partial) | v1 built; final review found 1 Critical + 7 Important, fixed in one wave; 1 Important residual (recover() fetch timeout) |
| 6 | 2026-11-22 | B | 22 of 22 | Deferred-findings polish on `polish/deferred-findings`. This orchestration pass re-ran the gates after the bookkeeping edits: test.sh 548 backend (2 deselected live) and 252 vitest, integration 231, ui-test Playwright 3, lint clean. `architecture-review.sh` exit 1 is expired OAuth (`AUDIT_ERROR`), not a finding and not a pass. `code-review.sh` wrote only a placeholder. |
