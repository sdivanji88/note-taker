#!/usr/bin/env bash
# Integration tests — HARD gate. Non-zero exit fails the feature's Definition of Done.

set -euo pipefail

cd "$(dirname "$0")/.."

echo "Running integration tests for note-taker..."

# Real-git integration tests (no Ollama needed). Live extractor tests are manual: (cd backend && uv run pytest -m live)
if [ -f backend/tests/test_api.py ]; then (cd backend && uv run pytest -q tests/test_git_publisher.py tests/test_push_service.py tests/test_push_recovery.py tests/test_api.py tests/test_api_*.py); else echo "integration tests not created yet (plan Tasks 5, 6, 11)"; fi
# The Electron e2e (frontend/e2e/smoke.spec.ts) is run by scripts/ui-test.sh, which builds the app first;
# running it here too would double the time and fail on a missing or stale build.

echo "✓ Integration tests passed"
