# Ollama live validation — design

**Date:** 2026-11-21  
**Status:** Approved for planning  
**Context:** v1 is on `main`. Ollama and Tesseract extractors were never run against real tools. Ollama with a vision model is the preferred path for real use; Tesseract is deferred.

## 1. Goal

Prove Ollama vision extraction works on this machine, choose a default model from a short candidate list using the existing `-m live` tests, then improve quality in a second pass.

Two passes:

1. **Harness green + default model** — pull candidates, run live tests, pick a winner, commit the default (and a schema fix only if required).
2. **Quality tuning** — adjust prompt/schema from real-page results until daily use is acceptable.

## 2. Scope

### In scope

- Ollama reachability and vision-model pulls.
- Model bakeoff via existing live tests in `backend/tests/test_ollama_extractor.py`.
- Optional env override so candidates can be tested without rewriting the default three times.
- Structured-output schema fix (`_FORMAT` nullable unions → `anyOf`) **only if** live runs fail due to schema rejection.
- Updating the committed default model, README, feature/handoff trackers, and deferred-findings notes.
- Pass 2 prompt/schema polish and documenting remaining weak cases.

### Out of scope

- Installing or validating Tesseract.
- Photo-path Playwright e2e (skipped without Tesseract).
- `PushService.recover()` startup timeout and other deferred “fix first / soon” items.
- UI polish from `docs/deferred-findings.md`.
- Packaging/distribution.

## 3. Approach

**Approach A — existing live harness** (chosen).

Pass 1 uses:

- `test_live_extract_sample_p163` as the **hard gate** (highlight text contains “mathematical possibility”, `page == 163`).
- `test_live_all_local_fixtures_report` as the **comparison printout** over local `PXL_*.jpg` (no accuracy asserts; skipped if none).

No new bakeoff script or Electron smoke in Pass 1. Model pick is judgment from the hard gate plus the fixture report, matching the original plan/spec intent.

## 4. Candidate models

Three small pulls for a Mac:

| # | Model | Role |
|---|--------|------|
| 1 | `qwen2.5vl:3b` (~3.2 GB) | Fast baseline |
| 2 | `qwen2.5vl:7b` (~6 GB) | Current placeholder default — must be tried fairly |
| 3 | `granite3.2-vision` (~2.4 GB) | Document-oriented family |

If a pull fails or Ollama is too old for a tag, drop that candidate. Optionally substitute `qwen3-vl:4b` only when `ollama --version` is ≥ 0.12.7. Do not expand beyond three successful pulls in Pass 1 without a new decision.

Prerequisites assumed: Ollama installed and running; no vision model pulled yet; real `PXL_*.jpg` fixtures already present under `backend/tests/fixtures/` (gitignored); committed `sample-p163.jpg` available.

## 5. Bakeoff procedure

1. Confirm Ollama is reachable at `http://localhost:11434`.
2. `ollama pull` each candidate.
3. For each candidate, run live tests with that model selected (see §6 env override).
4. Record: p163 pass/fail, per-`PXL_*` report quality (eyeball), obvious latency, schema/parse errors.
5. Apply winner rules (§7).
6. Commit the winning default string; update README so it is no longer described as an untested placeholder.
7. Pass 2: re-read the report; change `PROMPT` and/or `_FORMAT` only as needed; document residual weaknesses.

Command shape:

```bash
cd backend
NOTE_TAKER_OLLAMA_MODEL=<candidate> uv run pytest -m live tests/test_ollama_extractor.py -s
```

## 6. Code touch points

| Change | When | Where |
|--------|------|--------|
| Env override `NOTE_TAKER_OLLAMA_MODEL` | Pass 1 | `OllamaSettings` in `backend/src/note_taker/models.py` — if unset, keep the committed default |
| Default model string | End of Pass 1 | Same `OllamaSettings.model` default; README / docs that name the placeholder |
| `_FORMAT` nullable → `anyOf` | Pass 1 only if live schema rejection | `backend/src/note_taker/extractors/ollama.py` |
| Prompt / further schema polish | Pass 2 | `ollama.py` `PROMPT` / `_FORMAT` |
| Trackers | Both passes as appropriate | `feature_list.json`, `session-handoff.md`, `claude-progress.md`, `docs/deferred-findings.md` |

Live tests construct `OllamaSettings()` today; the env override is the bakeoff lever so `models.py` is not rewritten once per candidate.

**Rotation:** `imaging.detect_rotation` without Tesseract returns `0` by design. Pass 1 accepts that. Sideways photos that need OSD are Pass 2 notes or a later Tesseract effort.

## 7. Winner rules

In order:

1. Must pass `test_live_extract_sample_p163`.
2. Among passers: best fixture report (highlights look like real yellow passages, page numbers plausible, fewer empty/garbage results).
3. Tie-break: smaller/faster model wins.

Losers may stay pulled locally or be removed with `ollama rm`; not required by this design.

## 8. Failure handling

| Failure | Action |
|---------|--------|
| Ollama down | Start/fix Ollama; no product code change |
| Model not pulled | `ollama pull`; existing health detail already instructs the user |
| Schema rejection / unusable JSON tied to `_FORMAT` | Fix `_FORMAT` once; re-run affected candidates |
| All three fail p163 after schema fix | Stop and report; do not invent a fourth family without a new decision |
| p163 passes but fixture report is weak | Still eligible; prefer another passer with a better report |

## 9. Testing and done criteria

**Pass 1 done when:**

- Chosen default passes `test_live_extract_sample_p163`.
- Fixture report has been run once with that default (when `PXL_*.jpg` exist).
- Default + README no longer treat the model as an untested placeholder.
- Existing non-live unit tests for the Ollama extractor still pass; no regression in normal `pytest` / project test scripts beyond intentional default-string updates.

**Pass 2 done when:**

- Any prompt/schema tweaks justified by fixture results are committed.
- Remaining weak cases are written down (deferred findings or reliability notes).
- `ollama-extractor` in `feature_list.json` may move from `partial` → `pass` when real-page quality is judged good enough for daily reading sessions.

## 10. Non-goals reminder

Tesseract install, yellow HSV tuning, photo-path e2e, and startup `recover()` timeout remain separate workstreams.
