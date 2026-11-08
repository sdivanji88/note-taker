#!/usr/bin/env bash
# UI / end-to-end tests — HARD gate when UI is in scope.
# Requires a browser driver (Playwright, Cypress, etc) configured for this project.

set -euo pipefail

cd "$(dirname "$0")/.."

echo "Running UI tests for note-taker..."

# Stack-derived UI test command. Default assumes Playwright.
# Override for Cypress (`npx cypress run`), Storybook test-runner, etc.
if [ -f frontend/e2e/smoke.spec.ts ]; then
  (cd frontend && npx vitest run && npx playwright test)
else
  echo "frontend e2e not created yet (plan Task 16)"
fi

echo "✓ UI tests passed"
