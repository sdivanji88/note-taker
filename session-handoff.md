# Session Handoff — note-taker

> Read this at the start of every session. Update it before ending every session.

**Last updated:** 2026-11-08 (Session 1: design + plan + harness; no product code yet)

---

## What was accomplished

- Ran a design interview (superpowers:brainstorming) and committed the spec: `docs/superpowers/specs/2026-11-08-note-taker-design.md` (`df5b7b7`).
- Wrote and committed the 16-task implementation plan: `docs/superpowers/plans/2026-11-08-note-taker.md` (`12d70f5`).
- Generated this agent harness: CLAUDE.md, `.claude/agents/*`, `scripts/*`, `docs/*`, trackers.

## What remains

All 16 plan tasks, tracked in `feature_list.json` (all `status: "todo"`). Do them in order:
- **Phase 1, backend (Tasks 1–11):** `backend-scaffold-models` → `batch-store` → `markdown-writer` → `book-catalog` → `git-publisher` → `push-service` → `extraction-queue` → `ollama-extractor` → `tesseract-extractor` → `janitor` → `rest-api`.
- **Phase 2, desktop app (Tasks 12–16):** `electron-shell` → `batch-screens` → `review-editor` → `settings-screen` → `e2e-readme`.

## Blockers / decisions made

- **Decision:** execution method is **superpowers:subagent-driven-development**. A fresh implementer subagent works on each plan task, a fresh reviewer gates it before the next task starts, and the whole branch gets a final review. **Why:** the user chose it, the tasks depend on each other's interfaces, and the git-safety tasks (5–6) protect the user's real notes repo. **Trade-off:** more tokens per task.
- **Decision:** every product decision is in the spec's decision log (§13, D1–D21). §12 "Builder-check resolutions" overrides earlier spec sections. In the spec, **[user]** marks decisions the user made and **[call]** marks designer's calls. Don't relitigate the [user] ones.
- **Open (non-blocking):** the default Ollama vision model is a placeholder (`qwen2.5vl:7b`). Pick it in Task 8 by running the live tests on real photos.
- **Needs from user (non-blocking):** real highlighted-page photos in `backend/tests/fixtures/`, including the *Permutation City* p.163 example. Live tests fall back to synthetic images until then.

## Files modified

**Design & plan**
- `docs/superpowers/specs/2026-11-08-note-taker-design.md` — design spec
- `docs/superpowers/plans/2026-11-08-note-taker.md` — implementation plan
- `.gitignore` — added `.superpowers/`

**Harness**
- `CLAUDE.md`, `session-handoff.md`, `claude-progress.md`, `feature_list.json`, `clean-state-checklist.md`, `evaluator-rubric.md`, `quality-document.md`
- `.claude/agents/{orchestrator,architect,developer,tester,code-reviewer,designer}.md`
- `scripts/{lint,test,integration,ui-test,code-review,architecture-review}.sh` — skip parts of the project that don't exist yet, until the plan creates them
- `docs/{PRODUCT,ARCHITECTURE,RELIABILITY,architecture-rules}.md`

## Benchmark results (if applicable)

None yet. There's no code.

## Next session — start here

1. Read `CLAUDE.md`, then the spec (especially §12–13), then the plan's header, Global Constraints, Review Focus and File Structure.
2. Create a feature branch (e.g. `feat/backend-phase1`). Use superpowers:using-git-worktrees if you want isolation. Don't build on `main`.
3. Invoke **`superpowers:subagent-driven-development`** with the plan `docs/superpowers/plans/2026-11-08-note-taker.md` and start at **Task 1**. Give each implementer subagent the plan path, the spec path, its task number, and the plan's Global Constraints.
4. After each task: run `scripts/test.sh`, set that feature's `status: "pass"` in `feature_list.json` with evidence (the test command and its result, plus the commit SHA), and append to `claude-progress.md`.
5. Before ending the session, update this file.

Prerequisites to check on the machine before Task 1:
- `uv --version`
- `git --version`
- Before Task 8: `ollama list`
- Before Task 9: `which tesseract`
- Before Task 12: `node -v` (needs 20+)
