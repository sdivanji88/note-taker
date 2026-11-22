import { fireEvent, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, type BatchEvent } from '../src/api/types'
import { capture } from './helpers'
import { hl, ready, settle, setup, type } from './reviewSetup'

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

const approved = (id = 'c1') => capture(id, 'approved', { book_slug: 'dune', page: 3, highlights: [hl('h1', 'kept')] })

describe('an invalid page never holds back other edits', () => {
  it('saves a highlight edit without the page and reports the invalid page', async () => {
    const s = setup([ready()])
    s.start()
    await settle()
    type('Page', '-3')
    type('Highlight text', 'new text', 0)
    await settle(600)
    expect(s.patchCapture).toHaveBeenCalledTimes(1)
    const body = s.patchCapture.mock.calls[0][1]
    expect(body).not.toHaveProperty('page')
    expect(body.highlights![0].text).toBe('new text')
    expect(screen.getByRole('status')).toHaveTextContent(/fix the page number/i)
  })

  it('unmounting with an invalid page still saves the valid fields', async () => {
    const s = setup([ready()])
    const view = s.start()
    await settle()
    type('Page', '1.5')
    type('Chapter', 'saved anyway')
    view.unmount()
    await settle()
    expect(s.patchCapture).toHaveBeenCalledWith('c1', { chapter: 'saved anyway' })
  })
})

describe('Back to batch', () => {
  it('goes back at once when nothing is unsaved', async () => {
    const s = setup([ready()])
    s.start()
    await settle()
    fireEvent.click(screen.getByRole('button', { name: /back to batch/i }))
    await settle()
    expect(s.onBack).toHaveBeenCalled()
  })

  it('flushes first and goes back when the save succeeds', async () => {
    const s = setup([ready()])
    s.start()
    await settle()
    type('Chapter', 'x')
    fireEvent.click(screen.getByRole('button', { name: /back to batch/i }))
    await settle()
    expect(s.patchCapture).toHaveBeenCalledWith('c1', { chapter: 'x' })
    expect(s.onBack).toHaveBeenCalled()
  })

  it('stays when the save fails, offering Retry now and Leave without saving', async () => {
    const s = setup([ready()])
    s.patchCapture.mockRejectedValue(new ApiError(500, 'boom', 'down'))
    s.start()
    await settle()
    type('Chapter', 'precious')
    fireEvent.click(screen.getByRole('button', { name: /back to batch/i }))
    await settle()
    expect(s.onBack).not.toHaveBeenCalled()
    expect(screen.getByText(/Couldn't save — retrying…/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry now' })).toBeInTheDocument()
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByRole('button', { name: 'Leave without saving' })).toBeInTheDocument()
    expect(screen.getByLabelText('Chapter')).toHaveValue('precious')

    fireEvent.keyDown(dialog, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(s.onBack).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: /back to batch/i }))
    await settle()
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Leave without saving' }))
    expect(s.onBack).toHaveBeenCalledTimes(1)
  })
})

describe('approving an approved capture', () => {
  it('Cmd+Enter flushes an unsaved edit first, then moves on', async () => {
    const s = setup([approved('c1'), ready('c2', { chapter: 'two' })])
    s.start()
    await settle()
    type('Chapter', 'late edit')
    fireEvent.keyDown(document.body, { key: 'Enter', metaKey: true })
    await settle()
    expect(s.patchCapture.mock.calls.map((c) => c[1])).toEqual([{ chapter: 'late edit' }])
    expect(screen.getByLabelText('Chapter')).toHaveValue('two')
  })

  it('does not move on when that flush fails', async () => {
    const s = setup([approved('c1'), ready('c2', { chapter: 'two' })])
    s.patchCapture.mockRejectedValue(new ApiError(422, 'not_approvable', 'x'))
    s.start()
    await settle()
    type('Highlight text', '')
    fireEvent.keyDown(document.body, { key: 'Enter', ctrlKey: true })
    await settle()
    expect(screen.getByRole('alert')).toHaveTextContent('Add highlight text and choose a book before approving.')
    expect(screen.getByText('1 of 2')).toBeInTheDocument()
    expect(screen.getByLabelText('Highlight text')).toHaveValue('')
  })
})

describe('a push in progress', () => {
  it('is read-only after a 409, then unlocks and saves the held edit once the batch is no longer pushing', async () => {
    const s = setup([ready()])
    let emit!: (e: BatchEvent) => void
    s.client.subscribe.mockImplementation(((_id: string, cb: (e: BatchEvent) => void) => { emit = cb; return vi.fn() }) as never)
    // The server is mid-push: the first save is refused, and the batch reports "pushing".
    s.patchCapture.mockRejectedValueOnce(new ApiError(409, 'batch_pushing', 'push running'))
    const open = s.getBatch.getMockImplementation()!
    s.getBatch.mockImplementation(async () => ({ ...(await open()), status: 'pushing' as const }))
    s.start()
    await settle()
    type('Chapter', 'held edit')
    await settle(600)
    await settle(250)
    // The pause is explained once, in the status line; an alert on top would only repeat it.
    expect(screen.getByRole('status')).toHaveTextContent('Paused — a push is running; your edits will save when it finishes.')
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByLabelText('Chapter')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled()

    s.getBatch.mockImplementation(open)
    emit({ type: 'batch.push_progress', data: { stage: 'done' } })
    await settle(250)
    expect(screen.getByLabelText('Chapter')).toBeEnabled()
    expect(screen.getByLabelText('Chapter')).toHaveValue('held edit')
    expect(s.patchCapture).toHaveBeenCalledTimes(2)
    expect(s.patchCapture).toHaveBeenLastCalledWith('c1', { chapter: 'held edit' })
    expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled()
  })
})

describe('Cmd+Enter guard', () => {
  const approvals = (s: ReturnType<typeof setup>) =>
    s.patchCapture.mock.calls.filter(([, b]) => 'status' in b)
  // fireEvent returns false when the event's default was prevented.
  const press = (init: KeyboardEventInit = {}) =>
    fireEvent.keyDown(document.body, { key: 'Enter', metaKey: true, ...init })

  it('control: a plain Cmd+Enter approves exactly once and claims the key', async () => {
    const s = setup([ready()])
    s.start()
    await settle()
    expect(press()).toBe(false)
    press() // a second press while the first is still in flight must not double-send
    await settle()
    expect(approvals(s)).toHaveLength(1)
  })

  it.each([
    ['isComposing', { isComposing: true }],
    ['keyCode 229 (IME confirm)', { keyCode: 229 }],
    ['auto-repeat', { repeat: true }]
  ])('ignores %s without touching the event', async (_n, init) => {
    const s = setup([ready()])
    s.start()
    await settle()
    expect(press(init)).toBe(true)
    await settle()
    expect(approvals(s)).toHaveLength(0)
  })

  it('does nothing for a capture that is still extracting', async () => {
    const s = setup([capture('e1', 'extracting')])
    s.start()
    await settle()
    expect(press()).toBe(true)
    await settle()
    expect(s.patchCapture).not.toHaveBeenCalled()
  })

  it('does nothing while the batch is being pushed', async () => {
    const s = setup([ready()], {}, { status: 'pushing' })
    s.start()
    await settle()
    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled()
    expect(press()).toBe(true)
    await settle()
    expect(s.patchCapture).not.toHaveBeenCalled()
  })

  it('on an already-approved capture it still saves and moves on', async () => {
    const s = setup([approved('c1'), ready('c2', { chapter: 'two' })])
    s.start()
    await settle()
    expect(press()).toBe(false)
    await settle()
    expect(screen.getByLabelText('Chapter')).toHaveValue('two')
  })
})
