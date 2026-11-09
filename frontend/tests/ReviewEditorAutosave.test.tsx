import { fireEvent, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../src/api/types'
import { hl, ready, settle, setup, type } from './reviewSetup'

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('ReviewEditor autosave', () => {
  it('edits autosave after 600ms debounce, coalescing rapid edits into one PATCH', async () => {
    const s = setup([ready()])
    s.start()
    await settle()
    type('Chapter', 'T')
    await settle(300)
    type('Chapter', 'Two')
    await settle(599)
    expect(s.patchCapture).not.toHaveBeenCalled()
    await settle(1)
    expect(s.patchCapture).toHaveBeenCalledTimes(1)
    expect(s.patchCapture).toHaveBeenCalledWith('c1', { chapter: 'Two' })
    expect(screen.getByText('Saved')).toBeInTheDocument()
  })

  it('sends the full highlight list (existing ids, none for new blocks) when one changes', async () => {
    const s = setup([ready()])
    s.start()
    await settle()
    type('Highlight text', 'first!', 0)
    fireEvent.click(screen.getByRole('button', { name: '+ Add highlight' }))
    expect(screen.getAllByLabelText('Highlight text')[2]).toHaveFocus()
    type('Highlight text', 'third', 2)
    await settle(600)
    expect(s.patchCapture).toHaveBeenCalledWith('c1', {
      highlights: [
        { id: 'h1', text: 'first!', note: null },
        { id: 'h2', text: 'second', note: 'my note' },
        { text: 'third', note: null }
      ]
    })
    // The minted id is adopted: a second edit sends it, not an id-less block.
    type('Highlight text', 'third!', 2)
    await settle(600)
    expect(s.patchCapture.mock.calls[1][1].highlights![2]).toEqual({ id: 'new1', text: 'third!', note: null })
  })

  it('removing a block drops it from the list', async () => {
    const s = setup([ready()])
    s.start()
    await settle()
    fireEvent.click(within(screen.getAllByTestId('highlight-block')[0]).getByRole('button', { name: /remove/i }))
    await settle(600)
    expect(s.patchCapture).toHaveBeenCalledWith('c1', { highlights: [{ id: 'h2', text: 'second', note: 'my note' }] })
  })

  it('queues edits made during an in-flight PATCH and sends them once', async () => {
    const s = setup([ready()])
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    const original = s.patchCapture.getMockImplementation()!
    s.patchCapture.mockImplementationOnce(async (id, body) => { await gate; return original(id, body) })
    s.start()
    await settle()
    type('Chapter', 'A')
    await settle(600)
    expect(s.patchCapture).toHaveBeenCalledTimes(1)
    type('Chapter', 'AB')
    await settle(600)
    type('Chapter', 'ABC')
    await settle(600)
    expect(s.patchCapture).toHaveBeenCalledTimes(1)
    release()
    await settle()
    expect(s.patchCapture).toHaveBeenCalledTimes(2)
    expect(s.patchCapture).toHaveBeenLastCalledWith('c1', { chapter: 'ABC' })
    expect(screen.getByLabelText('Chapter')).toHaveValue('ABC')
  })

  it('an older response never overwrites newer local text', async () => {
    const s = setup([ready()])
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    const original = s.patchCapture.getMockImplementation()!
    s.patchCapture.mockImplementationOnce(async (id, body) => { await gate; return original(id, body) })
    s.start()
    await settle()
    type('Chapter', 'A')
    await settle(600)
    type('Chapter', 'AB')
    release()
    await settle(0)
    expect(screen.getByLabelText('Chapter')).toHaveValue('AB')
  })

  it('a failed autosave keeps the text and offers Retry now', async () => {
    const s = setup([ready()])
    s.patchCapture.mockRejectedValueOnce(new ApiError(0, 'network_error', 'could not reach'))
    s.start()
    await settle()
    type('Chapter', 'Keep me')
    await settle(600)
    expect(screen.getByText(/Couldn't save — retrying…/)).toBeInTheDocument()
    expect(screen.getByLabelText('Chapter')).toHaveValue('Keep me')
    fireEvent.click(screen.getByRole('button', { name: 'Retry now' }))
    await settle()
    expect(s.patchCapture).toHaveBeenCalledTimes(2)
    expect(s.patchCapture).toHaveBeenLastCalledWith('c1', { chapter: 'Keep me' })
    expect(screen.getByText('Saved')).toBeInTheDocument()
  })

  it('does not send an untouched captured_at', async () => {
    const s = setup([ready()])
    s.start()
    await settle()
    type('Chapter', 'x')
    await settle(600)
    expect(Object.keys(s.patchCapture.mock.calls[0][1])).toEqual(['chapter'])
  })

  it('converts an edited captured_at to a tz-aware ISO string', async () => {
    const s = setup([ready()])
    s.start()
    await settle()
    type('Captured', '2026-11-09T08:30:00')
    await settle(600)
    expect(s.patchCapture).toHaveBeenCalledWith('c1', { captured_at: new Date('2026-11-09T08:30:00').toISOString() })
  })

  it('empty page sends null; invalid page is not sent and is flagged', async () => {
    const s = setup([ready()])
    s.start()
    await settle()
    type('Page', '')
    await settle(600)
    expect(s.patchCapture).toHaveBeenLastCalledWith('c1', { page: null })
    type('Page', '-3')
    await settle(600)
    expect(s.patchCapture).toHaveBeenCalledTimes(1)
    expect(screen.getByText('Page must be a whole number, 0 or more.')).toBeInTheDocument()
    type('Page', '4')
    await settle(600)
    expect(s.patchCapture).toHaveBeenLastCalledWith('c1', { page: 4 })
    expect(screen.queryByText(/Page must be/)).toBeNull()
  })

  it('a re-fetch does not clobber an unsaved edit but updates status', async () => {
    const live = [ready('c1', { highlights: [hl('h1', 'orig')] })]
    const s = setup(live)
    let emit!: (e: unknown) => void
    s.client.subscribe.mockImplementation(((_id: string, cb: (e: unknown) => void) => { emit = cb; return vi.fn() }) as never)
    s.start()
    await settle()
    type('Chapter', 'typing…')
    // The server moves on (e.g. status flip + a different chapter) before our debounce fires.
    s.live[0].chapter = 'server chapter'
    s.live[0].page = 99
    s.live[0].status = 'approved'
    emit({ type: 'capture.status_changed', data: { capture_id: 'c1', status: 'approved', error: null } })
    await settle(250)
    expect(screen.getByLabelText('Chapter')).toHaveValue('typing…')
    expect(screen.getByLabelText('Page')).toHaveValue(99)
    expect(screen.getByRole('button', { name: 'Unapprove' })).toBeInTheDocument()
  })
})

