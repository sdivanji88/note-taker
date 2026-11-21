# Reliability — note-taker

> Performance targets, scale, observability, failure modes, and operational characteristics.

## Performance targets

Single local user. Per-photo extraction ≤180s timeout (concurrency 1, Ollama on a Mac); API calls other than extraction/push respond in <200ms locally; a push of a 30-photo batch completes in <30s excluding network.

Specific targets:

- **Latency (p50 / p95 / p99):** non-extraction API calls <200ms locally
- **Throughput:** extraction is the bottleneck: ~1 photo at a time, ≤180s timeout each
- **Resource budget (CPU / memory):** one local vision model in memory (Ollama); backend itself small
- **Startup time:** backend healthy within 20s of Electron launch (Electron gives up after 20s)

## Scale targets

One user, one machine. Batches of ~5–30 photos; several open batches at once. Local storage holds only in-progress batches (deleted on push or after 30-day expiry with warning) — it must not grow unbounded. Notes repo grows by markdown text only (no photos).

Specific targets:

- **Concurrent users:** 1
- **Requests per second sustained:** n/a (local UI)
- **Data volume (total / growth rate):** local: only open batches (photos + JSON); repo: markdown text only
- **Failure isolation boundary:** per capture (one failed extraction never fails the batch) and per push (failure rolls back only the app's own changes)

## Observability

### Structured logging

Not JSON: the backend uses plain-text Python stdlib `logging` to stderr
(`%(asctime)s %(levelname)s %(name)s: %(message)s`, configured in `note_taker/__main__.py`).
In dev, Electron forwards the backend's stderr to the terminal running `npm run dev` and logs
the backend's exit code/signal. Log lines carry `batch_id`/`capture_id` where relevant; a
redacting filter on the handler masks URL credentials and `?token=`; tokens and credentials
are never logged.

### Timeouts on external calls

Every git subprocess has a timeout and never prompts (stdin is `/dev/null`,
`GIT_TERMINAL_PROMPT=0`): 60s for network commands (fetch, push, clone, ls-remote), 20s for
local ones. Tighter overrides where the UI waits: the `/health` remote check uses 5s and the
`GET /books` sync 10s. A timeout surfaces as a git error (push rolls back as for any git
failure). App startup probes `/ping`, which does no I/O.

### Metrics

None in v1 (single local user).

### Tracing

None; `batch_id`/`capture_id` in log lines are the correlation keys.

### Dashboards & alerts

None (local desktop app). `/health` + the Settings health panel are the operator view.

## Failure modes

For each anticipated failure, document: trigger, detection, blast radius, recovery.

- Ollama down / model not pulled → captures stay `pending`, auto-resume when healthy
- Extraction timeout or bad model output → capture `failed`, user retries or types manually
- Dirty notes repo → push refused (409) with instructions
- Push rejected / network failure → rollback of app's own commit, batch kept, retry later
- Crash mid-push → `recover()` on startup reconciles via remote markers

## Backpressure & degradation

Extraction queues (FIFO, concurrency 1); UI stays responsive; nothing is dropped.

## Disaster recovery

The notes repo on GitHub is the durable record. Local batch data is intentionally ephemeral (deleted on push / expiry).

## Deployment

macOS only, dev-mode run (`npm run dev` in frontend/, which spawns the backend via `uv run`). Backend binds 127.0.0.1 with a per-launch token. Packaging/distribution is out of scope for v1. Prerequisites: Ollama (+ pulled vision model), `brew install tesseract`, uv, Node 20+.

### Rollout strategy

n/a — dev-mode run from the repo.

### Rollback

`git revert` / checkout an earlier commit of this repo.

## Capacity planning

n/a for single-user; watch extraction time per photo and data-dir size.
