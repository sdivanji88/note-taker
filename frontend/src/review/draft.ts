import { ApiError, type Capture, type CapturePatch } from '../api/types'
import { errorMessage } from '../format'

// The editable form of a capture. Everything is a string (or string|null) so inputs are
// controlled without parse/format round-trips fighting the user's typing; conversion to
// the wire shape happens once, in buildPatch.
export interface HighlightDraft {
  // Stable React key. Server ids can't serve: new blocks have none until the first save.
  key: string
  id: string | null
  text: string
  note: string
}

export interface Draft {
  book_slug: string | null
  page: string
  chapter: string
  captured_at: string // datetime-local value, local time
  highlights: HighlightDraft[]
}

export const PAGE_ERROR = 'Page must be a whole number, 0 or more.'
export const NOT_APPROVABLE = 'Add highlight text and choose a book before approving.'

let keySeq = 0
export const newKey = () => `k${++keySeq}`

const pad = (n: number) => String(n).padStart(2, '0')

// Backend timestamps are tz-aware ISO strings; datetime-local wants a naive local value.
// Seconds are kept (the input is rendered with step=1) so an untouched field round-trips.
export function toLocalInput(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  )
}

export function parsePage(s: string): { ok: true; value: number | null } | { ok: false } {
  const t = s.trim()
  if (t === '') return { ok: true, value: null }
  return /^\d+$/.test(t) ? { ok: true, value: Number(t) } : { ok: false }
}

// Reuses keys of blocks the draft already has (matched by id) so a server refresh doesn't
// remount textareas the user is looking at.
export function draftFromCapture(c: Capture, previous?: Draft): Draft {
  const keys = new Map(previous?.highlights.filter((h) => h.id).map((h) => [h.id, h.key]))
  return {
    book_slug: c.book_slug,
    page: c.page === null ? '' : String(c.page),
    chapter: c.chapter ?? '',
    captured_at: toLocalInput(c.captured_at),
    highlights: c.highlights.map((h) => ({
      key: keys.get(h.id) ?? newKey(),
      id: h.id,
      text: h.text,
      note: h.note ?? ''
    }))
  }
}

const sameHighlights = (a: HighlightDraft[], b: HighlightDraft[]) =>
  a.length === b.length && a.every((h, i) => h.id === b[i].id && h.text === b[i].text && h.note === b[i].note)

export type FieldName = 'book_slug' | 'page' | 'chapter' | 'captured_at' | 'highlights'

// Fields whose draft differs from what the server last confirmed. "Dirty" is derived
// rather than tracked, so an edit that is typed and then undone sends nothing.
export function dirtyFields(draft: Draft, base: Draft): FieldName[] {
  const out: FieldName[] = []
  if (draft.book_slug !== base.book_slug) out.push('book_slug')
  if (draft.page !== base.page) out.push('page')
  if (draft.chapter !== base.chapter) out.push('chapter')
  if (draft.captured_at !== base.captured_at) out.push('captured_at')
  if (!sameHighlights(draft.highlights, base.highlights)) out.push('highlights')
  return out
}

export const pageIsValid = (draft: Draft) => parsePage(draft.page).ok

// Only changed fields go out, except highlights which is always the whole list (the
// backend replaces it wholesale). An invalid page is withheld and reported inline.
export function buildPatch(draft: Draft, fields: FieldName[]): { body: CapturePatch; sent: FieldName[] } | null {
  const body: CapturePatch = {}
  const sent: FieldName[] = []
  for (const f of fields) {
    if (f === 'book_slug') body.book_slug = draft.book_slug
    else if (f === 'chapter') body.chapter = draft.chapter.trim() === '' ? null : draft.chapter
    else if (f === 'captured_at') {
      const d = new Date(draft.captured_at)
      if (draft.captured_at === '' || Number.isNaN(d.getTime())) continue
      body.captured_at = d.toISOString()
    } else if (f === 'page') {
      const p = parsePage(draft.page)
      if (!p.ok) continue
      body.page = p.value
    } else {
      body.highlights = draft.highlights.map((h) => ({
        ...(h.id ? { id: h.id } : {}),
        text: h.text,
        note: h.note === '' ? null : h.note
      }))
    }
    sent.push(f)
  }
  return sent.length ? { body, sent } : null
}

export function reviewErrorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === 'network_error') return "Can't reach the backend."
    if (e.status === 409 && e.code === 'batch_pushing')
      return 'A push is running for this batch; try again when it finishes.'
    if (e.status === 422 && e.code === 'not_approvable') return NOT_APPROVABLE
    if (e.status === 404) return 'This capture no longer exists.'
  }
  return errorMessage(e)
}

export const isGone = (e: unknown) => e instanceof ApiError && e.status === 404
export const isPushing = (e: unknown) => e instanceof ApiError && e.code === 'batch_pushing'
// Worth retrying on its own: the server never saw (or never finished) the request.
export const isTransient = (e: unknown) => e instanceof ApiError && (e.status === 0 || e.status >= 500)
