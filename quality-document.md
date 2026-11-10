# Quality Document — note-taker

> Living quality report. Update after each major feature or session. Grades reflect current state, not aspirations.

## Scoring Summary

| Dimension | Grade | Notes |
|-----------|-------|-------|
| Build & Compile | A | `npm run build` (typecheck + electron-vite) clean; `uv sync` clean; no warnings in test output. |
| Feature Completeness | B | 14 of 16 features `pass`, 2 `partial` (Ollama and Tesseract extractors have never run against the real tools). All v1 spec goals implemented; non-goals respected. |
| Test Coverage | B+ | 423 backend tests (real git against a bare remote, concurrent pushes, crash recovery), 145 frontend tests, hermetic Kindle-path Electron e2e. Gaps: real-tool tests skipped/deselected; photo-path e2e never run. |
| Documentation | B | README, ARCHITECTURE, PRODUCT, RELIABILITY and the spec are current; `docs/deferred-findings.md` lists what is open. No user-facing screenshots/walkthrough. |
| Architecture Adherence | A- | `architecture-review.sh` passes (no file over 500 LOC; imports ≤ 15) with one documented exemption (composition roots `api/app.py`, `api/deps.py`). |
| Structured Logging | C | Plain-text stdlib logging to stderr (forwarded to the `npm run dev` terminal), with credential/token redaction; ids in log lines but not structured JSON. DoD item 5 asks for structured logging at boundaries. |
| Performance | C | Unmeasured. Targets in RELIABILITY.md are unverified; the image endpoint re-encodes the full 12 MP photo per request. |
| Harness Quality | B | Trackers, handoff and deferred-findings current as of session 2; `clean-state-checklist.md` was exercised through the gate scripts, not walked item by item. |

## Overall Grade: B

**Grading scale**: A = production-ready, no known issues. B = functional, minor gaps. C = works but significant gaps. D = partially functional. F = broken.

Held at B (not higher) because the OCR/vision paths are unverified on real photos and one known startup hang (recover() fetch timeout) is unfixed.

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
- `evaluator-rubric.md`: 4.0 / 5 overall.
- `feature_list.json`: 14 of 16 at status "pass" (2 "partial").
- `scripts/test.sh`: PASS (423 backend + 145 frontend; 2 tests skipped without Tesseract).
- `scripts/integration.sh`: PASS (188 backend integration tests).
- `scripts/architecture-review.sh`: PASS.
- `scripts/lint.sh`: clean (and honest since session 2: it previously reported clean while ruff found 17 errors).
- `scripts/code-review.sh`: not run as a gate; independent per-task and whole-branch reviews were done instead.

## Quality Trend

| Session | Date | Overall | Features passing | Notes |
|---------|------|---------|------------------|-------|
| 1 | 2026-11-08T16:09:58Z | n/a | 0 of 16 | Initial: design, plan, harness |
| 2 | 2026-11-09 | B | 14 of 16 (+2 partial) | v1 built; final review found 1 Critical + 7 Important, fixed in one wave; 1 Important residual (recover() fetch timeout) |
