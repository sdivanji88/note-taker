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

# Invoke claude headless to produce the review. Falls back to a placeholder if claude isn't installed.
if command -v claude > /dev/null 2>&1; then
  PROMPT=$(cat <<'EOF'
You are reviewing a code diff for correctness, clarity, and adherence to the architecture rules in docs/architecture-rules.md.

Output a markdown report with these sections:

## Summary
One-paragraph overall assessment.

## Findings
For each finding: severity (high/medium/low), file:line, what's wrong, suggested fix.

## Architecture rule violations
Specifically flag violations of: deep modules, information hiding, defining errors out of existence, pulling complexity downward, naming/commenting.

Only flag things you are confident about. Empty sections are fine.

The diff:
EOF
)
  echo "$PROMPT" > /tmp/code-review-prompt.txt
  echo "$DIFF_CONTENT" >> /tmp/code-review-prompt.txt

  claude -p "$(cat /tmp/code-review-prompt.txt)" > "$REPORT_FILE" 2>&1 || {
    echo "⚠ claude -p failed; writing placeholder report."
    echo "# Code review (placeholder)" > "$REPORT_FILE"
    echo "claude CLI invocation failed. Run \`claude\` manually with the diff above." >> "$REPORT_FILE"
  }
  rm -f /tmp/code-review-prompt.txt
else
  echo "# Code review (placeholder)" > "$REPORT_FILE"
  echo "claude CLI not found in PATH — install it to enable LLM-driven code review." >> "$REPORT_FILE"
fi

echo "✓ Code review report written to $REPORT_FILE (soft gate — not blocking)"
exit 0
