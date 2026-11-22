import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import BatchList from '../src/screens/BatchList'
import { ApiError } from '../src/api/types'
import { batch, book, fakeClient, renderWith, summary } from './helpers'

const noop = () => {}
const list = (client: ReturnType<typeof fakeClient>['client'], over = {}) =>
  renderWith(client, <BatchList onOpenBatch={noop} onSettings={noop} {...over} />)

describe('BatchList', () => {
  it('shows expiry banner when a batch is expiring_soon', async () => {
    const { client } = fakeClient({
      listBatches: vi.fn().mockResolvedValue([
        summary('a', { expiring_soon: true }),
        summary('b', { expiring_soon: true }),
        summary('c')
      ])
    })
    list(client)
    const banner = await screen.findByRole('alert', { name: /expir/i })
    expect(banner).toHaveTextContent(/2 batches will be deleted soon: .+\. Resume or discard them\./)
  })

  it('shows no expiry banner when nothing is expiring', async () => {
    const { client } = fakeClient({ listBatches: vi.fn().mockResolvedValue([summary('a')]) })
    list(client)
    await screen.findByRole('button', { name: /resume/i })
    expect(screen.queryByText(/deleted soon/)).toBeNull()
  })

  it('discard asks for confirmation then deletes', async () => {
    const { client } = fakeClient({
      listBatches: vi.fn().mockResolvedValueOnce([summary('a')]).mockResolvedValue([])
    })
    list(client)
    fireEvent.click(await screen.findByRole('button', { name: /discard/i }))
    expect(client.deleteBatch).not.toHaveBeenCalled()
    const dialog = screen.getByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: /^discard$/i }))
    await waitFor(() => expect(client.deleteBatch).toHaveBeenCalledWith('a'))
    await waitFor(() => expect(screen.queryByRole('button', { name: /resume/i })).toBeNull())
  })

  it('Escape in the confirm dialog cancels without deleting', async () => {
    const { client } = fakeClient({ listBatches: vi.fn().mockResolvedValue([summary('a')]) })
    list(client)
    fireEvent.click(await screen.findByRole('button', { name: /discard/i }))
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(client.deleteBatch).not.toHaveBeenCalled()
  })

  it('shows created date, default book title, counts and expiry', async () => {
    const { client } = fakeClient({
      listBooks: vi.fn().mockResolvedValue([book('dune', 'Dune')]),
      listBatches: vi.fn().mockResolvedValue([
        summary('a', { default_book_slug: 'dune', counts: { ...summary('x').counts, ready: 3, approved: 2 } })
      ])
    })
    list(client)
    expect(await screen.findByText('Dune')).toBeInTheDocument()
    expect(screen.getByText(/3 ready/)).toBeInTheDocument()
    expect(screen.getByText(/2 approved/)).toBeInTheDocument()
    expect(screen.getByText(new Date('2026-11-08T10:00:00Z').toLocaleString(), { exact: false })).toBeInTheDocument()
    expect(screen.getByText(new Date('2026-12-08T10:00:00Z').toLocaleString(), { exact: false })).toBeInTheDocument()
  })

  it('Resume opens the batch', async () => {
    const onOpenBatch = vi.fn()
    const { client } = fakeClient({ listBatches: vi.fn().mockResolvedValue([summary('a')]) })
    list(client, { onOpenBatch })
    fireEvent.click(await screen.findByRole('button', { name: /resume/i }))
    expect(onOpenBatch).toHaveBeenCalledWith('a')
  })

  it('New batch creates one and opens it', async () => {
    const onOpenBatch = vi.fn()
    const { client } = fakeClient({ createBatch: vi.fn().mockResolvedValue(batch([], { id: 'new1' })) })
    list(client, { onOpenBatch })
    fireEvent.click(await screen.findByRole('button', { name: /new batch/i }))
    await waitFor(() => expect(onOpenBatch).toHaveBeenCalledWith('new1'))
  })

  it('links to Settings and warns when the repo is not connected', async () => {
    const onSettings = vi.fn()
    const { client } = fakeClient({
      getHealth: vi.fn().mockResolvedValue({
        extractor: { kind: 'tesseract', ok: true, detail: '' },
        repo: { cloned: false, dirty: null, path: '/x' },
        remote: { ok: true, detail: '' }
      })
    })
    list(client, { onSettings })
    const banner = await screen.findByText(/notes repo is not connected/i)
    fireEvent.click(within(banner.closest('[role="status"]') as HTMLElement).getByRole('button', { name: /settings/i }))
    expect(onSettings).toHaveBeenCalled()
  })

  it('renders backend text as literal text, never markup', async () => {
    const evil = '<img src=x onerror=alert(1)>'
    const { client } = fakeClient({
      listBooks: vi.fn().mockResolvedValue([book('evil', evil)]),
      listBatches: vi.fn().mockResolvedValue([summary('a', { default_book_slug: 'evil' })]),
      createBatch: vi.fn().mockRejectedValue(new ApiError(500, 'x', evil))
    })
    const { container } = list(client)
    expect(await screen.findByText(evil)).toBeInTheDocument()
    expect(container.querySelector('img')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /new batch/i }))
    await waitFor(() => expect(screen.getAllByText(evil)).toHaveLength(2))
    expect(container.querySelector('img')).toBeNull()
  })

  it('shows batches even when books and health never answer', async () => {
    const { client } = fakeClient({
      listBatches: vi.fn().mockResolvedValue([summary('a')]),
      listBooks: vi.fn(() => new Promise(() => {})),
      getHealth: vi.fn(() => new Promise(() => {}))
    })
    list(client)
    expect(await screen.findByRole('button', { name: /resume/i })).toBeInTheDocument()
  })

  it('shows batches and separate non-blocking notices when books and health fail', async () => {
    const { client } = fakeClient({
      listBatches: vi.fn().mockResolvedValue([summary('a')]),
      listBooks: vi.fn().mockRejectedValue(new ApiError(0, 'network_error', 'books down')),
      getHealth: vi.fn().mockRejectedValue(new ApiError(0, 'network_error', 'health down'))
    })
    list(client)
    expect(await screen.findByRole('button', { name: /resume/i })).toBeInTheDocument()
    expect(await screen.findByText(/could not load books: books down/i)).toBeInTheDocument()
    expect(await screen.findByText(/could not check the notes repo: health down/i)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  describe('discard failures', () => {
    async function discardFirst(client: ReturnType<typeof fakeClient>['client']) {
      list(client)
      fireEvent.click(await screen.findByRole('button', { name: /discard/i }))
      fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /^discard$/i }))
    }

    it('a failed delete reloads the list and keeps the error visible', async () => {
      const { client } = fakeClient({
        listBatches: vi.fn().mockResolvedValue([summary('a')]),
        deleteBatch: vi.fn().mockRejectedValue(new ApiError(500, 'boom', 'disk full'))
      })
      await discardFirst(client)
      expect(await screen.findByRole('alert')).toHaveTextContent(
        "Couldn't discard the batch: disk full. The list has been refreshed."
      )
      await waitFor(() => expect(client.listBatches).toHaveBeenCalledTimes(2))
      // The reload must not wipe the message it was triggered to accompany.
      expect(screen.getByRole('alert')).toHaveTextContent(/Couldn't discard the batch/)
      expect(screen.getByRole('button', { name: /resume/i })).toBeInTheDocument()
    })

    it('a 404 on delete means it is already gone: no error, list reloaded', async () => {
      const { client } = fakeClient({
        listBatches: vi.fn().mockResolvedValueOnce([summary('a')]).mockResolvedValue([]),
        deleteBatch: vi.fn().mockRejectedValue(new ApiError(404, 'batch_not_found', 'no such batch'))
      })
      await discardFirst(client)
      await waitFor(() => expect(client.listBatches).toHaveBeenCalledTimes(2))
      await waitFor(() => expect(screen.queryByRole('button', { name: /resume/i })).toBeNull())
      expect(screen.queryByRole('alert')).toBeNull()
    })

    it('success clears an earlier error and moves focus to the heading', async () => {
      const { client } = fakeClient({
        listBatches: vi.fn().mockResolvedValueOnce([summary('a'), summary('b')]).mockResolvedValue([summary('b')]),
        createBatch: vi.fn().mockRejectedValue(new ApiError(500, 'x', 'earlier failure'))
      })
      list(client)
      fireEvent.click(await screen.findByRole('button', { name: /new batch/i }))
      expect(await screen.findByRole('alert')).toHaveTextContent('earlier failure')
      fireEvent.click(screen.getAllByRole('button', { name: /discard/i })[0])
      fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /^discard$/i }))
      await waitFor(() => expect(screen.getAllByRole('button', { name: /resume/i })).toHaveLength(1))
      expect(screen.queryByRole('alert')).toBeNull()
      expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Note Taker' }))
    })
  })
})
