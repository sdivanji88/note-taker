#!/usr/bin/env bash
# Code review — SOFT gate. Writes a markdown report to .claude-review.md.
# Always exits 0; humans/agents are expected to read the report.

set -uo pipefail

cd "$(dirname "$0")/.."

REPORT_FILE=".claude-review.md"

# Determine diff range: staged changes if any, else last commit, else everything.
if ! git rev-parse --git-dir > /dev/null 2>&1; then
  echo "Not a git repo — skipping code review."
  exit 0
fi

if ! git diff --cached --quiet 2>/dev/null; then
  DIFF_CMD="git diff --cached"
  DIFF_DESC="staged changes"
elif git rev-parse HEAD > /dev/null 2>&1; then
  DIFF_CMD="git diff HEAD~1..HEAD"
  DIFF_DESC="last commit"
else
  echo "No commits yet — skipping code review."
  exit 0
fi

echo "Running code review on $DIFF_DESC..."

DIFF_CONTENT=$($DIFF_CMD 2>/dev/null || echo "")

if [ -z "$DIFF_CONTENT" ]; then
  echo "Empty diff — skipping."
  exit 0
fi

# Prefer Cursor Agent headless; fall back to Claude Code CLI.
LLM_CMD=""
if command -v agent > /dev/null 2>&1; then
  LLM_CMD="agent"
elif command -v cursor-agent > /dev/null 2>&1; then
  LLM_CMD="cursor-agent"
elif command -v claude > /dev/null 2>&1; then
  LLM_CMD="claude"
fi

if [ -n "$LLM_CMD" ]; then
  PROMPT=$(cat <<'EOF'
You are reviewing a code diff for correctness, clarity, and adherence to the architecture rules in docs/architecture-rules.md.

You are read-only. Do not edit files or run mutating commands.

Output a markdown report with these sections:

## Summary
One-paragraph overall assessment.

## Findings
For each finding: severity (high/medium/low), file:line, what is wrong, suggested fix.

## Architecture rule violations
Specifically flag violations of: deep modules, information hiding, defining errors out of existence, pulling complexity downward, naming/commenting.

Only flag things you are confident about. Empty sections are fine.

The diff:
EOF
)
  echo "$PROMPT" > /tmp/code-review-prompt.txt
  echo "$DIFF_CONTENT" >> /tmp/code-review-prompt.txt

  if [ "$LLM_CMD" = "claude" ]; then
    "$LLM_CMD" -p "$(cat /tmp/code-review-prompt.txt)" > "$REPORT_FILE" 2>&1 || {
      echo "⚠ $LLM_CMD -p failed; writing placeholder report."
      echo "# Code review (placeholder)" > "$REPORT_FILE"
      echo "\`$LLM_CMD\` invocation failed." >> "$REPORT_FILE"
    }
  else
    "$LLM_CMD" -p --mode ask --output-format text "$(cat /tmp/code-review-prompt.txt)" > "$REPORT_FILE" 2>&1 || {
      echo "⚠ $LLM_CMD -p failed; writing placeholder report."
      echo "# Code review (placeholder)" > "$REPORT_FILE"
      echo "\`$LLM_CMD\` invocation failed." >> "$REPORT_FILE"
    }
  fi
  rm -f /tmp/code-review-prompt.txt
else
  echo "# Code review (placeholder)" > "$REPORT_FILE"
  echo "No headless LLM in PATH (need \`agent\` / \`cursor-agent\` or \`claude\`)." >> "$REPORT_FILE"
fi

echo "✓ Code review report written to $REPORT_FILE (soft gate — not blocking)"
exit 0
