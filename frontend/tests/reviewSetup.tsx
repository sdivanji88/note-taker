import { act, fireEvent, screen } from '@testing-library/react'
import { vi } from 'vitest'
import ReviewEditor from '../src/screens/ReviewEditor'
import type { Capture, CapturePatch } from '../src/api/types'
import { batch, capture, fakeClient, renderWith } from './helpers'

export const settle = (ms = 0) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })

export const hl = (id: string, text: string, note: string | null = null) => ({ id, text, note })

// A tiny in-memory backend: PATCH applies the whitelisted fields and mints ids for new blocks.
export function setup(caps: Capture[], over: Record<string, unknown> = {}, batchExtra = {}) {
  const live = caps.map((c) => ({ ...c }))
  let minted = 0
  const patchCapture = vi.fn(async (id: string, body: CapturePatch) => {
    const c = live.find((x) => x.id === id)!
    const { highlights, status, ...rest } = body
    Object.assign(c, rest)
    if (highlights) c.highlights = highlights.map((h) => ({ id: h.id ?? `new${++minted}`, text: h.text, note: h.note ?? null }))
    if (status) c.status = status
    return { ...c }
  })
  const retryCapture = vi.fn(async (id: string) => {
    const c = live.find((x) => x.id === id)!
    c.status = 'pending'
    c.error = null // as the backend does on retry
    return { ...c }
  })
  const getBatch = vi.fn(async () => batch(live.map((c) => ({ ...c })), batchExtra))
  const f = fakeClient({ patchCapture, retryCapture, getBatch, ...over })
  const onBack = vi.fn()
  const start = (index = 0) => renderWith(f.client, <ReviewEditor batchId="b1" index={index} onBack={onBack} />)
  return { ...f, live, patchCapture, retryCapture, getBatch, onBack, start }
}

export const ready = (id = 'c1', extra: Partial<Capture> = {}) =>
  capture(id, 'ready', { book_slug: 'dune', page: 12, chapter: 'One', highlights: [hl('h1', 'first'), hl('h2', 'second', 'my note')], ...extra })

export const type = (label: string, value: string, nth = 0) =>
  fireEvent.change(screen.getAllByLabelText(label)[nth], { target: { value } })

export const ARROW = (key: string, target: Element = document.body) => fireEvent.keyDown(target, { key })
