# note-taker

Note Taker is a local macOS desktop app that turns highlights from physical books into a
git-backed knowledge base. You photograph yellow-highlighted pages (or paste Kindle
highlight text), drop the photos into the app, fix what the extractor got wrong, and push
the approved highlights to a GitHub repo you own. Each book becomes one markdown file
(`books/<slug>.md`) that you can reread later. Extraction runs locally (Tesseract OCR or an
Ollama vision model); nothing leaves your machine except `git push`.

## Capture flow

1. Photograph the highlighted pages (or copy Kindle highlights).
2. Click **New batch**, pick or create the book, and drop the photos onto the batch grid.
   Extraction runs in the background; thumbnails show their status.
3. Open **Review**: one page at a time, edit the text, add a note, set page and chapter,
   then **Approve**. Edits save automatically.
4. Click **Push all approved**. The app appends one section per highlight to the book's
   file, commits, and pushes. The batch (and its photos) is then deleted from this computer.

## Prerequisites

- macOS
- [uv](https://docs.astral.sh/uv/) and Node 20+
- Tesseract: `brew install tesseract`
- [Ollama](https://ollama.com) with a vision model pulled (only needed for the Ollama extractor)
- `git` with credentials already working for your notes repo (SSH key or a credential
  helper). The app stores no tokens; avoid putting one in the remote URL.

## Setup and run

```bash
(cd backend && uv sync)
(cd frontend && npm ci)
ollama pull qwen2.5vl:7b
(cd frontend && npm run dev)     # starts the app, which spawns the Python backend
```

`qwen2.5vl:7b` is the default model, but it is a placeholder: it has not been tested against
real photos. Change the model name in Settings if you prefer another vision model.

## First run

1. Open **Settings**. Enter your notes repo's **Remote URL** and **Branch**, then **Save**.
2. Click **Connect repo**. The app clones it (or, if you set "Use existing clone", uses
   that folder).
3. Choose the **Extractor** (Ollama or Tesseract) and Save.

## Where data lives

Electron's userData folder, `~/Library/Application Support/note-taker-frontend/`, unless
`NOTE_TAKER_DATA_DIR` is set:

- `settings.json`: your settings
- `batches/<id>/`: `batch.json` and `photos/` for each in-progress batch
- `repo/`: the default clone of your notes repo
- `pending_books.json`: books you created that have no file in the repo yet

Local storage only ever holds in-progress batches. A batch is deleted when its push
succeeds, or after 30 days of inactivity (the app warns first). Photos are never committed.

## Notes repo format

One file per book, append-only. Each highlight ends with a marker comment, which makes
retried pushes safe (a section whose marker already exists is skipped).

```markdown
---
title: Permutation City
author: Greg Egan
kind: fiction
---

# Permutation City

## p.163 · The Lobian Argument · 2026-11-09 18:42

> Memory is the city we rebuild every morning.

**Note:** Compare with chapter 2.

<!-- nt:highlight=01JC... -->
```

Each push is one commit: `notes: <n> highlights from <titles>` with a `Note-Taker-Batch:` trailer.

## Testing

```bash
(cd backend && uv run pytest -q)          # unit + real-git integration tests
(cd backend && uv run pytest -m live)     # manual: real Ollama / Tesseract
(cd frontend && npx vitest run)           # component tests
(cd frontend && npm run build && npm run test:e2e)   # Electron end-to-end
bash scripts/ui-test.sh                   # vitest + build + e2e
bash scripts/architecture-review.sh       # architecture gate
```

The e2e launches the built app against a temp data dir, a temp bare git remote and a temp
HOME. Its Kindle-path test needs no external tools. The photo-path test needs `tesseract`
on PATH and is skipped otherwise.

## Known limitations

1. Pushes are append-only and highlights are recognised by id, so a highlight already in the
   repo is never rewritten. Through the app its text can no longer change between review and
   push (edits are refused while a push runs, and the push writes exactly the reviewed text);
   what remains is a highlight id changed outside the app, or the repo file edited by hand,
   which the app neither detects nor repairs.
2. Changes to `extractor.concurrency` and `timeout_s` need an app restart.
3. OCR and vision accuracy, the highlight detection thresholds and the default model are
   untested on real photos: Tesseract and Ollama were not installed on the machine where the
   app was built (there is no CI).
4. An existing clone must be on the configured branch, with `origin` set to the configured
   remote URL; otherwise the app refuses to push (and does not pull) until you fix the clone
   or Settings. The Settings page shows the remote and branch the app will actually use
   (surrounding whitespace is trimmed and `~` in the clone path is expanded on save).
5. Backend logs (plain text) appear in the terminal running `npm run dev`; there is no log file.
6. Run `(cd backend && uv sync)` before the e2e, which starts the real backend.
7. macOS only, and dev-mode only (`npm run dev`); there is no packaged app.
8. No search or tagging inside the app; use the repo (grep, your editor, GitHub).
