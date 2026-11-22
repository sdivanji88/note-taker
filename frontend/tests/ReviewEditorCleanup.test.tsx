import { act, fireEvent, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../src/api/types'
import { capture } from './helpers'
import { hl, ready, settle, setup, type } from './reviewSetup'

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

// "Add Kindle highlight" creates the capture up front; leaving it untouched must not
// strand an empty entry in the batch. Photo captures are never cleaned up this way.
const blankKindle = (id = 'k1', extra = {}) =>
  capture(id, 'ready', { source: 'kindle', image_file: null, highlights: [hl('h1', '')], ...extra })
const backBtn = () => screen.getByRole('button', { name: /back to batch/i })

describe('leaving an untouched Kindle capture', () => {
  it('Back deletes it before going back', async () => {
    const s = setup([blankKindle()])
    s.start()
    await settle()
    fireEvent.click(backBtn())
    await settle()
    expect(s.client.deleteCapture).toHaveBeenCalledWith('k1')
    expect(s.client.deleteCapture.mock.invocationCallOrder[0]).toBeLessThan(s.onBack.mock.invocationCallOrder[0])
  })

  it('treats whitespace-only text as blank', async () => {
    const s = setup([blankKindle('k1', { highlights: [hl('h1', '  \n ')] })])
    s.start()
    await settle()
    fireEvent.click(backBtn())
    await settle()
    expect(s.client.deleteCapture).toHaveBeenCalledWith('k1')
  })

  it('keeps it when it has highlight text', async () => {
    const s = setup([blankKindle('k1', { highlights: [hl('h1', 'a quote')] })])
    s.start()
    await settle()
    fireEvent.click(backBtn())
    await settle()
    expect(s.client.deleteCapture).not.toHaveBeenCalled()
    expect(s.onBack).toHaveBeenCalled()
  })

  it('judges what was just typed, not the stale copy: text typed then Back keeps it', async () => {
    const s = setup([blankKindle()])
    s.start()
    await settle()
    type('Highlight text', 'typed just now')
    fireEvent.click(backBtn())
    await settle()
    expect(s.patchCapture).toHaveBeenCalled()
    expect(s.client.deleteCapture).not.toHaveBeenCalled()
    expect(s.onBack).toHaveBeenCalled()
  })

  it.each([
    ['a chapter', () => type('Chapter', 'Three')],
    ['a page', () => type('Page', '7')],
    ['a margin note', () => type('My note', 'remember this')]
  ])('keeps it when only %s was entered', async (_what, enter) => {
    const s = setup([blankKindle()])
    s.start()
    await settle()
    enter()
    fireEvent.click(backBtn())
    await settle()
    expect(s.client.deleteCapture).not.toHaveBeenCalled()
    expect(s.onBack).toHaveBeenCalled()
  })

  it('never deletes a photo capture, even with no highlights', async () => {
    const s = setup([capture('p1', 'ready', { highlights: [] })])
    s.start()
    await settle()
    fireEvent.click(backBtn())
    await settle()
    expect(s.client.deleteCapture).not.toHaveBeenCalled()
    expect(s.onBack).toHaveBeenCalled()
  })

  it('still goes back when the delete fails', async () => {
    const s = setup([blankKindle()])
    s.client.deleteCapture.mockRejectedValue(new ApiError(500, 'boom', 'down'))
    s.start()
    await settle()
    fireEvent.click(backBtn())
    await settle()
    expect(s.client.deleteCapture).toHaveBeenCalled()
    expect(s.onBack).toHaveBeenCalledTimes(1)
  })

  it('does not delete when the save fails and the user is asked to confirm leaving', async () => {
    const s = setup([blankKindle()])
    s.patchCapture.mockRejectedValue(new ApiError(500, 'boom', 'down'))
    s.start()
    await settle()
    type('Chapter', 'x')
    fireEvent.click(backBtn())
    await settle()
    expect(s.client.deleteCapture).not.toHaveBeenCalled()
    expect(s.onBack).not.toHaveBeenCalled()
  })

  it('does not delete on unmount (only deliberate Back / Prev / Next do)', async () => {
    const s = setup([blankKindle()])
    const view = s.start()
    await settle()
    view.unmount()
    await settle()
    expect(s.client.deleteCapture).not.toHaveBeenCalled()
  })
})

// While the delete is in flight the pane is the one the user still sees; anything typed
// then would be lost with the capture, so it must be refused rather than silently dropped.
describe('while the blank-Kindle delete is in flight', () => {
  const pendingDelete = (s: ReturnType<typeof setup>) => {
    let finish!: (ok: boolean) => void
    s.client.deleteCapture.mockImplementation(
      () => new Promise<void>((resolve, reject) => (finish = (ok) => (ok ? resolve() : reject(new ApiError(500, 'boom', 'down')))))
    )
    return (ok: boolean) => act(async () => { finish(ok); await vi.advanceTimersByTimeAsync(0) })
  }

  it('Next makes the pane read-only until it has moved on', async () => {
    const s = setup([blankKindle('k1'), ready('c2', { chapter: 'two' })])
    const resolve = pendingDelete(s)
    s.start()
    await settle()
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await settle()
    expect(s.client.deleteCapture).toHaveBeenCalledWith('k1')
    expect(screen.getByLabelText('Chapter')).toBeDisabled()
    expect(screen.getByLabelText('Highlight text')).toBeDisabled()
    await resolve(true)
    expect(screen.getByLabelText('Chapter')).toHaveValue('two')
    expect(screen.getByLabelText('Chapter')).toBeEnabled()
  })

  it('Back makes the pane read-only, and a failed delete re-enables it before leaving', async () => {
    const s = setup([blankKindle()])
    const resolve = pendingDelete(s)
    s.start()
    await settle()
    fireEvent.click(backBtn())
    await settle()
    expect(screen.getByLabelText('Chapter')).toBeDisabled()
    expect(s.onBack).not.toHaveBeenCalled()
    await resolve(false)
    expect(s.onBack).toHaveBeenCalledTimes(1)
    expect(screen.getByLabelText('Chapter')).toBeEnabled() // the capture stays; nothing is stuck
  })

  it('a failed delete on Next un-busies the pane and still moves on', async () => {
    const s = setup([blankKindle('k1'), ready('c2', { chapter: 'two' })])
    const resolve = pendingDelete(s)
    s.start()
    await settle()
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await settle()
    expect(screen.getByLabelText('Chapter')).toBeDisabled()
    await resolve(false)
    expect(screen.getByLabelText('Chapter')).toHaveValue('two')
    expect(screen.getByLabelText('Chapter')).toBeEnabled()
  })
})

describe('stepping off an untouched Kindle capture', () => {
  it('Next deletes it, lands on the next capture and drops it from the count', async () => {
    const s = setup([blankKindle('k1'), ready('c2', { chapter: 'two' })])
    s.start()
    await settle()
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await settle()
    expect(s.client.deleteCapture).toHaveBeenCalledWith('k1')
    expect(screen.getByLabelText('Chapter')).toHaveValue('two')
    expect(screen.getByText('1 of 1')).toBeInTheDocument()
  })

  it('does not delete when there is nowhere to step to', async () => {
    const s = setup([blankKindle('k1')])
    s.start()
    await settle()
    fireEvent.keyDown(document.body, { key: 'ArrowRight' })
    await settle()
    expect(s.client.deleteCapture).not.toHaveBeenCalled()
  })

  it('keeps a failed-to-delete capture in the list and still moves on', async () => {
    const s = setup([blankKindle('k1'), ready('c2', { chapter: 'two' })])
    s.client.deleteCapture.mockRejectedValue(new ApiError(500, 'boom', 'down'))
    s.start()
    await settle()
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await settle()
    expect(screen.getByLabelText('Chapter')).toHaveValue('two')
    expect(screen.getByText('2 of 2')).toBeInTheDocument()
  })

  it('keeps a Kindle capture that has text', async () => {
    const s = setup([blankKindle('k1', { highlights: [hl('h1', 'quote')] }), ready('c2')])
    s.start()
    await settle()
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await settle()
    expect(s.client.deleteCapture).not.toHaveBeenCalled()
  })
})
