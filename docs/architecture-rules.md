# Architecture Rules — note-taker

These rules govern every non-trivial code change in this project. The `architect` and `code-reviewer` subagents enforce them; `scripts/architecture-review.sh` audits adherence.

The underlying principle: **reduce cognitive load for the next developer** (often a future version of you, or an AI agent loading the project cold). Speed of delivery is not a license to leave complexity behind.

---

## 1. Prioritize complexity management

Primary directive: **reduce cognitive load** for future developers.

- **Cognitive load:** minimize what a developer needs to know to complete a task.
- **Change amplification:** reduce how many places must be modified for a single conceptual change.

When coding: if a change requires modifications in multiple unrelated files, there is likely an information leak. Consolidate related knowledge into a single module.

## 2. Strategic over tactical programming

Do not prioritize speed of delivery over code quality.

- Allocate **~10–20% of effort to improving design** as you go.
- Don't just "make it work" — make it clean.
- Avoid being a "tactical tornado" who moves fast but leaves complexity behind.

## 3. Build deep modules

Design modules that are **deep**, not shallow.

- **Deep:** powerful functionality through a simple, narrow interface (e.g. a file I/O module that hides buffering, error handling, OS differences).
- **Shallow:** complex interface for minimal internal logic (anti-pattern).

**Rule:** if a module's interface is nearly as complex as its implementation, it isn't providing enough abstraction.

## 4. Information hiding, not leakage

The most important technique for achieving deep modules.

- **Information hiding:** internal details invisible to users of the module.
- **Information leakage:** a design decision reflected in multiple modules (anti-pattern).

When coding: if changing one class forces changes in another, identify and fix the leak. Hide data structures, algorithms, and implementation details behind clean interfaces.

## 5. Define errors out of existence

Exception handling is a major source of complexity.

- Prefer: define method behavior to eliminate the error condition.
- Avoid: throwing exceptions for every edge case.

**Example:**
- Bad: `delete_range()` throws an error if the range doesn't exist.
- Good: define `delete_range()` as "ensure this range does not exist" — if already gone, success.

## 6. Pull complexity downward

When faced with where to handle complexity, **push it into the module, not to callers**.

Better for one module to be slightly more complex internally than for ten callers to handle that complexity each. Handle edge cases, defaults, and configuration internally when possible. Make the common case trivially easy; hide the complex cases.

## 7. Naming and comments

### Naming

- Intuitive and precise.
- If a name needs a comment to explain it, the name is poor.
- Use consistent terminology across the codebase.

### Comments — focus on the unknowns

Comments document what is **not obvious** from the code.

**Don't:**
- Repeat the code (`i += 1  # increment i` is useless).
- Describe mechanics obvious from reading the code.

**Do:**
- Explain intent (the "why").
- Describe results and side effects.
- Document design decisions and trade-offs.
- Note preconditions and constraints ("input must be sorted", "not thread-safe").

### Interface comments

Write from the perspective of the **user** of the module.

- Describe high-level behavior, arguments, return values.
- Mention side effects and preconditions.
- If a user must read implementation code to understand usage, the interface comment has failed.

### Document the "why"

Code shows what the system does; comments explain why it was built that way.

- Rationale behind non-obvious design choices.
- Trade-offs and algorithmic choices.
- If using a workaround for a third-party bug, explain why so it isn't "cleaned up" later.

### Comment-first development

Write comments **before** code as a design tool.

1. Write the interface comment for a method before implementing it.
2. If the comment is difficult to write or feels wordy, the design is likely shallow or poorly structured.
3. Use this as feedback to simplify the design before committing to implementation.

### Cross-module documentation

For design decisions affecting multiple files:

- Create central design notes in `docs/`.
- Document at the primary entry point.
- Do not scatter fragments of the same explanation across multiple files.

---

## Good vs bad comments

| Feature | Bad (redundant) | Good (informative) |
|---------|-----------------|--------------------|
| Focus | What the code does | Intent or constraints |
| Clarity | Same words as function name | Adds info not in signature |
| Depth | Shallow — describes the "how" | Deep — describes the "why" or "what if" |

---

## Enforcement

`scripts/architecture-review.sh` audits this file's rules against the recent diff:

1. **Static metrics gate (hard):**
   - File LOC > threshold → flagged
   - Single function with > 50 lines → flagged
   - File with > 15 imports → flagged (potential information leak)
   - Cyclomatic complexity > 10 → flagged

2. **LLM audit (hard):** invokes `claude -p` with this file + the diff, asking for any violations of rules 1–7. Any high-confidence violation → fail.

`code-reviewer` subagent uses this file as its rubric.
