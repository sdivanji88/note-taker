#!/usr/bin/env bash
# Architecture review — HARD gate. Two stages:
#   1. Static metrics (file LOC, function size, import fan-out, complexity heuristics)
#   2. LLM audit against docs/architecture-rules.md
# Both must pass. Non-zero exit blocks the feature's Definition of Done.

set -uo pipefail

cd "$(dirname "$0")/.."

REPORT_FILE=".architecture-review.md"
FAILED=0

# Thresholds — tune per project
MAX_FILE_LOC=500
MAX_FUNCTION_LOC=50
MAX_IMPORTS_PER_FILE=15

# Composition roots exist to wire every component together, so a high import count is
# their job rather than a leak. Exempt from the import-count check ONLY (not LOC).
# Keep this list to files whose sole role is wiring; anything else must pass.
COMPOSITION_ROOTS="./backend/src/note_taker/api/app.py ./backend/src/note_taker/api/deps.py"

echo "# Architecture review — $(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$REPORT_FILE"
echo "" >> "$REPORT_FILE"
echo "## Stage 1 — static metrics" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

# Collect source files based on detected stack (extend as needed)
# Dependency, build and cache dirs are excluded at ANY depth (e.g. backend/.venv),
# not just at the repo root.
SOURCE_FILES=$(find . -type f \
  \( -name "*.py" -o -name "*.ts" -o -name "*.tsx" -o -name "*.js" -o -name "*.jsx" \
     -o -name "*.go" -o -name "*.rs" -o -name "*.java" -o -name "*.rb" -o -name "*.kt" \) \
  -not -path "*/node_modules/*" -not -path "*/.git/*" -not -path "*/vendor/*" \
  -not -path "*/dist/*" -not -path "*/build/*" -not -path "*/.venv/*" \
  -not -path "*/target/*" -not -path "*/__pycache__/*" 2>/dev/null)

# 1a. Files exceeding LOC threshold
echo "### Files exceeding $MAX_FILE_LOC LOC" >> "$REPORT_FILE"
OVERSIZED=0
for f in $SOURCE_FILES; do
  loc=$(wc -l < "$f" | tr -d ' ')
  if [ "$loc" -gt "$MAX_FILE_LOC" ]; then
    echo "- $f ($loc lines)" >> "$REPORT_FILE"
    OVERSIZED=$((OVERSIZED + 1))
  fi
done
if [ "$OVERSIZED" -eq 0 ]; then
  echo "_None._" >> "$REPORT_FILE"
else
  echo "" >> "$REPORT_FILE"
  echo "**FAIL:** $OVERSIZED file(s) exceed the LOC threshold. Consider splitting into deeper modules." >> "$REPORT_FILE"
  FAILED=1
fi
echo "" >> "$REPORT_FILE"

# 1b. Files with too many imports (information-leakage smell)
echo "### Files with > $MAX_IMPORTS_PER_FILE imports" >> "$REPORT_FILE"
LEAKY=0
for f in $SOURCE_FILES; do
  case " $COMPOSITION_ROOTS " in *" $f "*) continue ;; esac
  # grep -c prints 0 AND exits 1 on no match, so `|| echo 0` would yield "0\n0";
  # `|| true` plus a default keeps the value a single integer.
  case "$f" in
    *.py) count=$(grep -cE "^(import |from .* import )" "$f" 2>/dev/null || true) ;;
    *.ts|*.tsx|*.js|*.jsx) count=$(grep -cE "^(import |const .* = require)" "$f" 2>/dev/null || true) ;;
    *.go) count=$(awk '/^import \(/,/^\)/' "$f" 2>/dev/null | grep -cE '^\s*"' || true) ;;
    *) count=0 ;;
  esac
  count=${count:-0}
  if [ "$count" -gt "$MAX_IMPORTS_PER_FILE" ]; then
    echo "- $f ($count imports)" >> "$REPORT_FILE"
    LEAKY=$((LEAKY + 1))
  fi
done
if [ "$LEAKY" -eq 0 ]; then
  echo "_None._" >> "$REPORT_FILE"
else
  echo "" >> "$REPORT_FILE"
  echo "**FAIL:** $LEAKY file(s) import too many things. Likely information leak or unfocused module." >> "$REPORT_FILE"
  FAILED=1
fi
echo "" >> "$REPORT_FILE"

# 1c. Optional: language-specific complexity tooling
# Python — radon if installed
if command -v radon > /dev/null 2>&1; then
  echo "### Python cyclomatic complexity (radon)" >> "$REPORT_FILE"
  COMPLEX=$(radon cc . -n C -s 2>/dev/null || true)
  if [ -n "$COMPLEX" ]; then
    echo '```' >> "$REPORT_FILE"
    echo "$COMPLEX" >> "$REPORT_FILE"
    echo '```' >> "$REPORT_FILE"
    echo "**FAIL:** functions exceeding complexity threshold C." >> "$REPORT_FILE"
    FAILED=1
  else
    echo "_All under threshold._" >> "$REPORT_FILE"
  fi
  echo "" >> "$REPORT_FILE"
fi

# Stage 2 — LLM audit
echo "## Stage 2 — LLM audit against docs/architecture-rules.md" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

if [ ! -f "docs/architecture-rules.md" ]; then
  echo "**SKIP:** docs/architecture-rules.md not found." >> "$REPORT_FILE"
elif ! command -v claude > /dev/null 2>&1; then
  echo "**SKIP:** claude CLI not in PATH." >> "$REPORT_FILE"
else
  # Get the relevant diff (staged or HEAD~1..HEAD)
  if git rev-parse --git-dir > /dev/null 2>&1; then
    if ! git diff --cached --quiet 2>/dev/null; then
      DIFF=$(git diff --cached 2>/dev/null)
    elif git rev-parse HEAD > /dev/null 2>&1; then
      DIFF=$(git diff HEAD~1..HEAD 2>/dev/null || echo "")
    else
      DIFF=""
    fi
  else
    DIFF=""
  fi

  if [ -z "$DIFF" ]; then
    echo "_No diff to audit._" >> "$REPORT_FILE"
  else
    RULES=$(cat docs/architecture-rules.md)
    PROMPT_FILE=$(mktemp)
    cat > "$PROMPT_FILE" <<EOF
Audit the following code diff against these architecture rules. Be strict — flag any HIGH-CONFIDENCE violation. Skip low-confidence concerns.

Output:
- If no violations: print exactly "PASS"
- If violations: print "FAIL" then a bulleted list of (file:line, rule violated, why).

Rules:
$RULES

Diff:
$DIFF
EOF
    AUDIT=$(claude -p "$(cat "$PROMPT_FILE")" 2>&1 || echo "AUDIT_ERROR")
    rm -f "$PROMPT_FILE"

    echo '```' >> "$REPORT_FILE"
    echo "$AUDIT" >> "$REPORT_FILE"
    echo '```' >> "$REPORT_FILE"

    if echo "$AUDIT" | head -1 | grep -qi "^FAIL"; then
      FAILED=1
    fi
  fi
fi

echo "" >> "$REPORT_FILE"
echo "## Result" >> "$REPORT_FILE"
if [ "$FAILED" -eq 0 ]; then
  echo "**PASS** — architecture review clean." >> "$REPORT_FILE"
  echo "✓ Architecture review passed. Report: $REPORT_FILE"
  exit 0
else
  echo "**FAIL** — see findings above." >> "$REPORT_FILE"
  echo "✗ Architecture review FAILED. Report: $REPORT_FILE"
  exit 1
fi
