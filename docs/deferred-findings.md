# Deferred findings

Findings from the per-task reviews and the final whole-branch review that were **not fixed** in the first build session (2026-11-08/09). Triage is the final reviewer's. Items the final fix wave resolved (git timeouts, atomic batch delete after push, push snapshot race, branch/remote guard, `/ping` readiness probe, settings trimming, token out of env, lint honesty) are not listed.

## Residual from the last review — fix first

| Item | Where | Smallest fix |
|---|---|---|
| **A crash mid-push plus a slow remote can still stop the app from starting.** `PushService.recover()` runs in the FastAPI lifespan before `/ping` answers and calls `git.fetch()` with the default 60 s network timeout; Electron gives up after 20 s and kills the backend, so every later launch fails the same way until the network is reachable. | `backend/src/note_taker/push_service.py` (`recover`, ~:167) | `git.fetch(timeout_s=_SYNC_TIMEOUT_S)` (10 s). A failed fetch already reopens the batch without reconciling, which is safe because pushes are idempotent. Add a test with a hanging fetch. |
| Origin comparison is a strict string match (trailing `/`, `.git`, scp-style vs `ssh://`, credentials in one URL only make a correct setup fail as `remote_mismatch`). Safe (push refused with a message naming both URLs), but annoying. | `push_service.py` `_clone_mismatch` (~:233) | Compare after stripping a trailing `/` and `.git`. |
| A clone on the wrong branch/remote is only reported at push time (`sync()` skips silently with a log line). | `push_service.py` `sync` | Show it in `/health` or a BatchList notice. |

## Should fix soon

- **Settings/listing robustness:** a corrupt `settings.json` stops the backend from starting (`SettingsStore.load` → quarantine and use defaults, as `books._quarantine` does); `BatchStore.list()` raises on one corrupt `batch.json` and is used by `GET /batches`, `find_capture` and `resume_pending` (use `list_readable()`).
- **Markdown writer:** a multi-line note whose later line is exactly `<!-- nt:highlight=<id> -->` can forge a marker (prefix/escape continuation lines); a newline in a chapter or title splits the heading (collapse whitespace in `_heading`/`render_new_file`); a 0-byte existing book file gets no frontmatter (treat as missing).
- **Push bookkeeping:** a failure after a successful `git push` (e.g. `finish` raising) leaves the batch in `pushing` until restart — wrap, reopen, log "pushed but bookkeeping failed".
- **Extraction:** `detect_rotation` has no timeout (pass `timeout=30` to `image_to_osd`); the 30 s health tick rewrites batch JSON and republishes the same status per pending capture (only write when the error text changes); a margin note with no highlights is silently dropped; `imaging.captured_at` catches only some exceptions, so corrupt EXIF can fail an upload with a 500 (use `except Exception`).
- **Ollama:** the structured-output schema uses `{"type": ["string","null"]}` unions; settle on `anyOf` once a real Ollama is available. Pick the default model on real photos (`qwen2.5vl:7b` is a placeholder).
- **API:** duplicate highlight ids in a PATCH are not de-duplicated (the second block would be skipped forever by the marker check — mint a fresh id for repeats); tracebacks (`exc_info`) bypass credential redaction.
- **UI:** the "Live updates may be stale" text is always shown because `client.subscribe` has no `onerror` reporting and `JSON.parse` in the listener can throw; no reload after a failed Discard on the list; thumbnail numbering skips hidden pushed captures and an empty batch reads "Review 1 of 0"; `type="number"` bad input becomes `page: null` with no message; "Couldn't save — retrying…" is shown for 409/422 that never retry; ⌘↵ has no IME-composition or read-only guard; a server 422 on Settings focuses no field.
- **Noisy test output:** the stderr-ring-buffer test in `frontend/tests/backend.test.ts` makes the forwarded backend stderr (added in the final wave) print ~8 KB of `x` characters plus `boom…`/`HEAD-MARKER`/`TAIL-MARKER` into the real stderr during `npx vitest run`; silence `process.stderr.write` in that test so the output stays pristine.
- **Anti-goal polish:** no per-batch "expiring" badge (spec §3); "New batch" creates an empty batch on click and "Add Kindle highlight" creates a `ready` capture with empty text before the user types — backing out leaves an unfinishable batch; `/captures/{id}/image` decodes and re-encodes the full 12 MP photo per request with `no-store` (serve a downscaled copy).

## Known limitations (accepted for v1)

- **Never run against real tools:** Tesseract and Ollama were not installed where this was built. OCR quality, highlight-detection thresholds (yellow HSV range, kernel size, no crop padding), two-column highlight merging, rotation detection, the default model and the schema above are untested on real photos. The photo-path e2e test and the Tesseract-OSD rotation test are skipped without Tesseract and have never run. Run `uv run pytest -m live` and the e2e after `brew install tesseract` / installing Ollama, and keep the 7 real photos in `backend/tests/fixtures/` (gitignored, they carry GPS) for tuning.
- The photo `mtime` fallback for `captured_at` is the upload time (only EXIF gives the real photo time).
- A retry's requested extractor kind is forgotten if the extractor was unhealthy and the capture is re-queued; `extractor.concurrency` / `timeout_s` are read once at startup.
- A crash mid-write of a book file can leave a partial unmarked section at the tail; a retry appends a complete copy after it (the user can hand-fix).
- A highlight's *text* edited outside the app after it was written is not rewritten (highlights are recognised by id).
- Many small UI races (stale health fetch in Settings, `holdForPush` closure, Back double-click) are bounded and self-correcting; see the per-task notes in the git history.
