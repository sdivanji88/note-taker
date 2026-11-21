# claude-progress.md -- Session Log

> Append a new session entry at the end of every session. Never overwrite previous entries — this is an append-only log.

## note-taker

### Session 1 -- 2026-11-08

**Duration**: ~1.5h
**Goal**: Turn the note-taker idea into an approved design, an implementation plan, and handoff artifacts. No product code.

**What was done**:
- Ran a design interview with the user. Clicked mockups chose the review screen ("one page at a time") and the multi-photo upload ("grid first, then step through").
- Committed the spec `docs/superpowers/specs/2026-11-08-note-taker-design.md` after a builder-check review. Eight questions from that review were settled as designer's calls (§12).
- Committed the 16-task TDD plan `docs/superpowers/plans/2026-11-08-note-taker.md`.
- Generated the agent harness (CLAUDE.md, subagents, scripts, docs, trackers). `feature_list.json` maps one feature to each plan task.

**Decisions**:
- One markdown file per book with a section per highlight — over one file per highlight — because the user recalls by rereading a book's takeaways (user).
- Stack: Python backend, React + Electron frontend, Ollama for vision — the user's choice.
- A JSON file + photos folder per batch — over SQLite — because the user's anti-goal is local storage that keeps growing (call).
- Several open batches are allowed. A done batch is deleted locally. Uncommitted batches expire after 30d (configurable) with a warning first (user).
- Push refuses on a dirty clone and never hard-resets. Hidden per-highlight markers make push idempotent — over trusting git state alone — because crash or retry must not duplicate notes or destroy user edits (call).
- Execution method: superpowers:subagent-driven-development (user).

**Issues**:
- None. The default Ollama model is still to be chosen in Task 8 using real photos.

**Benchmark Results** (if applicable):
- N/A.

**Next session**: Branch off `main`, then run superpowers:subagent-driven-development on the plan starting at Task 1 (see session-handoff.md).

### Session 2 -- 2026-11-09

**Duration**: ~1 day wall clock (mostly subagent time)
**Goal**: Execute the 16-task plan with subagent-driven development and test-driven development, then a final whole-branch review.

**What was done**:
- Built all 16 tasks on branch `feat/note-taker-v1`; every task went through an implementer subagent (TDD with RED/GREEN evidence), a spec+quality review, and 0-2 fix rounds with scoped re-reviews. Final whole-branch review (most capable model) found 1 Critical + 7 Important; one fix wave (12 commits) addressed all; a scoped re-review found 1 residual Important (see below).
- Backend 423 tests, frontend 145, Kindle-path e2e passing; architecture-review and lint gates pass.
- Real findings caught by reviews (not by the original tests): `delete("..")` could rmtree the data dir; CRLF book files were rewritten; rollback could leave the clone dirty or delete outside the repo; a stale expiry warning could delete a batch without a fresh warning; edits were silently overwritten by extraction; the backend could be orphaned on kill; invalid page blocked all autosave; pushing from a clone on branch `wip` would have published `wip` to `main`; the app could fail to start with a configured remote; `lint.sh` reported clean while ruff found 17 errors.

**Decisions**:
- Capture edits are refused while pending/extracting/pushing — over silently overwriting — because extraction results would erase the user's typing.
- A warning counts only in the current expiry window — over "warned_at set" — because an edit resets the window and the batch must never vanish without a fresh warning.
- No bbox overlay — over persisting boxes — because the backend does not store them and the overlay was a spec nice-to-have.
- Push refuses on wrong branch/remote — over trusting the clone — because the push published HEAD to the configured branch.
- Token passed to the backend via environment and removed from the backend's own environment after reading.

**Issues**:
- **Residual (not fixed):** `PushService.recover()` fetch uses a 60 s timeout inside the startup lifespan (Electron waits 20 s) — one-line fix in `docs/deferred-findings.md`.
- Tesseract and Ollama were not installed: the extractors, rotation detection and the photo-path e2e test have never run on real photos.
- Earlier real-window checks left Chromium cache files in `~/Library/Application Support/note-taker-frontend/` (no user data).

**Benchmark Results** (if applicable):
- None.

**Next session**: apply the one-line recover() fix with a test, then install Tesseract/Ollama and run the live checks on the real photos (see session-handoff.md).

