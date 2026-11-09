import { useCallback, useEffect, useState } from 'react'
import { useApi } from '../api/context'
import type { BatchSummary, Book, Health } from '../api/types'
import ConfirmDialog from '../components/ConfirmDialog'
import ExpiryBanner from '../components/ExpiryBanner'
import { errorMessage, formatDate } from '../format'

interface Props {
  onOpenBatch: (batchId: string) => void
  onSettings: () => void
}

export default function BatchList({ onOpenBatch, onSettings }: Props) {
  const api = useApi()
  const [batches, setBatches] = useState<BatchSummary[] | null>(null)
  const [books, setBooks] = useState<Book[]>([])
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [discarding, setDiscarding] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      const [b, bk, h] = await Promise.all([api.listBatches(), api.listBooks(), api.getHealth()])
      setBatches(b)
      setBooks(bk)
      setHealth(h)
    } catch (e) {
      setError(errorMessage(e))
    }
  }, [api])
  useEffect(() => {
    void reload()
  }, [reload])

  async function newBatch() {
    try {
      onOpenBatch((await api.createBatch()).id)
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  async function confirmDiscard() {
    const id = discarding
    setDiscarding(null)
    if (!id) return
    try {
      await api.deleteBatch(id)
      setError(null)
      await reload()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  const title = (slug: string | null) =>
    slug ? (books.find((b) => b.slug === slug)?.title ?? slug) : 'No default book'

  return (
    <main className="screen">
      <header className="row between">
        <h1>Note Taker</h1>
        <div className="row">
          <button onClick={() => void newBatch()}>New batch</button>
          <button onClick={onSettings}>Settings</button>
        </div>
      </header>
      {health && !health.repo.cloned && (
        <div role="status" className="banner">
          Your notes repo is not connected.{' '}
          <button className="link" onClick={onSettings}>Open Settings</button>
        </div>
      )}
      {batches && <ExpiryBanner batches={batches} />}
      {error && <p role="alert" className="error">{error}</p>}
      {batches?.length === 0 && <p>No open batches. Start a new one to add photos.</p>}
      <ul className="batches">
        {batches?.map((b) => (
          <li key={b.id} className="batch">
            <div>
              <strong>{title(b.default_book_slug)}</strong>
              <div>Created {formatDate(b.created_at)}</div>
              <div>Expires {formatDate(b.expires_at)}</div>
              <div>
                {(Object.entries(b.counts) as [string, number][])
                  .filter(([, n]) => n > 0)
                  .map(([s, n]) => `${n} ${s}`)
                  .join(', ') || 'Empty'}
              </div>
            </div>
            <div className="row">
              <button onClick={() => onOpenBatch(b.id)}>Resume</button>
              <button className="danger" onClick={() => setDiscarding(b.id)}>Discard</button>
            </div>
          </li>
        ))}
      </ul>
      {discarding && (
        <ConfirmDialog
          title="Discard batch?"
          message="This deletes the batch and its photos. Notes already pushed are not affected."
          confirmLabel="Discard"
          onConfirm={() => void confirmDiscard()}
          onCancel={() => setDiscarding(null)}
        />
      )}
    </main>
  )
}
