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
})
