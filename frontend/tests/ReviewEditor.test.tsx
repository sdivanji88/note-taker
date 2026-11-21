import { fireEvent, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../src/api/types'
import { ARROW, hl, ready, settle, setup, type } from './reviewSetup'
import { capture } from './helpers'

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('ReviewEditor rendering', () => {
  it('renders one block per highlight with shared page field', async () => {
    const s = setup([ready()])
    s.start()
    await settle()
    expect(screen.getByLabelText('Page')).toHaveValue(12)
    expect(screen.getByLabelText('Chapter')).toHaveValue('One')
    expect(screen.getAllByLabelText('Highlight text')).toHaveLength(2)
    expect(screen.getAllByLabelText('My note')[1]).toHaveValue('my note')
    expect(screen.getByText('1 of 1')).toBeInTheDocument()
    expect(screen.getByAltText(/page 12/i)).toHaveAttribute('src', expect.stringContaining('/captures/c1/image?token=t&v=0'))
  })

  it('shows the active extractor from settings', async () => {
    const s = setup([ready()])
    s.start()
    await settle()
    expect(screen.getByText(/tesseract/i)).toBeInTheDocument()
  })

  it('Kindle captures show a panel instead of a photo', async () => {
    const s = setup([capture('k1', 'ready', { source: 'kindle', image_file: null, highlights: [hl('h1', 'x')] })])
    s.start()
    await settle()
    expect(screen.getByText('Kindle highlight')).toBeInTheDocument()
    expect(screen.queryByRole('img')).toBeNull()
    expect(screen.queryByRole('button', { name: /rotate/i })).toBeNull()
  })

  it('renders hostile text literally', async () => {
    const evil = '<img src=x onerror=alert(1)>'
    const s = setup([ready('c1', { chapter: evil, highlights: [hl('h1', evil, evil)] })])
    s.start()
    await settle()
    expect(screen.getByLabelText('Chapter')).toHaveValue(evil)
    expect(screen.getByLabelText('Highlight text')).toHaveValue(evil)
    expect(document.querySelector('img[src="x"]')).toBeNull()
  })
})

describe('ReviewEditor read-only states', () => {
  it.each(['pending', 'extracting'] as const)('%s captures are read-only with only Discard enabled', async (status) => {
    const s = setup([capture('c1', status, { image_file: 'c1.jpg' })])
    s.start()
    await settle()
    expect(screen.getByText(/Still extracting… you can edit once it's ready/)).toBeInTheDocument()
    expect(screen.getByLabelText('Page')).toBeDisabled()
    expect(screen.getByLabelText('Chapter')).toBeDisabled()
    expect(screen.getByRole('button', { name: '+ Add highlight' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Discard' })).toBeEnabled()
  })

  it('a pending capture with an extractor error explains it and offers Retry', async () => {
    const s = setup([capture('c1', 'pending', { image_file: 'c1.jpg', error: 'ollama is not running' })])
    s.start()
    await settle()
    expect(
      screen.getByText(
        'Waiting for the extractor: ollama is not running. Change it in Settings, or retry with the other extractor.'
      )
    ).toBeInTheDocument()
    expect(screen.queryByText(/Still extracting/)).toBeNull()
    expect(screen.getByLabelText('Chapter')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled()
    expect(screen.getByLabelText('Extractor')).toBeEnabled()
    fireEvent.change(screen.getByLabelText('Extractor'), { target: { value: 'ollama' } })
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await settle()
    expect(s.retryCapture).toHaveBeenCalledWith('c1', 'ollama')
  })

  it('a pending capture without an error offers no Retry', async () => {
    const s = setup([capture('c1', 'pending', { image_file: 'c1.jpg' })])
    s.start()
    await settle()
    expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull()
  })

  it('a failed capture shows its error on the page, not only in a tooltip', async () => {
    const s = setup([capture('f1', 'failed', { error: 'tesseract found no highlights' })])
    s.start()
    await settle()
    expect(screen.getByText(/tesseract found no highlights/)).toBeVisible()
  })

  it('is read-only while the batch is pushing', async () => {
    const s = setup([ready()], {}, { status: 'pushing' })
    s.start()
    await settle()
    expect(screen.getByLabelText('Chapter')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled()
  })
})

describe('ReviewEditor actions', () => {
  it('approve flushes pending edits before patching status', async () => {
    const s = setup([ready(), ready('c2')])
    s.start()
    await settle()
    type('Chapter', 'Edited')
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await settle()
    expect(s.patchCapture.mock.calls.map((c) => c[1])).toEqual([{ chapter: 'Edited' }, { status: 'approved' }])
    expect(screen.getByText('2 of 2')).toBeInTheDocument()
  })

  it('approving the last capture returns to the grid', async () => {
    const s = setup([ready()])
    s.start()
    await settle()
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await settle()
    expect(s.onBack).toHaveBeenCalled()
  })

  it('shows the not_approvable message on 422', async () => {
    const s = setup([ready()])
    s.patchCapture.mockRejectedValueOnce(new ApiError(422, 'not_approvable', 'server words'))
    s.start()
    await settle()
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await settle()
    expect(screen.getByRole('alert')).toHaveTextContent('Add highlight text and choose a book before approving.')
    expect(s.onBack).not.toHaveBeenCalled()
  })

  it('an approved capture offers Unapprove, which patches ready', async () => {
    const s = setup([capture('c1', 'approved', { highlights: [hl('h1', 'x')] })])
    s.start()
    await settle()
    fireEvent.click(screen.getByRole('button', { name: 'Unapprove' }))
    await settle()
    expect(s.patchCapture).toHaveBeenCalledWith('c1', { status: 'ready' })
    expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument()
  })

  it('discard asks for confirmation, then patches discarded and moves on', async () => {
    const s = setup([ready(), ready('c2')])
    s.start()
    await settle()
    fireEvent.click(screen.getByRole('button', { name: 'Discard' }))
    expect(s.patchCapture).not.toHaveBeenCalled()
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /discard/i }))
    await settle()
    expect(s.patchCapture).toHaveBeenCalledWith('c1', { status: 'discarded' })
    expect(screen.getByText('1 of 1')).toBeInTheDocument()
  })

  it('retry is visible only for failed captures and passes the chosen extractor', async () => {
    const s = setup([ready(), capture('f1', 'failed', { error: 'boom' })])
    s.start()
    await settle()
    expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull()
    ARROW('ArrowRight')
    await settle()
    fireEvent.change(screen.getByLabelText('Extractor'), { target: { value: 'ollama' } })
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await settle()
    expect(s.retryCapture).toHaveBeenCalledWith('f1', 'ollama')
    expect(screen.getByText(/Still extracting/)).toBeInTheDocument()
  })

  it('rotate patches rotation +90 mod 360 and offers Re-run extraction', async () => {
    const s = setup([capture('f1', 'failed', { rotation: 270, error: 'boom' })])
    s.start()
    await settle()
    expect(screen.queryByRole('button', { name: 'Re-run extraction' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /Rotate/ }))
    await settle()
    expect(s.patchCapture).toHaveBeenCalledWith('f1', { rotation: 0 })
    expect(screen.getByAltText(/photo/i)).toHaveAttribute('src', expect.stringContaining('&v=0'))
    fireEvent.click(screen.getByRole('button', { name: 'Re-run extraction' }))
    await settle()
    expect(s.retryCapture).toHaveBeenCalledWith('f1', 'tesseract')
  })

  it('rotating a ready capture only changes the view and says so', async () => {
    const s = setup([ready()])
    s.start()
    await settle()
    fireEvent.click(screen.getByRole('button', { name: /Rotate/ }))
    await settle()
    expect(s.patchCapture).toHaveBeenCalledWith('c1', { rotation: 90 })
    expect(screen.getByText('Rotation changes the photo view only; highlights already extracted are unchanged.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Re-run extraction' })).toBeNull()
  })
})

describe('ReviewEditor errors', () => {
  const failApprove = async (err: ApiError) => {
    const s = setup([ready()])
    s.patchCapture.mockRejectedValueOnce(err)
    s.start()
    await settle()
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await settle()
    return s
  }

  it('409 batch_pushing', async () => {
    const s = setup([ready()])
    s.patchCapture.mockRejectedValueOnce(new ApiError(409, 'batch_pushing', 'x'))
    const open = s.getBatch.getMockImplementation()!
    s.start()
    await settle()
    // The push starts after the page loaded; the 409 is how the editor finds out.
    s.getBatch.mockImplementation(async () => ({ ...(await open()), status: 'pushing' as const }))
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await settle()
    expect(screen.getByRole('alert')).toHaveTextContent('A push is running for this batch; try again when it finishes.')
    expect(screen.getByLabelText('Chapter')).toBeDisabled()
  })

  it('409 invalid_transition shows the server message and re-fetches', async () => {
    const s = setup([ready()])
    s.patchCapture.mockRejectedValueOnce(new ApiError(409, 'invalid_transition', 'cannot change status from failed to approved'))
    s.start()
    await settle()
    const before = s.getBatch.mock.calls.length
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await settle()
    expect(screen.getByRole('alert')).toHaveTextContent('cannot change status from failed to approved')
    expect(s.getBatch.mock.calls.length).toBeGreaterThan(before)
  })

  it('404 says the capture is gone with a Back button', async () => {
    const s = await failApprove(new ApiError(404, 'capture_not_found', 'capture not found'))
    expect(screen.getByRole('alert')).toHaveTextContent('This capture no longer exists.')
    fireEvent.click(screen.getByRole('button', { name: /back/i }))
    await settle()
    expect(s.onBack).toHaveBeenCalled()
  })

  it('network_error', async () => {
    await failApprove(new ApiError(0, 'network_error', 'could not reach the Note Taker backend'))
    expect(screen.getByRole('alert')).toHaveTextContent("Can't reach the backend.")
  })

  it('other errors show the message as plain text', async () => {
    await failApprove(new ApiError(500, 'boom', '<b>oops</b>'))
    expect(screen.getByRole('alert')).toHaveTextContent('<b>oops</b>')
  })

  it('a missing batch shows the gone message', async () => {
    const s = setup([ready()], { getBatch: vi.fn().mockRejectedValue(new ApiError(404, 'batch_not_found', 'nope')) })
    s.start()
    await settle()
    expect(screen.getByRole('alert')).toHaveTextContent('This capture no longer exists.')
  })
})

describe('ReviewEditor navigation', () => {
  it('next/prev navigation skips pushed captures', async () => {
    const s = setup([
      ready('c1', { chapter: 'one' }),
      capture('c2', 'pushed'),
      ready('c3', { chapter: 'three' })
    ])
    s.start()
    await settle()
    expect(screen.getByText('1 of 2')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await settle()
    expect(screen.getByText('2 of 2')).toBeInTheDocument()
    expect(screen.getByLabelText('Chapter')).toHaveValue('three')
    fireEvent.click(screen.getByRole('button', { name: 'Previous' }))
    await settle()
    expect(screen.getByLabelText('Chapter')).toHaveValue('one')
  })

  it('a pushed target index moves to the nearest reviewable capture', async () => {
    const s = setup([capture('c1', 'pushed'), ready('c2', { chapter: 'two' })])
    s.start(0)
    await settle()
    expect(screen.getByLabelText('Chapter')).toHaveValue('two')
  })

  it('flushes pending edits before navigating, and stays put if that fails', async () => {
    const s = setup([ready('c1'), ready('c2', { chapter: 'two' })])
    s.start()
    await settle()
    type('Chapter', 'edited')
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await settle()
    expect(s.patchCapture).toHaveBeenCalledWith('c1', { chapter: 'edited' })
    expect(screen.getByLabelText('Chapter')).toHaveValue('two')

    s.patchCapture.mockRejectedValueOnce(new ApiError(500, 'boom', 'down'))
    type('Chapter', 'unsaved')
    fireEvent.click(screen.getByRole('button', { name: 'Previous' }))
    await settle()
    expect(screen.getByLabelText('Chapter')).toHaveValue('unsaved')
    expect(screen.getByText('2 of 2')).toBeInTheDocument()
  })

  it('flushes pending edits on unmount without touching state afterwards', async () => {
    const s = setup([ready()])
    const view = s.start()
    await settle()
    type('Chapter', 'bye')
    view.unmount()
    await settle()
    expect(s.patchCapture).toHaveBeenCalledWith('c1', { chapter: 'bye' })
  })

  it("a late response for capture A never touches capture B", async () => {
    const s = setup([ready('A', { chapter: 'a' }), ready('B', { chapter: 'b' })])
    let emit!: (e: unknown) => void
    s.client.subscribe.mockImplementation(((_id: string, cb: (e: unknown) => void) => { emit = cb; return vi.fn() }) as never)
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    const original = s.patchCapture.getMockImplementation()!
    s.patchCapture.mockImplementationOnce(async (id, body) => { await gate; return original(id, body) })
    s.start()
    await settle()
    type('Chapter', 'A edited')
    await settle(600)
    // A is pushed from under us: the editor moves to B while A's PATCH is still in flight.
    s.live[0].status = 'pushed'
    emit({ type: 'capture.status_changed', data: { capture_id: 'A', status: 'pushed', error: null } })
    await settle(250)
    expect(screen.getByLabelText('Chapter')).toHaveValue('b')
    release()
    await settle()
    expect(screen.getByLabelText('Chapter')).toHaveValue('b')
    expect(screen.getByText('1 of 1')).toBeInTheDocument()
  })
})

describe('ReviewEditor keyboard', () => {
  it('arrow keys navigate when focus is not in a field', async () => {
    const s = setup([ready('c1', { chapter: 'one' }), ready('c2', { chapter: 'two' })])
    s.start()
    await settle()
    ARROW('ArrowRight')
    await settle()
    expect(screen.getByLabelText('Chapter')).toHaveValue('two')
    ARROW('ArrowLeft')
    await settle()
    expect(screen.getByLabelText('Chapter')).toHaveValue('one')
  })

  it('arrow keys do nothing inside a textarea', async () => {
    const s = setup([ready('c1'), ready('c2', { chapter: 'two' })])
    s.start()
    await settle()
    const area = screen.getAllByLabelText('Highlight text')[0]
    area.focus()
    ARROW('ArrowRight', area)
    await settle()
    expect(screen.getByLabelText('Chapter')).toHaveValue('One')
  })

  it('Cmd+Enter approves and moves on, even from a text field', async () => {
    const s = setup([ready('c1'), ready('c2', { chapter: 'two' })])
    s.start()
    await settle()
    const area = screen.getAllByLabelText('Highlight text')[0]
    area.focus()
    type('Highlight text', 'changed', 0)
    fireEvent.keyDown(area, { key: 'Enter', metaKey: true })
    await settle()
    expect(s.patchCapture.mock.calls.map((c) => c[1])).toEqual([
      { highlights: [{ id: 'h1', text: 'changed', note: null }, { id: 'h2', text: 'second', note: 'my note' }] },
      { status: 'approved' }
    ])
    expect(screen.getByLabelText('Chapter')).toHaveValue('two')
  })

  it('shortcuts are disabled while the discard dialog is open', async () => {
    const s = setup([ready('c1', { chapter: 'one' }), ready('c2', { chapter: 'two' })])
    s.start()
    await settle()
    fireEvent.click(screen.getByRole('button', { name: 'Discard' }))
    ARROW('ArrowRight')
    fireEvent.keyDown(document.body, { key: 'Enter', metaKey: true })
    await settle()
    expect(s.patchCapture).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Chapter')).toHaveValue('one')
  })
})
