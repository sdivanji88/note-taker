// Hand-written mirrors of the backend's JSON (backend/src/note_taker/models.py and
// api/routes_*.py). Field names stay snake_case so a response needs no translation
// layer; if the backend changes a shape, change it here and the compiler finds users.

export type CaptureStatus =
  | 'pending'
  | 'extracting'
  | 'ready'
  | 'failed'
  | 'approved'
  | 'pushed'
  | 'discarded'

export type BatchStatus = 'open' | 'pushing' | 'pushed' | 'discarded'
export type Source = 'photo' | 'kindle'
export type BookKind = 'fiction' | 'non-fiction'
export type ExtractorKind = 'ollama' | 'tesseract'

export interface Highlight {
  id: string
  text: string
  note: string | null
}

export interface Capture {
  id: string
  source: Source
  image_file: string | null
  image_sha256: string | null
  rotation: 0 | 90 | 180 | 270
  book_slug: string | null
  page: number | null
  chapter: string | null
  captured_at: string
  status: CaptureStatus
  error: string | null
  extractor_used: string | null
  highlights: Highlight[]
}

// GET/POST/PATCH /batches/{id}: the full batch.
export interface Batch {
  id: string
  default_book_slug: string | null
  created_at: string
  updated_at: string
  status: BatchStatus
  warned_at: string | null
  captures: Capture[]
  expires_at: string
  expiring_soon: boolean
}

// GET /batches: one row per batch, without captures but with per-status counts.
export interface BatchSummary {
  id: string
  status: BatchStatus
  default_book_slug: string | null
  created_at: string
  updated_at: string
  warned_at: string | null
  expires_at: string
  expiring_soon: boolean
  counts: Record<CaptureStatus, number>
}

export interface Book {
  slug: string
  title: string
  author: string | null
  kind: BookKind
  pending: boolean
}

export interface Settings {
  notes_repo: {
    remote_url: string
    branch: string
    local_path: string | null
    books_dir: string
  }
  extractor: {
    kind: ExtractorKind
    ollama: { base_url: string; model: string }
    tesseract: {
      hsv_low: [number, number, number]
      hsv_high: [number, number, number]
      lang: string
    }
    concurrency: number
    timeout_s: number
  }
  batches: { expiry_days: number; warn_days_before: number }
  // Response-only: the backend masks credentials in remote_url and reports here
  // whether the stored URL has any. Ignored by the backend when sent back.
  remote_url_has_credentials?: boolean
}

export interface RepoHealth {
  cloned: boolean
  dirty: boolean | null
  path: string
}

export interface Health {
  extractor: { kind: ExtractorKind; ok: boolean; detail: string }
  repo: RepoHealth
  remote: { ok: boolean; detail: string }
}

export interface PushResult {
  commit_sha: string
  files_changed: string[]
  highlights_written: number
  batch_deleted: boolean
}

export interface UploadRejection {
  filename: string
  reason: 'too_large' | 'too_many_files' | 'unsupported_type' | 'duplicate'
}

export interface UploadResult {
  created: Capture[]
  rejected: UploadRejection[]
}

export interface HighlightInput {
  id?: string | null
  text: string
  note?: string | null
}

export interface KindleInput {
  source: 'kindle'
  highlights: HighlightInput[]
  book_slug?: string | null
  page?: number | null
  chapter?: string | null
  captured_at?: string | null
}

// Only the fields the backend lets a client change; absent means "leave as is".
export interface CapturePatch {
  highlights?: HighlightInput[]
  book_slug?: string | null
  page?: number | null
  chapter?: string | null
  captured_at?: string
  rotation?: 0 | 90 | 180 | 270
  status?: CaptureStatus
}

export interface NewBook {
  title: string
  author?: string | null
  kind: BookKind
}

// Server-sent events on /batches/{id}/events (the SSE `event:` name is `type`).
export type BatchEvent =
  | { type: 'capture.status_changed'; data: { capture_id: string; status: CaptureStatus; error: string | null } }
  | { type: 'capture.extracted'; data: { capture_id: string; capture: Capture } }
  | { type: 'batch.push_progress'; data: { stage: string; code?: string } }

export interface BackendConfig {
  baseUrl: string
  token: string
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string

  // status 0 means the request never got an HTTP response (backend down).
  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}
