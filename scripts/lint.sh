#!/usr/bin/env bash
# Lint — SOFT gate. Reports problems but does not block: always exits 0.
# Every linter runs (one failing does not skip the rest), all of their output goes to
# the report, and "clean" is printed only when every one of them exited 0.

set -uo pipefail

cd "$(dirname "$0")/.."

REPORT_FILE=".lint-report.txt"
FAILED=()

echo "Running lint for note-taker..." | tee "$REPORT_FILE"

# run <name> <dir> <command...>: runs the command in <dir>, tees its output into the
# report, and records <name> if it exited non-zero.
run() {
  local name="$1" dir="$2"
  shift 2
  echo "--- $name ---" | tee -a "$REPORT_FILE"
  (cd "$dir" && "$@") 2>&1 | tee -a "$REPORT_FILE"
  local status=${PIPESTATUS[0]}
  if [ "$status" -ne 0 ]; then
    FAILED+=("$name (exit $status)")
  fi
}

if [ -d backend ]; then
  run "ruff" backend uv run --with ruff ruff check .
fi
if [ -f frontend/package.json ]; then
  run "frontend lint" frontend npm run --if-present lint
  run "frontend typecheck" frontend npm run --if-present typecheck
fi

if [ "${#FAILED[@]}" -eq 0 ]; then
  echo "✓ Lint clean" | tee -a "$REPORT_FILE"
else
  echo "⚠ Lint reported issues in: ${FAILED[*]} (soft gate — not blocking). See $REPORT_FILE." | tee -a "$REPORT_FILE"
fi

# Soft gate: always exit 0
exit 0
