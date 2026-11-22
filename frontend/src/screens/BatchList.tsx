import { useCallback, useEffect, useRef, useState } from 'react'
import { useApi } from '../api/context'
import { ApiError, type BatchSummary, type Book, type Health } from '../api/types'
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
  const [booksError, setBooksError] = useState<string | null>(null)
  const [healthError, setHealthError] = useState<string | null>(null)
  const [discarding, setDiscarding] = useState<string | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)

  const reload = useCallback(async () => {
    // Settled independently: listBooks syncs with the remote and getHealth probes it,
    // so either can be slow or fail, and neither may hide the local batch list.
    void api.listBooks().then(
      (bk) => {
        setBooks(bk)
        setBooksError(null)
      },
      (e) => setBooksError(errorMessage(e))
    )
    void api.getHealth().then(
      (h) => {
        setHealth(h)
        setHealthError(null)
      },
      (e) => setHealthError(errorMessage(e))
    )
    try {
      setBatches(await api.listBatches())
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
    let failure: string | null = null
    try {
      await api.deleteBatch(id)
    } catch (e) {
      // "Make sure it's gone": a batch that is already missing is the outcome the user asked for.
      if (!(e instanceof ApiError && e.status === 404 && e.code === 'batch_not_found')) {
        failure = errorMessage(e)
      }
    }
    // Cleared/set before the reload: the reload never clears an error itself, so a failed
    // discard's message survives it, while a reload failure can still replace it.
    setError(failure === null ? null : `Couldn't discard the batch: ${failure}. The list has been refreshed.`)
    // Reload either way: after a failure the row may or may not still exist (e.g. the
    // delete half-ran), and the list must show the truth rather than the user's guess.
    await reload()
    // The Discard button that had focus is gone with its row; park focus somewhere stable.
    if (failure === null) heading.current?.focus()
  }

  const title = (slug: string | null) =>
    slug ? (books.find((b) => b.slug === slug)?.title ?? slug) : 'No default book'

  return (
    <main className="screen">
      <header className="row between">
        <h1 ref={heading} tabIndex={-1}>Note Taker</h1>
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
      {booksError && <p role="status" className="banner warn">Could not load books: {booksError}</p>}
      {healthError && (
        <p role="status" className="banner warn">Could not check the notes repo: {healthError}</p>
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
