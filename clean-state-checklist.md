# Clean State Checklist — note-taker

Run through this checklist before merging any non-trivial change. Each section has hard checks (must pass) and discretion checks (judge per change).

---

## 1. Build

- [ ] `(cd backend && uv sync) && (cd frontend && npm ci && npm run build)` completes with exit 0
- [ ] No new uncommitted lockfile changes that weren't intended
- [ ] Build artifacts are gitignored (no `dist/`, `target/`, `__pycache__/` in `git status`)
- [ ] `cd backend && uv sync --locked` and `cd frontend && npm ci` succeed. `uv.lock` and `package-lock.json` are committed

## 2. Architecture

- [ ] `scripts/architecture-review.sh` passes (hard gate)
- [ ] No module added with a shallow interface (interface complexity ≈ implementation complexity)
- [ ] No information leak introduced (a single change should not require edits in unrelated modules)
- [ ] New errors are defined out of existence where possible, not thrown
- [ ] `docs/ARCHITECTURE.md` updated if module boundaries changed
- [ ] Layering: `api/` → services (`push_service`, `extraction_queue`, `janitor`) → stores/adapters (`batch_store`, `books`, `markdown_writer`, `git_publisher`, `extractors/`). Adapters never import `api/`. The frontend talks to the backend only through `src/api/client.ts`

## 3. Runtime

- [ ] `cd frontend && npm run dev   # spawns the backend; or backend alone: cd backend && uv run python -m note_taker --port 8765 --token dev --data-dir /tmp/nt` starts the app/service cleanly
- [ ] Smoke test: `cd backend && uv run python -m note_taker --port 8765 --token t --data-dir /tmp/nt` then `curl -s -H 'X-Session-Token: t' localhost:8765/health` returns JSON (and returns 401 without the header)
- [ ] No errors or unexpected warnings in startup logs
- [ ] All declared services in CLAUDE.md actually start
- [ ] The backend listens on 127.0.0.1 only (`lsof -iTCP -sTCP:LISTEN | grep python` shows 127.0.0.1). Quitting Electron kills the backend process

## 4. Logging

- [ ] Structured logging present at every service boundary (request in, response out, external call)
- [ ] No `print()` / `console.log()` left in production paths
- [ ] Log entries include: timestamp, level, service tag, message, structured data payload
- [ ] Errors logged with stack trace + context, not bare messages
- [ ] Logs include `batch_id`/`capture_id` on extraction, push and janitor events. Session tokens and git credentials are never logged

## 5. Data integrity

- [ ] Schema migrations (if any) are reversible OR explicitly documented as one-way with rationale
- [ ] No dangling references between entities (run `scripts/cleanup-scanner.sh` if present)
- [ ] Persistence tests cover round-trip serialize/deserialize
- [ ] Reset / clean-slate path works end-to-end
- [ ] Pushing the same batch twice writes no duplicate sections (`nt:highlight=` markers unique). A finished batch's folder is gone from `batches/`. Hand edits in `books/*.md` survive a push byte-for-byte. No photos in the notes repo

## 6. Performance

- [ ] Latency target met: Single local user. Per-photo extraction ≤180s timeout (concurrency 1, Ollama on a Mac); API calls other than extraction/push respond in <200ms locally; a push of a 30-photo batch completes in <30s excluding network.
- [ ] No obvious N+1 queries or unbounded loops introduced
- [ ] Memory footprint stable under repeated operations
- [ ] If benchmarks exist, `scripts/benchmark.sh` results recorded in `session-handoff.md`
- [ ] Background extraction does not block the API: `GET /batches` stays <200ms while extraction runs. The extraction timeout is honored (180s default)

## 7. Repository

- [ ] No secrets committed (scan for keys, tokens, `.env` files)
- [ ] `.gitignore` covers all generated files
- [ ] No commented-out blocks of code left in
- [ ] No `TODO:` / `FIXME:` left without a tracking issue reference
- [ ] `feature_list.json` is up to date — every feature mentioned in CLAUDE.md appears with a `status`
- [ ] `session-handoff.md` is current

## 8. Scripts

- [ ] All `scripts/*.sh` are executable (`chmod +x`)
- [ ] `scripts/lint.sh` runs and reports cleanly (warnings allowed, errors must be addressed)
- [ ] `scripts/test.sh` exits 0
- [ ] `scripts/integration.sh` exits 0
- [ ] `scripts/architecture-review.sh` exits 0
- [ ] `scripts/code-review.sh` produced a report at `.claude-review.md` and was reviewed
- [ ] `scripts/ui-test.sh` passes once Task 16 exists (needs `tesseract` on PATH)

---

## How to use this checklist

Walk through every item. If a `{{TODO}}` placeholder remains, fill it in with a concrete check for this project's stack. The point of this file is to **encode tribal knowledge** about what "done" means here.
