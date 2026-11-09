import type { ExtractorKind, Settings } from '../api/types'

// Number inputs are held as strings so a half-typed or empty value is representable and
// can be reported inline instead of being coerced to 0 or NaN behind the user's back.
export interface Form {
  remote_url: string
  branch: string
  local_path: string
  books_dir: string
  kind: ExtractorKind
  base_url: string
  model: string
  concurrency: string
  timeout_s: string
  expiry_days: string
  warn_days_before: string
}

export type FieldName = keyof Form

export function toForm(s: Settings): Form {
  return {
    remote_url: s.notes_repo.remote_url,
    branch: s.notes_repo.branch,
    local_path: s.notes_repo.local_path ?? '',
    books_dir: s.notes_repo.books_dir,
    kind: s.extractor.kind,
    base_url: s.extractor.ollama.base_url,
    model: s.extractor.ollama.model,
    concurrency: String(s.extractor.concurrency),
    timeout_s: String(s.extractor.timeout_s),
    expiry_days: String(s.batches.expiry_days),
    warn_days_before: String(s.batches.warn_days_before)
  }
}

// Settings the form has no fields for (tesseract tuning) are carried over from the server
// copy so saving cannot silently reset them.
export function toSettings(f: Form, server: Settings): Settings {
  return {
    // Trimmed because pasted values often carry stray spaces (the backend strips too).
    notes_repo: {
      remote_url: f.remote_url.trim(),
      branch: f.branch.trim(),
      local_path: f.local_path.trim() === '' ? null : f.local_path.trim(),
      books_dir: f.books_dir.trim()
    },
    extractor: {
      ...server.extractor,
      kind: f.kind,
      ollama: { base_url: f.base_url, model: f.model },
      concurrency: Number(f.concurrency),
      timeout_s: Number(f.timeout_s)
    },
    batches: { expiry_days: Number(f.expiry_days), warn_days_before: Number(f.warn_days_before) }
  }
}

function intIn(v: string, min: number, max: number): boolean {
  if (!/^\d+$/.test(v.trim())) return false
  const n = Number(v)
  return n >= min && n <= max
}

// Only the simple numeric bounds are mirrored here; the backend stays the authority for
// everything else (paths, branch names, URL schemes) and its 422 text is shown as-is.
export function validate(f: Form): Partial<Record<FieldName, string>> {
  const errors: Partial<Record<FieldName, string>> = {}
  if (!intIn(f.expiry_days, 1, Infinity)) errors.expiry_days = 'Expiry days must be at least 1'
  if (!intIn(f.warn_days_before, 0, Infinity)) errors.warn_days_before = 'Warning days must be 0 or more'
  if (!intIn(f.concurrency, 1, 4)) errors.concurrency = 'Concurrency must be between 1 and 4'
  if (!intIn(f.timeout_s, 1, 3600)) errors.timeout_s = 'Timeout must be between 1 and 3600'
  return errors
}

// Visual order, used to focus the first invalid field.
export const FIELD_ORDER: FieldName[] = [
  'remote_url', 'branch', 'local_path', 'books_dir', 'base_url', 'model',
  'concurrency', 'timeout_s', 'expiry_days', 'warn_days_before'
]

// A password/token in a URL's userinfo ends up in settings.json in plain text. Plain
// `ssh://git@host` is normal, so only flag http(s) userinfo or any `user:secret@`.
export function urlHasCredentials(url: string): boolean {
  const m = /^[a-z][a-z0-9+.-]*:\/\/([^/?#\s]*)@/i.exec(url.trim())
  if (!m) return false
  return m[1].includes(':') || /^https?:/i.test(url.trim())
}
