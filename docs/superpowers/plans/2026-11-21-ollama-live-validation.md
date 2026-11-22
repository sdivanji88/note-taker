# Ollama Live Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove Ollama vision extraction on real fixtures, pick a default model via the existing `-m live` harness, and tune quality in a second pass — without installing Tesseract.

**Architecture:** Keep Approach A from the design: no new bakeoff script. Add a thin `NOTE_TAKER_OLLAMA_MODEL` env override on `OllamaSettings` so live tests can swap candidates; run the three candidate pulls against `test_ollama_extractor.py` live tests; commit the winner as the product default; optionally fix `_FORMAT` nullable unions if Ollama rejects them; then Pass 2 prompt/schema polish from the fixture report.

**Tech Stack:** Python 3.12, uv, pytest (`-m live`), Pydantic v2, httpx, local Ollama (`http://localhost:11434`), existing `OllamaVisionExtractor`.

**Spec:** `docs/superpowers/specs/2026-11-21-ollama-live-validation-design.md`

## Global Constraints

- Work on a feature branch off `main` (e.g. `feat/ollama-live-validation`); do not implement on `main`.
- Ollama preferred; **no Tesseract install** in this plan; photo-path e2e stays skipped.
- Candidate set (max three successful pulls): `qwen2.5vl:3b`, `qwen2.5vl:7b`, `granite3.2-vision`. Optional substitute `qwen3-vl:4b` only if `ollama --version` ≥ 0.12.7 and a listed pull fails.
- Hard gate: `test_live_extract_sample_p163` (highlight contains “mathematical possibility”, `page == 163`).
- Soft gate: `test_live_all_local_fixtures_report` over local `PXL_*.jpg` (print-only; no accuracy asserts).
- Schema `_FORMAT` change only if live runs fail with schema rejection / unusable JSON tied to nullable unions.
- Winner rules: (1) pass p163, (2) best fixture report, (3) smaller/faster ties.
- Env var name exactly: `NOTE_TAKER_OLLAMA_MODEL`.
- Do not commit GPS-bearing `PXL_*.jpg` fixtures; only `sample-p163.jpg` is committed.
- Never `git reset --hard`. Photos never committed to the notes repo.

## File Structure

| File | Responsibility |
|------|----------------|
| `backend/src/note_taker/models.py` | `OllamaSettings.model` default + env override |
| `backend/tests/test_models.py` | Unit tests for env override / unset default |
| `backend/src/note_taker/extractors/ollama.py` | `_FORMAT` (conditional), `PROMPT` (Pass 2) |
| `backend/tests/test_ollama_extractor.py` | Existing live + unit tests; schema shape assert if `_FORMAT` changes |
| `README.md` | Default model name; remove “untested placeholder” once validated |
| `feature_list.json` | `ollama-extractor` evidence / status |
| `docs/deferred-findings.md` | Mark Ollama live-verify items done; residual weak cases |
| `session-handoff.md`, `claude-progress.md` | Session close-out |

No new modules. No bakeoff script.

---

### Task 1: `NOTE_TAKER_OLLAMA_MODEL` env override

**Files:**
- Modify: `backend/src/note_taker/models.py` (`OllamaSettings`)
- Modify: `backend/tests/test_models.py`
- Test: `backend/tests/test_models.py`

**Interfaces:**
- Consumes: `os.environ.get("NOTE_TAKER_OLLAMA_MODEL")`
- Produces: `OllamaSettings().model` reads the env when set; otherwise the committed default string (still `qwen2.5vl:7b` until Task 4). Explicit `OllamaSettings(model="x")` always wins. Settings loaded from JSON with a `model` field are unchanged (Pydantic uses the JSON value).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_models.py`:

```python
import os

from note_taker.models import OllamaSettings


def test_ollama_model_default_when_env_unset(monkeypatch):
    monkeypatch.delenv("NOTE_TAKER_OLLAMA_MODEL", raising=False)
    assert OllamaSettings().model == "qwen2.5vl:7b"


def test_ollama_model_reads_env_override(monkeypatch):
    monkeypatch.setenv("NOTE_TAKER_OLLAMA_MODEL", "granite3.2-vision")
    assert OllamaSettings().model == "granite3.2-vision"


def test_ollama_model_explicit_kwarg_beats_env(monkeypatch):
    monkeypatch.setenv("NOTE_TAKER_OLLAMA_MODEL", "granite3.2-vision")
    assert OllamaSettings(model="qwen2.5vl:3b").model == "qwen2.5vl:3b"


def test_ollama_model_empty_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("NOTE_TAKER_OLLAMA_MODEL", "")
    assert OllamaSettings().model == "qwen2.5vl:7b"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `(cd backend && uv run pytest -q tests/test_models.py::test_ollama_model_reads_env_override tests/test_models.py::test_ollama_model_explicit_kwarg_beats_env tests/test_models.py::test_ollama_model_empty_env_falls_back_to_default -v)`

Expected: FAIL — env is ignored (or `AttributeError` / assert failure); `OllamaSettings().model` stays `"qwen2.5vl:7b"` even when env is set.

- [ ] **Step 3: Implement the override**

In `backend/src/note_taker/models.py`, add `import os` at the top (with the other imports), then replace `OllamaSettings` with:

```python
def _default_ollama_model() -> str:
    # Bakeoff / live tests: NOTE_TAKER_OLLAMA_MODEL=<tag> pytest -m live ...
    # Empty or unset → product default. Explicit OllamaSettings(model=...) always wins.
    return os.environ.get("NOTE_TAKER_OLLAMA_MODEL") or "qwen2.5vl:7b"


class OllamaSettings(BaseModel):
    base_url: str = "http://localhost:11434"
    model: str = Field(default_factory=_default_ollama_model)
```

Keep `ExtractorSettings.ollama: OllamaSettings = Field(default_factory=OllamaSettings)` as-is.

- [ ] **Step 4: Run tests to verify they pass**

Run: `(cd backend && uv run pytest -q tests/test_models.py -v)`

Expected: PASS (all model tests including the new ones).

Also run: `(cd backend && uv run pytest -q tests/test_ollama_extractor.py -m "not live")`

Expected: PASS (mocked unit tests unchanged).

- [ ] **Step 5: Commit**

```bash
git add backend/src/note_taker/models.py backend/tests/test_models.py
git commit -m "$(cat <<'EOF'
feat(settings): allow NOTE_TAKER_OLLAMA_MODEL override for live bakeoff

EOF
)"
```

---

### Task 2: Pull candidates and run the live bakeoff

**Files:**
- No product code required (uses Task 1 override).
- Create (local only, do not commit): bakeoff notes — paste the filled table into the Task 4 commit message body and/or `docs/deferred-findings.md` in Task 4.

**Interfaces:**
- Consumes: `OllamaSettings()` via `_live_extractor()` in `backend/tests/test_ollama_extractor.py` (already constructs `OllamaSettings()` then `OllamaVisionExtractor(s.base_url, s.model)`).
- Produces: A filled results table deciding the winner for Task 4.

- [ ] **Step 1: Confirm Ollama and fixtures**

```bash
curl -sS http://localhost:11434/api/tags | head -c 200; echo
ollama --version
ls backend/tests/fixtures/sample-p163.jpg backend/tests/fixtures/PXL_*.jpg 2>/dev/null | head
```

Expected: Ollama responds JSON; `sample-p163.jpg` exists; one or more `PXL_*.jpg` exist (spec assumes they do). If Ollama is down, start it and re-check — do not change product code.

- [ ] **Step 2: Pull the three candidates**

```bash
ollama pull qwen2.5vl:3b
ollama pull qwen2.5vl:7b
ollama pull granite3.2-vision
```

If a pull fails, drop that candidate. Only if a listed pull fails **and** `ollama --version` reports ≥ 0.12.7, pull `qwen3-vl:4b` as a substitute so you still have up to three models. Do not exceed three successful pulls.

- [ ] **Step 3: Run live tests for each candidate**

For each successful pull `<model>`:

```bash
cd backend
NOTE_TAKER_OLLAMA_MODEL=<model> uv run pytest -m live tests/test_ollama_extractor.py -s --tb=short
```

Capture stdout for the fixture report lines (`PXL_...: page=...`).

Fill this table (keep it for Task 4):

| Model | p163 pass? | Fixture report notes (highlights / page / junk) | Schema/parse errors? | Rough latency |
|-------|------------|--------------------------------------------------|----------------------|---------------|
| `qwen2.5vl:3b` | | | | |
| `qwen2.5vl:7b` | | | | |
| `granite3.2-vision` | | | | |
| substitute (if any) | | | | |

- [ ] **Step 4: Apply winner rules**

1. Eliminate any model that failed `test_live_extract_sample_p163`.
2. Among passers, pick the best fixture report (real yellow passages, plausible pages, less garbage).
3. Tie-break: smaller/faster wins.

If **every** candidate fails p163 with errors that look like schema rejection or “did not return usable JSON”, stop and do **Task 3**, then re-run Step 3 for the failed candidates. If they still all fail after Task 3, stop and report to the user — do not invent a fourth family.

If at least one passer exists and failures were quality (wrong page/text) not schema, skip Task 3 entirely (mark Task 3 checkboxes cancelled / N/A in the plan progress notes).

- [ ] **Step 5: Commit**

No code commit required for a pure bakeoff. If you created a scratch notes file under the repo, do **not** `git add` it. Proceed to Task 3 or Task 4.

---

### Task 3: Fix `_FORMAT` nullable unions (conditional)

**Skip this entire task** if Task 2 found at least one p163 passer and no candidate failed due to schema rejection / unusable JSON clearly tied to `_FORMAT`. In that case, write in the session notes: `Task 3 skipped — not needed` and go to Task 4.

**Files:**
- Modify: `backend/src/note_taker/extractors/ollama.py` (`_FORMAT`)
- Modify: `backend/tests/test_ollama_extractor.py`
- Test: `backend/tests/test_ollama_extractor.py`

**Interfaces:**
- Consumes: Ollama `/api/chat` `format` JSON Schema
- Produces: `_FORMAT` with nullable fields as `anyOf: [{type: string|integer}, {type: null}]` instead of `{"type": ["string","null"]}`

- [ ] **Step 1: Write the failing schema-shape test**

Add to `backend/tests/test_ollama_extractor.py`:

```python
@respx.mock
def test_schema_uses_anyof_for_nullables(extractor, image):
    route = respx.post(f"{BASE}/api/chat").mock(return_value=chat_response({"highlights": []}))
    extractor.extract(image)
    schema = json.loads(route.calls.last.request.content)["format"]
    for key in ("note", "chapter"):
        assert schema["properties"][key] == {
            "anyOf": [{"type": "string"}, {"type": "null"}],
        }
    assert schema["properties"]["page"] == {
        "anyOf": [{"type": "integer"}, {"type": "null"}],
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `(cd backend && uv run pytest -q tests/test_ollama_extractor.py::test_schema_uses_anyof_for_nullables -v)`

Expected: FAIL — current schema still uses `{"type": ["string", "null"]}` (or equivalent list form).

- [ ] **Step 3: Update `_FORMAT`**

In `backend/src/note_taker/extractors/ollama.py`, replace `_FORMAT` with:

```python
_FORMAT = {
    "type": "object",
    "properties": {
        "highlights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
        "note": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "page": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "chapter": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": ["highlights"],
}
```

Do not reintroduce `bbox`. Leave `PROMPT` unchanged in this task.

- [ ] **Step 4: Run unit + re-run live bakeoff for previous failures**

```bash
cd backend
uv run pytest -q tests/test_ollama_extractor.py -m "not live"
NOTE_TAKER_OLLAMA_MODEL=<failed-model> uv run pytest -m live tests/test_ollama_extractor.py -s --tb=short
```

Repeat live for each model that previously failed on schema. Update the Task 2 results table. Re-apply winner rules.

Expected: unit tests PASS; at least one candidate now passes p163 (if not, stop and report).

- [ ] **Step 5: Commit**

```bash
git add backend/src/note_taker/extractors/ollama.py backend/tests/test_ollama_extractor.py
git commit -m "$(cat <<'EOF'
fix(ollama): use anyOf nullables in structured-output schema

EOF
)"
```

---

### Task 4: Commit the winning default and close Pass 1 docs

**Files:**
- Modify: `backend/src/note_taker/models.py` (`_default_ollama_model` fallback string)
- Modify: `backend/tests/test_models.py` (assert the new default in unset/empty-env tests)
- Modify: `README.md` (setup pull line + remove placeholder wording)
- Modify: `feature_list.json` (`ollama-extractor` evidence; keep `partial` until Pass 2 unless quality already clearly daily-ready — default: stay `partial`, note live p163 green)
- Modify: `docs/deferred-findings.md` (mark live Ollama / default-model items addressed for Pass 1; leave Tesseract/HSV)
- Modify: `session-handoff.md`, `claude-progress.md`

**Interfaces:**
- Consumes: Winner model tag from Task 2/3
- Produces: Product default string = winner; README documents that tag as the tested default

- [ ] **Step 1: Update the default string and its unit tests**

In `models.py`, change only the fallback in `_default_ollama_model`:

```python
def _default_ollama_model() -> str:
    return os.environ.get("NOTE_TAKER_OLLAMA_MODEL") or "<WINNER>"
```

Replace `<WINNER>` with the actual tag (e.g. `qwen2.5vl:3b`).

In `test_models.py`, update the two assertions that expect `"qwen2.5vl:7b"` when env is unset/empty to expect `"<WINNER>"` instead.

- [ ] **Step 2: Run unit tests**

```bash
cd backend
uv run pytest -q tests/test_models.py tests/test_ollama_extractor.py -m "not live"
```

Expected: PASS.

- [ ] **Step 3: Confirm live green on the committed default (env unset)**

```bash
cd backend
# ensure NOTE_TAKER_OLLAMA_MODEL is unset
unset NOTE_TAKER_OLLAMA_MODEL
uv run pytest -m live tests/test_ollama_extractor.py::test_live_extract_sample_p163 -s --tb=short
uv run pytest -m live tests/test_ollama_extractor.py::test_live_all_local_fixtures_report -s --tb=short
```

Expected: p163 PASS; fixture report prints without `ExtractionError`.

- [ ] **Step 4: Update README and trackers**

`README.md` setup section — replace the placeholder block with (using the real winner tag):

```markdown
```bash
(cd backend && uv sync)
(cd frontend && npm ci)
ollama pull <WINNER>
(cd frontend && npm run dev)     # starts the app, which spawns the Python backend
```

`<WINNER>` is the default Ollama vision model, chosen by live tests against
`sample-p163.jpg` and local fixture photos. Change the model name in Settings if you
prefer another vision model. Override for one-off runs with
`NOTE_TAKER_OLLAMA_MODEL=<tag>`.
```

In `feature_list.json` for `ollama-extractor`, update `evidence` to record: live p163 passed on `<WINNER>`, fixture report run, schema changed or not. Leave `status` as `"partial"` until Pass 2 unless you and the user already agree quality is daily-ready.

In `docs/deferred-findings.md`, under Ollama / “Never run against real tools”, note that Ollama live validation Pass 1 completed with default `<WINNER>`; leave Tesseract/photo-path e2e as open.

Update `session-handoff.md` and append a `claude-progress.md` entry for this session (Pass 1).

- [ ] **Step 5: Commit**

```bash
git add backend/src/note_taker/models.py backend/tests/test_models.py README.md feature_list.json docs/deferred-findings.md session-handoff.md claude-progress.md
git commit -m "$(cat <<'EOF'
feat(ollama): set default vision model from live bakeoff

Winner: <WINNER>. p163 live gate green; Tesseract still deferred.
EOF
)"
```

---

### Task 5: Pass 2 — quality tuning from the fixture report

**Files:**
- Modify (only if justified by Task 2/4 report): `backend/src/note_taker/extractors/ollama.py` (`PROMPT` and/or `_FORMAT`)
- Modify: `backend/tests/test_ollama_extractor.py` (only if schema/`PROMPT`-related asserts need updating — prompt string is not currently asserted; prefer not adding brittle prompt snapshot tests)
- Modify: `docs/deferred-findings.md` (residual weak cases)
- Modify: `feature_list.json` (`status: "pass"` when daily-ready)
- Modify: `session-handoff.md`, `claude-progress.md`

**Interfaces:**
- Consumes: Pass 1 fixture report + winner default
- Produces: Optional prompt/schema tweaks; documented residuals; possibly `ollama-extractor` → `pass`

- [ ] **Step 1: Classify fixture failures**

From the Pass 1 report, list each `PXL_*.jpg` issue into one bucket:

| Bucket | Typical fix |
|--------|-------------|
| Includes unhighlighted body text | Tighten `PROMPT`: emphasize “ONLY highlighter-marked text” / “ignore body text without highlight” |
| Misses real highlights | Soften or clarify highlighter cue; do not add bbox |
| Wrong/missing page | Ask to read the printed page number near the margin; keep `page` nullable |
| Margin note dropped | Already asked for `note`; add “include handwritten margin notes even if short” |
| Sideways / wrong orientation | Document as known limitation without Tesseract OSD (`detect_rotation` → 0); do not install Tesseract in this task |
| Schema/parse errors | If still present, revisit Task 3 style fix — do not invent new fields |

If the report is already good enough for daily use (your judgment + user confirmation), skip Step 2–3 code changes and jump to Step 4 docs with `status: "pass"`.

- [ ] **Step 2: Apply the smallest prompt change (if needed)**

Edit only `PROMPT` in `ollama.py`. Example pattern when unhighlighted text leaks (adapt to the actual bucket — do not paste this blindly if the failure mode differs):

```python
PROMPT = (
    "This is a photo of a printed book page. Return ONLY text that is marked with a highlighter "
    "(usually yellow), as separate passages in reading order, transcribed exactly. "
    "Do not return unhighlighted body text. If there is handwritten text in the margins, "
    "return it as `note`. Return the printed page number as `page` and the chapter title as "
    "`chapter` if a running header shows it; otherwise null."
)
```

One focused edit per commit cycle. Do not change HSV/Tesseract code.

- [ ] **Step 3: Re-run live tests on the default model**

```bash
cd backend
unset NOTE_TAKER_OLLAMA_MODEL
uv run pytest -m live tests/test_ollama_extractor.py -s --tb=short
uv run pytest -q tests/test_ollama_extractor.py -m "not live"
```

Expected: p163 still PASS; fixture report improved or documented as residual. Unit tests PASS.

If p163 regresses, revert the prompt change and document the conflict.

- [ ] **Step 4: Update docs and feature status**

Write residual weak cases into `docs/deferred-findings.md` (e.g. sideways photos without OSD).

If quality is good enough for daily reading sessions, set `feature_list.json` → `ollama-extractor.status` to `"pass"` with evidence citing the live runs and any prompt tweak.

Update `session-handoff.md` and append `claude-progress.md`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/note_taker/extractors/ollama.py docs/deferred-findings.md feature_list.json session-handoff.md claude-progress.md
# include test file only if modified
git commit -m "$(cat <<'EOF'
tune(ollama): improve live extraction quality after fixture review

EOF
)"
```

If there were no code changes (docs-only Pass 2 close):

```bash
git add docs/deferred-findings.md feature_list.json session-handoff.md claude-progress.md
git commit -m "$(cat <<'EOF'
docs: close Ollama live validation Pass 2

EOF
)"
```

---

## Self-review (plan author)

1. **Spec coverage:** Goal/two passes → Tasks 1–5. Env override → Task 1. Candidates + bakeoff → Task 2. Schema conditional → Task 3. Default/README/trackers → Task 4. Pass 2 quality → Task 5. Out of scope (Tesseract, e2e, recover()) excluded.
2. **Placeholders:** `<WINNER>` appears only where the bakeoff result is unknown until Task 2; implementer substitutes the real tag. No TBD/TODO.
3. **Type consistency:** Env name `NOTE_TAKER_OLLAMA_MODEL`, `_default_ollama_model()`, `_FORMAT` anyOf shape, live test module path — consistent across tasks.
