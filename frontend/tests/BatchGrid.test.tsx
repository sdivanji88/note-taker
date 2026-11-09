import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import BatchGrid from '../src/screens/BatchGrid'
import { ApiError, type CaptureStatus } from '../src/api/types'
import { batch, capture, fakeClient, renderWith } from './helpers'

const grid = (client: ReturnType<typeof fakeClient>['client'], over = {}) =>
  renderWith(client, <BatchGrid batchId="b1" onOpenReview={() => {}} onBack={() => {}} {...over} />)

const png = (name = 'a.png', type = 'image/png') => new File(['x'], name, { type })
const pickFiles = (files: File[]) =>
  fireEvent.change(screen.getByLabelText(/photo files/i), { target: { files } })

describe('BatchGrid', () => {
  it('grid renders badge per capture status', async () => {
    const statuses: CaptureStatus[] = ['pending', 'extracting', 'ready', 'failed', 'approved', 'discarded', 'pushed']
    const { client } = fakeClient({
      getBatch: vi.fn().mockResolvedValue(
        batch(
          statuses.map((s) =>
            capture(s, s, { error: s === 'failed' ? 'ollama timed out' : s === 'pending' ? 'ollama is not running' : null })
          )
        )
      )
    })
    grid(client)
    for (const s of ['pending', 'extracting', 'ready', 'failed', 'approved', 'discarded']) {
      const item = await screen.findByTestId(`thumb-${s}`)
      expect(within(item).getByText(s, { selector: '.sr-only' })).toBeInTheDocument()
    }
    expect(screen.queryByTestId('thumb-pushed')).toBeNull()
    expect(screen.getByTestId('thumb-discarded')).toHaveClass('faded')
    expect(within(screen.getByTestId('thumb-failed')).getByTitle('ollama timed out')).toBeInTheDocument()
    expect(within(screen.getByTestId('thumb-pending')).getByTitle('ollama is not running')).toBeInTheDocument()
  })

  it('uploading files calls uploadPhotos and shows rejected reasons', async () => {
    const created = capture('n1', 'pending')
    const { client } = fakeClient({
      uploadPhotos: vi.fn().mockResolvedValue({
        created: [created],
        rejected: [
          { filename: 'dup.jpg', reason: 'duplicate' },
          { filename: 'big.jpg', reason: 'too_large' },
          { filename: 'bad.bin', reason: 'unsupported_type' },
          { filename: 'many.jpg', reason: 'too_many_files' },
          { filename: 'odd.jpg', reason: 'weird <b>reason</b>' }
        ]
      }),
      getBatch: vi.fn().mockResolvedValueOnce(batch()).mockResolvedValue(batch([created]))
    })
    grid(client)
    await screen.findByLabelText(/photo files/i)
    const f = png('a.png')
    pickFiles([f])
    await waitFor(() => expect(client.uploadPhotos).toHaveBeenCalledWith('b1', [f]))
    expect(await screen.findByText(/dup\.jpg.*already in this batch/)).toBeInTheDocument()
    expect(screen.getByText(/big\.jpg.*larger than 25 MB/)).toBeInTheDocument()
    expect(screen.getByText(/bad\.bin.*not a PNG or JPEG/)).toBeInTheDocument()
    expect(screen.getByText(/many\.jpg.*more than 100 files at once/)).toBeInTheDocument()
    expect(screen.getByText(/odd\.jpg.*weird <b>reason<\/b>/)).toBeInTheDocument()
    // The created capture is kept even though others were rejected.
    expect(await screen.findByTestId('thumb-n1')).toBeInTheDocument()
  })

  it('skips dropped non-image files client-side and lists them', async () => {
    const { client } = fakeClient()
    grid(client)
    const zone = await screen.findByRole('button', { name: /drop photos/i })
    const good = png('ok.jpg', 'image/jpeg')
    fireEvent.drop(zone, { dataTransfer: { files: [good, new File(['x'], 'notes.pdf', { type: 'application/pdf' })] } })
    await waitFor(() => expect(client.uploadPhotos).toHaveBeenCalledWith('b1', [good]))
    expect(await screen.findByText(/notes\.pdf.*not a PNG or JPEG/)).toBeInTheDocument()
  })

  it('does not call uploadPhotos when every dropped file is skipped', async () => {
    const { client } = fakeClient()
    grid(client)
    const zone = await screen.findByRole('button', { name: /drop photos/i })
    fireEvent.drop(zone, { dataTransfer: { files: [new File(['x'], 'a.gif', { type: 'image/gif' })] } })
    expect(await screen.findByText(/a\.gif.*not a PNG or JPEG/)).toBeInTheDocument()
    expect(client.uploadPhotos).not.toHaveBeenCalled()
  })

  it('drop zone opens the file picker with Enter and Space', async () => {
    const { client } = fakeClient()
    grid(client)
    const zone = await screen.findByRole('button', { name: /drop photos/i })
    const click = vi.spyOn(screen.getByLabelText(/photo files/i) as HTMLInputElement, 'click')
    fireEvent.keyDown(zone, { key: 'Enter' })
    fireEvent.keyDown(zone, { key: ' ' })
    expect(click).toHaveBeenCalledTimes(2)
    expect(screen.getByLabelText(/photo files/i)).toHaveAttribute('accept', 'image/png,image/jpeg')
  })

  it('push button disabled with zero approved and shows dirty-repo message on 409', async () => {
    const { client } = fakeClient({
      getBatch: vi.fn().mockResolvedValue(batch([capture('c1', 'approved')])),
      push: vi.fn().mockRejectedValue(new ApiError(409, 'dirty_repo', 'raw server text'))
    })
    const view = grid(client)
    fireEvent.click(await screen.findByRole('button', { name: 'Push all approved (1)' }))
    expect(await screen.findByText('Your notes repo has uncommitted changes. Commit or stash them, then push again.')).toBeInTheDocument()
    view.unmount()

    const empty = fakeClient({ getBatch: vi.fn().mockResolvedValue(batch([capture('c1', 'ready')])) })
    grid(empty.client)
    expect(await screen.findByRole('button', { name: 'Push all approved (0)' })).toBeDisabled()
  })

  it.each([
    [409, 'not_cloned', 'x', 'Connect your notes repo in Settings first.'],
    [409, 'wrong_branch', 'the notes clone is on wip; check out main', 'Your notes clone is on a different branch than the one in Settings: the notes clone is on wip; check out main'],
    [409, 'remote_mismatch', 'origin differs', "Your notes clone's origin is not the remote in Settings: origin differs"],
    [422, 'unknown_book', 'x', 'Choose a book for every approved capture before pushing.'],
    [502, 'git_failed', 'remote: <i>denied</i>', 'remote: <i>denied</i>'],
    [500, 'other', 'something broke', 'something broke']
  ])('maps push error %s %s to its message', async (status, code, serverMsg, expected) => {
    const { client } = fakeClient({
      getBatch: vi.fn().mockResolvedValue(batch([capture('c1', 'approved')])),
      push: vi.fn().mockRejectedValue(new ApiError(status, code, serverMsg))
    })
    grid(client)
    fireEvent.click(await screen.findByRole('button', { name: /push all approved/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(expected)
  })

  it('shows the push summary on success', async () => {
    const { client } = fakeClient({
      getBatch: vi.fn().mockResolvedValue(batch([capture('c1', 'approved')])),
      push: vi.fn().mockResolvedValue({ commit_sha: 'abc1234def', files_changed: ['books/dune.md'], highlights_written: 4, batch_deleted: true })
    })
    grid(client)
    fireEvent.click(await screen.findByRole('button', { name: /push all approved/i }))
    const status = await screen.findByRole('status', { name: /push result/i })
    expect(status).toHaveTextContent(/4 highlights/)
    expect(status).toHaveTextContent('books/dune.md')
    expect(status).toHaveTextContent('abc1234')
  })

  it('a push in flight disables the button and mutating actions and cannot be double-submitted', async () => {
    let resolve!: (v: unknown) => void
    const { client } = fakeClient({
      getBatch: vi.fn().mockResolvedValue(batch([capture('c1', 'approved')])),
      push: vi.fn(() => new Promise((r) => (resolve = r)))
    })
    grid(client)
    const btn = await screen.findByRole('button', { name: /push all approved/i })
    fireEvent.click(btn)
    fireEvent.click(btn)
    expect(client.push).toHaveBeenCalledTimes(1)
    expect(btn).toBeDisabled()
    expect(screen.getByRole('button', { name: /add kindle highlight/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /remove selected/i })).toBeDisabled()
    expect(screen.getByLabelText(/photo files/i)).toBeDisabled()
    await act(async () => resolve({ commit_sha: 'abc1234', files_changed: [], highlights_written: 0, batch_deleted: true }))
  })

  it('refetches once for a burst of live events and unsubscribes on unmount', async () => {
    const { client, emit, unsubscribe } = fakeClient()
    const view = grid(client)
    await screen.findByLabelText(/photo files/i)
    expect(client.getBatch).toHaveBeenCalledTimes(1)
    emit(); emit(); emit()
    await waitFor(() => expect(client.getBatch).toHaveBeenCalledTimes(2))
    await new Promise((r) => setTimeout(r, 400))
    expect(client.getBatch).toHaveBeenCalledTimes(2)
    view.unmount()
    expect(unsubscribe).toHaveBeenCalled()
  })

  it('does not refetch after unmount even if an event was pending', async () => {
    const { client, emit } = fakeClient()
    const view = grid(client)
    await screen.findByLabelText(/photo files/i)
    emit()
    view.unmount()
    await new Promise((r) => setTimeout(r, 400))
    expect(client.getBatch).toHaveBeenCalledTimes(1)
  })

  it('resubscribes when batchId changes and Refresh refetches', async () => {
    const { client, unsubscribe } = fakeClient()
    const view = grid(client)
    await screen.findByLabelText(/photo files/i)
    fireEvent.click(screen.getByRole('button', { name: /refresh/i }))
    await waitFor(() => expect(client.getBatch).toHaveBeenCalledTimes(2))
    view.rerender(<></>)
    expect(unsubscribe).toHaveBeenCalled()
  })

  it('extracting capture is not openable and Review starts at the first reviewable one', async () => {
    const onOpenReview = vi.fn()
    const { client } = fakeClient({
      getBatch: vi.fn().mockResolvedValue(
        batch([capture('e1', 'extracting'), capture('p1', 'pending'), capture('r1', 'ready'), capture('r2', 'ready')])
      )
    })
    grid(client, { onOpenReview })
    const open = await within(await screen.findByTestId('thumb-e1')).findByRole('button', { name: /open/i })
    expect(open).toBeDisabled()
    expect(open).toHaveAttribute('title', 'Still extracting…')
    fireEvent.click(open)
    expect(onOpenReview).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /^review/i }))
    expect(onOpenReview).toHaveBeenCalledWith(2)
    fireEvent.click(within(screen.getByTestId('thumb-r2')).getByRole('button', { name: /open/i }))
    expect(onOpenReview).toHaveBeenLastCalledWith(3)
  })

  it('Remove selected deletes the chosen captures and refetches', async () => {
    const { client } = fakeClient({
      getBatch: vi.fn().mockResolvedValue(batch([capture('r1', 'ready'), capture('r2', 'ready')]))
    })
    grid(client)
    const t = await screen.findByTestId('thumb-r1')
    fireEvent.click(within(t).getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: /remove selected/i }))
    await waitFor(() => expect(client.deleteCapture).toHaveBeenCalledWith('r1'))
    expect(client.deleteCapture).toHaveBeenCalledTimes(1)
  })

  it('Add Kindle highlight adds one empty highlight and opens review at its index', async () => {
    const onOpenReview = vi.fn()
    const k = capture('k1', 'ready', { source: 'kindle', image_file: null })
    const { client } = fakeClient({
      getBatch: vi.fn().mockResolvedValueOnce(batch([capture('r1', 'ready')])).mockResolvedValue(batch([capture('r1', 'ready'), k])),
      addKindle: vi.fn().mockResolvedValue(k)
    })
    grid(client, { onOpenReview })
    fireEvent.click(await screen.findByRole('button', { name: /add kindle highlight/i }))
    await waitFor(() => expect(onOpenReview).toHaveBeenCalledWith(1))
    expect(client.addKindle).toHaveBeenCalledWith('b1', { source: 'kindle', highlights: [{ text: '' }], book_slug: null })
  })

  it('Book for all patches the batch default book', async () => {
    const { client } = fakeClient({
      listBooks: vi.fn().mockResolvedValue([{ slug: 'dune', title: 'Dune', author: null, kind: 'fiction', pending: true }])
    })
    grid(client)
    const select = await screen.findByLabelText(/book for all/i)
    await screen.findByRole('option', { name: 'Dune (new)' })
    fireEvent.change(select, { target: { value: 'dune' } })
    await waitFor(() => expect(client.patchBatch).toHaveBeenCalledWith('b1', { default_book_slug: 'dune' }))
  })

  it('shows a load error and renders backend text literally', async () => {
    const evil = '<img src=x onerror=alert(1)>'
    const { client } = fakeClient({ getBatch: vi.fn().mockRejectedValue(new ApiError(404, 'not_found', evil)) })
    const { container } = grid(client)
    expect(await screen.findByText(evil)).toBeInTheDocument()
    expect(container.querySelector('img')).toBeNull()
  })

  it('failed-capture error text with markup stays literal in the tooltip and thumbnail has alt text', async () => {
    const evil = '<img src=x onerror=alert(1)>'
    const { client } = fakeClient({
      getBatch: vi.fn().mockResolvedValue(batch([capture('f1', 'failed', { error: evil, page: 12 })]))
    })
    const { container } = grid(client)
    const t = await screen.findByTestId('thumb-f1')
    expect(within(t).getByTitle(evil)).toBeInTheDocument()
    expect(within(t).getByAltText(/page 12/i)).toBeInTheDocument()
    expect(container.querySelectorAll('img')).toHaveLength(1)
  })
})
