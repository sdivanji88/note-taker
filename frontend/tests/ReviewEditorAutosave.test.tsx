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
    expect(screen.getByLabelText('Page')).toHaveValue('99')
    expect(screen.getByRole('button', { name: 'Unapprove' })).toBeInTheDocument()
  })
})

describe('ReviewEditor page field', () => {
  const pageInput = () => screen.getByLabelText('Page') as HTMLInputElement
  const pageKeyed = (s: ReturnType<typeof setup>) =>
    s.patchCapture.mock.calls.filter(([, body]) => 'page' in body)

  it('is a text field with a numeric keypad, so bad input reaches our validation', async () => {
    const s = setup([ready()])
    s.start()
    await settle()
    expect(pageInput()).toHaveAttribute('type', 'text')
    expect(pageInput()).toHaveAttribute('inputmode', 'numeric')
    expect(pageInput()).toHaveAttribute('autocomplete', 'off')
    for (const a of ['min', 'step', 'pattern']) expect(pageInput()).not.toHaveAttribute(a)
  })

  it('flags "12a" at once, keeps the text, and never sends it', async () => {
    const s = setup([ready('c1', { page: null })])
    s.start()
    await settle()
    type('Page', '12a')
    const error = screen.getByText('Page must be a whole number, 0 or more.')
    expect(error).toHaveAttribute('id', 'page-error')
    expect(error).toHaveAttribute('role', 'alert')
    expect(pageInput()).toHaveAttribute('aria-invalid', 'true')
    expect(pageInput()).toHaveAttribute('aria-describedby', 'page-error')
    expect(pageInput()).toHaveValue('12a')
    await settle(600)
    expect(pageKeyed(s)).toHaveLength(0)
    expect(screen.getByRole('status')).toHaveTextContent('Not saved — fix the page number')
  })

  it.each(['-3', '1.5', '1e2'])('rejects %s', async (bad) => {
    const s = setup([ready()])
    s.start()
    await settle()
    type('Page', bad)
    expect(screen.getByText('Page must be a whole number, 0 or more.')).toBeInTheDocument()
    expect(pageInput()).toHaveAttribute('aria-invalid', 'true')
    await settle(600)
    expect(pageKeyed(s)).toHaveLength(0)
  })

  it('other edits still autosave while the page is invalid', async () => {
    const s = setup([ready()])
    s.start()
    await settle()
    type('Page', '12a')
    type('Chapter', 'Two')
    await settle(600)
    expect(s.patchCapture).toHaveBeenCalledTimes(1)
    expect(s.patchCapture).toHaveBeenCalledWith('c1', { chapter: 'Two' })
  })

  it('fixing the page clears the error and autosave resumes', async () => {
    const s = setup([ready('c1', { page: null })])
    s.start()
    await settle()
    type('Page', '12a')
    type('Page', '12')
    expect(screen.queryByText(/Page must be/)).toBeNull()
    expect(pageInput()).toHaveAttribute('aria-invalid', 'false')
    expect(pageInput()).not.toHaveAttribute('aria-describedby')
    await settle(600)
    expect(s.patchCapture).toHaveBeenCalledWith('c1', { page: 12 })
  })

  it('clearing the field sends page:null only when the capture had a page', async () => {
    const had = setup([ready()])
    had.start()
    await settle()
    type('Page', '')
    await settle(600)
    expect(had.patchCapture).toHaveBeenCalledWith('c1', { page: null })
  })

  it('clearing a field that was already empty sends nothing', async () => {
    const none = setup([ready('c1', { page: null })])
    none.start()
    await settle()
    type('Page', '4')
    type('Page', '')
    await settle(600)
    expect(none.patchCapture).not.toHaveBeenCalled()
  })

  it('Approve with an invalid page is blocked and focus goes to the page field', async () => {
    const s = setup([ready()])
    s.start()
    await settle()
    type('Page', 'abc')
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await settle()
    expect(s.patchCapture.mock.calls.filter(([, b]) => 'status' in b)).toHaveLength(0)
    expect(document.activeElement).toBe(pageInput())
  })

  it('Next with an invalid page stays on the capture and focuses the page field', async () => {
    const s = setup([ready('c1'), ready('c2')])
    s.start()
    await settle()
    type('Page', 'abc')
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await settle()
    expect(screen.getByText('1 of 2')).toBeInTheDocument()
    expect(document.activeElement).toBe(pageInput())
  })

  it('Back with an invalid page focuses the page field, and Stay returns there', async () => {
    const s = setup([ready()])
    s.start()
    await settle()
    type('Page', 'abc')
    fireEvent.click(screen.getByRole('button', { name: /back to batch/i }))
    await settle()
    expect(s.onBack).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Stay' }))
    expect(document.activeElement).toBe(pageInput())
  })
})

describe('ReviewEditor save-failure messages', () => {
  async function failSave(err: ApiError) {
    const s = setup([ready()])
    s.patchCapture.mockRejectedValue(err)
    s.start()
    await settle()
    type('Chapter', 'Keep me')
    await settle(600)
    return s
  }
  const status = () => screen.getByRole('status')

  it.each([
    ['409 invalid_transition', new ApiError(409, 'invalid_transition', 'cannot change status from failed to approved'),
      "Couldn't save — conflict: cannot change status from failed to approved"],
    ['422', new ApiError(422, 'invalid', 'highlight text too long'), "Couldn't save — not accepted: highlight text too long"],
    ['other 4xx', new ApiError(400, 'bad', 'bad request body'), "Couldn't save: bad request body"]
  ])('%s: says "Not saved", explains, offers Try again and never auto-retries', async (_n, err, alert) => {
    const s = await failSave(err)
    expect(status()).toHaveTextContent(/^Not saved\s*Try again$/)
    expect(status()).not.toHaveTextContent(/retrying/i)
    expect(screen.getAllByRole('alert')).toHaveLength(1) // one assertive message per event
    expect(screen.getByRole('alert')).toHaveTextContent(alert)
    expect(screen.queryByRole('button', { name: 'Retry now' })).toBeNull()
    expect(screen.getByLabelText('Chapter')).toHaveValue('Keep me')

    await settle(3000)
    expect(s.patchCapture).toHaveBeenCalledTimes(1)

    // The draft stayed dirty, so Try again re-sends it.
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await settle()
    expect(s.patchCapture).toHaveBeenCalledTimes(2)
    expect(s.patchCapture).toHaveBeenLastCalledWith('c1', { chapter: 'Keep me' })
  })

  it.each([
    ['network error', new ApiError(0, 'network_error', 'could not reach')],
    ['500', new ApiError(500, 'boom', 'down')]
  ])('%s: says "retrying…", offers Retry now and retries by itself after 3s', async (_n, err) => {
    const s = await failSave(err)
    expect(status()).toHaveTextContent("Couldn't save — retrying…")
    expect(screen.getByRole('button', { name: 'Retry now' })).toBeInTheDocument()
    expect(s.patchCapture).toHaveBeenCalledTimes(1)
    await settle(3000)
    expect(s.patchCapture).toHaveBeenCalledTimes(2)
  })

  it('409 batch_pushing: paused text only, no alert, no button, no retry timer', async () => {
    const s = setup([ready()])
    s.patchCapture.mockRejectedValue(new ApiError(409, 'batch_pushing', 'push running'))
    const open = s.getBatch.getMockImplementation()!
    s.start()
    await settle()
    type('Chapter', 'Keep me')
    // The push is what refused the save, so the re-fetch the pane triggers reports it.
    s.getBatch.mockImplementation(async () => ({ ...(await open()), status: 'pushing' as const }))
    await settle(600)
    await settle(250)
    expect(status()).toHaveTextContent('Paused — a push is running; your edits will save when it finishes.')
    expect(screen.queryByRole('alert')).toBeNull()
    expect(within(status()).queryByRole('button')).toBeNull()
    await settle(3000)
    expect(s.patchCapture).toHaveBeenCalledTimes(1)
  })
})
