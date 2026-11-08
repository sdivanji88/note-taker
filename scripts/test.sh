#!/usr/bin/env bash
# Unit tests — HARD gate. Non-zero exit fails the feature's Definition of Done.

set -euo pipefail

cd "$(dirname "$0")/.."

echo "Running unit tests for note-taker..."

if [ -d backend ]; then (cd backend && uv run pytest -q); else echo "backend/ not created yet (plan Task 1)"; fi
if [ -f frontend/package.json ]; then (cd frontend && npx vitest run); else echo "frontend/ not created yet (plan Task 12)"; fi

echo "✓ Unit tests passed"
