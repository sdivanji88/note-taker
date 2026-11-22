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


### Session 3 -- 2026-11-21 (Ollama live validation, Pass 1)

**Duration**: ~3h
**Goal**: Validate the Ollama extractor against a real Ollama and commit a tested default model.

**What was done**:
- Ran the live tests on three candidate vision models; qwen2.5vl:7b was the only one to pass p163. Committed it as the default (README now says it is tested).
- Found that the 4096-token default context truncated the JSON answer; set `num_ctx=8192` in the chat options with a unit test. Both live tests pass with the env override unset.

**Decisions**:
- Keep the nullable-union schema (Task 3 skipped) because the real server accepted it and the failures were context truncation, not schema rejection.
- `ollama-extractor` stays `partial` until Pass 2 quality review, because page/note accuracy varies (page=None on 3 of 9 fixtures).

**Issues**:
- ~40-55 s per photo (limit 180 s). `done_reason=length` is not yet an explicit error. Tesseract still unverified.

**Benchmark Results**: live suite 429.93 s for p163 + 9 fixtures.

**Next session**: On `feat/ollama-live-validation`, Ollama Pass 2 — treat `done_reason=length` as an explicit extraction error and improve page/note accuracy (see session-handoff.md).


### Session 3b -- 2026-11-21 (Ollama live validation, Pass 2)

**Duration**: ~25 min
**Goal**: Classify fixture weaknesses and tune only if justified.

**What was done**:
- Classified the 9 fixtures: page=None on 3, one note repeating highlight text, no sideways or parse failures. Left PROMPT unchanged.
- `done_reason == "length"` now raises ExtractionError (unit test added). Re-ran live suite: 2 passed in 382.68 s. Set `ollama-extractor` to pass.

**Decisions**:
- No prompt change: each weakness is user-correctable in the review editor, and a prompt edit risks regressing p163 at ~6 min per live run.

**Issues**:
- Residuals recorded in docs/deferred-findings.md. Tesseract still unverified.

**Benchmark Results**: live suite 382.68 s (p163 + 9 fixtures).

**Next session**: Tesseract/HSV/photo-path e2e, then the `recover()` timeout fix.


### Session 4 -- 2026-11-22 (Tesseract + photo-path e2e)

**Duration**: ~20 min
**Goal**: Unblock the photo-path e2e gate with a real Tesseract binary.

**What was done**:
- Confirmed tesseract 5.5.1 already installed via Homebrew (`/opt/homebrew/bin/tesseract`).
- Real-binary Tesseract + OSD/rotation unit tests pass (previously skipped).
- `bash scripts/ui-test.sh`: vitest 145, build, Playwright 2/2 including photo path (5.6s) with synthetic yellow-highlight PNGs.
- Updated `feature_list.json` (`tesseract-extractor` → pass, e2e evidence), deferred findings, session-handoff.

**Decisions**:
- HSV tuning on real GPS fixtures deferred as optional residual; synthetic e2e + unit coverage is enough for the pending gate.

**Issues**:
- Vitest still prints the noisy stderr-ring-buffer fixture (documented earlier).

**Benchmark Results**: ui-test Playwright ~14.6s total (2 tests); photo path 5.6s.

**Next session**: `recover()` timeout fix, or merge/PR `feat/ollama-live-validation`.

### Session 5 -- 2026-11-22 (v1 open gaps)

**Duration**: ~45 min
**Goal**: Close the three remaining real gaps after PR #2 merged to main.

**What was done**:
- TDD: `test_recover_uses_short_fetch_timeout`; `recover()` now calls `git.fetch(timeout_s=_SYNC_TIMEOUT_S)`.
- Hard gates: test.sh, integration.sh, architecture-review.sh, lint.sh green. Soft code-review.sh writes a report (claude CLI unavailable).
- Smoke: token-guarded `/health` + `/ping` on 127.0.0.1:8765.
- Script hygiene: exclude `.worktrees` from architecture scan; fix code-review.sh heredoc.

**Decisions**:
- Treat deferred “Should fix soon” items as post-v1 polish, not blockers.

**Issues**:
- claude CLI too old / fails for LLM audit stages (architecture stage 2 skipped cleanly when no FAIL line; code-review uses placeholder).

**Benchmark Results**: unit ~38s; integration ~23s; smoke ~2s to ping.

**Next session**: Merge `fix/recover-fetch-timeout`; optional deferred polish.

### Session 6 -- 2026-11-22 (deferred-findings polish)

**Goal**: Deferred-findings polish on `polish/deferred-findings`.

**What was done**:
- Ten implementation commits: `bb9cb55`, `a185d27`, `2625988`, `560de31`, `ad9195c`, `dd92c00`, `01c9b12`, `749f5ea`, `7e9f1e5`, `410f11c`.
- The bookkeeping pass updates `feature_list.json` (six polish rows), this log, `evaluator-rubric.md`, `quality-document.md`, `session-handoff.md`, and the accuracy lines in `docs/deferred-findings.md` and `docs/ARCHITECTURE.md`. Working tree only; not committed. That pass did not have the gate numbers below.
- This orchestration pass, after those bookkeeping edits, re-ran the gates. No duration recorded for that pass.

**Decisions**:
- Tolerant `list()` instead of `list_readable()`.
- `same_remote` lives in `git_publisher.py`, with a strict path compare.
- Back-out is delete-on-leave, not lazy create.

**Issues**:
- `scripts/architecture-review.sh` exit 1 is expired Claude CLI OAuth (`Failed to authenticate`, script recorded `AUDIT_ERROR`), not an architecture-rule finding, and it is not a pass. The static stage was clean (no file over 500 lines, no file over 15 imports); the LLM stage did not run.
- `scripts/code-review.sh` exited 0 and wrote only a placeholder (same expired OAuth). Not verified.
- Found-while-polishing items stay open.

**Benchmark Results**:
- This orchestration pass, after the bookkeeping edits (the implementation session did not have these numbers):
  - `scripts/test.sh` exit 0: pytest 548 passed, 2 deselected in 46.60s; vitest 252 passed in 2.41s.
  - `scripts/integration.sh` exit 0: 231 passed in 25.97s.
  - `scripts/ui-test.sh` exit 0: vitest 252, typecheck + electron-vite build succeeded, Playwright 3 passed in 16.3s (Kindle smoke, back-out e2e, photo path).
  - `scripts/lint.sh` exit 0: ruff clean, frontend typecheck passed.
  - `scripts/architecture-review.sh` exit 1: not a pass (auth, see Issues).
  - `scripts/code-review.sh` exit 0: placeholder only (see Issues).

**Next session**: Re-authenticate the `claude` CLI and re-run `scripts/architecture-review.sh` and `scripts/code-review.sh`, then push `polish/deferred-findings` and open the PR.

### Session 6b -- 2026-11-22 (architecture LLM via Cursor agent)

**Goal**: Complete architecture-review Stage 2 without Claude CLI (headless Cursor Agent).

**What was done**:
- Updated `scripts/architecture-review.sh` and `scripts/code-review.sh` to prefer `agent` / `cursor-agent` (`-p --mode ask --output-format text`), fall back to `claude`; architecture uses merge-base `main...HEAD` diff; fail on ambiguous audit output.
- Ran `bash scripts/architecture-review.sh`: exit 0, LLM=`agent`, PASS (~107s, ~275KB branch diff).
- Struck the Claude-OAuth blocker in `docs/deferred-findings.md`; refreshed `session-handoff.md`.

**Decisions**:
- Cursor Agent is the primary headless LLM for local gates when Claude is unavailable.

**Issues**: none for the architecture hard gate.

**Benchmark Results**: architecture-review ~107s wall clock with `agent`.

**Next session**: Merge PR #4; optional soft code-review with `agent`; triage "Found while polishing".

### Session 6c -- 2026-11-22 (PR #4 merged)

**Goal**: Record merge of deferred-findings polish.

**What was done**:
- Confirmed PR #4 MERGED (`0a6fda2`); fast-forwarded local `main`.
- Deleted local and remote `polish/deferred-findings`.

**Next session**: Triage "Found while polishing" or clean leftover branches/worktrees.
