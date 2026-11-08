#!/usr/bin/env bash
# Lint — SOFT gate. Reports problems but does not block.
# Exits 0 unless the lint tool itself crashes.

set -uo pipefail

cd "$(dirname "$0")/.."

REPORT_FILE=".lint-report.txt"

echo "Running lint for note-taker..." | tee "$REPORT_FILE"

# Tech-stack-derived lint command(s)
if [ -d backend ]; then (cd backend && uv run --with ruff ruff check .); fi
if [ -f frontend/package.json ]; then (cd frontend && npm run --if-present lint && npm run --if-present typecheck); fi 2>&1 | tee -a "$REPORT_FILE"
LINT_EXIT=${PIPESTATUS[0]}

if [ "$LINT_EXIT" -eq 0 ]; then
  echo "✓ Lint clean" | tee -a "$REPORT_FILE"
else
  echo "⚠ Lint reported issues (soft gate — not blocking). See $REPORT_FILE." | tee -a "$REPORT_FILE"
fi

# Soft gate: always exit 0
exit 0
