import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { vi } from 'vitest'
import { ApiContext } from '../src/api/context'
import type { ApiClient } from '../src/api/client'
import type { Batch, BatchEvent, BatchSummary, Book, Capture, CaptureStatus } from '../src/api/types'

export function capture(id: string, status: CaptureStatus, extra: Partial<Capture> = {}): Capture {
  return {
    id,
    source: 'photo',
    image_file: `${id}.jpg`,
    image_sha256: id,
    rotation: 0,
    book_slug: null,
    page: null,
    chapter: null,
    captured_at: '2026-11-08T10:00:00Z',
    status,
    error: null,
    extractor_used: null,
    highlights: [],
    ...extra
  }
}

export function batch(captures: Capture[] = [], extra: Partial<Batch> = {}): Batch {
  return {
    id: 'b1',
    default_book_slug: null,
    created_at: '2026-11-08T10:00:00Z',
    updated_at: '2026-11-08T10:00:00Z',
    status: 'open',
    warned_at: null,
    captures,
    expires_at: '2026-12-08T10:00:00Z',
    expiring_soon: false,
    ...extra
  }
}

const zeroCounts: BatchSummary['counts'] = {
  pending: 0, extracting: 0, ready: 0, failed: 0, approved: 0, pushed: 0, discarded: 0
}

export function summary(id: string, extra: Partial<BatchSummary> = {}): BatchSummary {
  return {
    id,
    status: 'open',
    default_book_slug: null,
    created_at: '2026-11-08T10:00:00Z',
    updated_at: '2026-11-08T10:00:00Z',
    warned_at: null,
    expires_at: '2026-12-08T10:00:00Z',
    expiring_soon: false,
    counts: { ...zeroCounts },
    ...extra
  }
}

export const book = (slug: string, title: string, pending = false): Book => ({
  slug, title, author: null, kind: 'fiction', pending
})

// A fake client whose methods are vi.fn()s with sane defaults; `emit` plays a backend event
// to whoever subscribed, `unsubscribe` records the cleanup.
export function fakeClient(overrides: Record<string, unknown> = {}) {
  let listener: ((e: BatchEvent) => void) | null = null
  const unsubscribe = vi.fn()
  const client = {
    ping: vi.fn().mockResolvedValue({ ok: true }),
    getHealth: vi.fn().mockResolvedValue({
      extractor: { kind: 'tesseract', ok: true, detail: '' },
      repo: { cloned: true, dirty: false, path: '/x' },
      remote: { ok: true, detail: '' }
    }),
    listBooks: vi.fn().mockResolvedValue([]),
    createBook: vi.fn(),
    listBatches: vi.fn().mockResolvedValue([]),
    createBatch: vi.fn(),
    getBatch: vi.fn().mockResolvedValue(batch()),
    patchBatch: vi.fn().mockResolvedValue(batch()),
    deleteBatch: vi.fn().mockResolvedValue(undefined),
    uploadPhotos: vi.fn().mockResolvedValue({ created: [], rejected: [] }),
    addKindle: vi.fn(),
    deleteCapture: vi.fn().mockResolvedValue(undefined),
    patchCapture: vi.fn(),
    retryCapture: vi.fn(),
    getSettings: vi.fn().mockResolvedValue({ extractor: { kind: 'tesseract' } }),
    push: vi.fn(),
    imageUrl: vi.fn((id: string) => `http://127.0.0.1:1/captures/${id}/image?token=t`),
    subscribe: vi.fn((_id: string, cb: (e: BatchEvent) => void) => {
      listener = cb
      return unsubscribe
    }),
    ...overrides
  }
  const emit = () =>
    listener?.({ type: 'capture.status_changed', data: { capture_id: 'c1', status: 'ready', error: null } })
  return { client: client as unknown as ApiClient & typeof client, emit, unsubscribe }
}

export function renderWith(client: ApiClient, ui: ReactElement) {
  return render(<ApiContext.Provider value={client}>{ui}</ApiContext.Provider>)
}
