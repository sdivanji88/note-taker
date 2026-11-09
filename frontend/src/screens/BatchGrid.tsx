import { useCallback, useEffect, useRef, useState } from 'react'
import { useApi } from '../api/context'
import { ApiError, type Batch, type PushResult } from '../api/types'
import BookSelect from '../components/BookSelect'
import Thumb, { REVIEWABLE } from '../components/Thumb'
import { errorMessage } from '../format'

interface Props {
  batchId: string
  // `index` is a position in the batch's full `captures` array (pushed ones included).
  onOpenReview: (index: number) => void
  onBack: () => void
}

const ACCEPT = 'image/png,image/jpeg'
const ACCEPTED_TYPES = ACCEPT.split(',')
const REJECTION_TEXT: Record<string, string> = {
  unsupported: 'not a PNG or JPEG',
  unsupported_type: 'not a PNG or JPEG',
  duplicate: 'already in this batch',
  too_large: 'larger than 25 MB',
  too_many_files: 'more than 100 files at once'
}
// Events can arrive in bursts (one per capture); one refetch per burst is enough.
const REFETCH_DEBOUNCE_MS = 200

// Cheap client-side filter only to avoid pointless uploads; the server stays the authority.
function looksLikeImage(f: File): boolean {
  if (f.type) return ACCEPTED_TYPES.includes(f.type)
  return /\.(png|jpe?g)$/i.test(f.name)
}

function pushErrorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 409 && e.code === 'dirty_repo')
      return 'Your notes repo has uncommitted changes. Commit or stash them, then push again.'
    if (e.status === 409 && e.code === 'not_cloned') return 'Connect your notes repo in Settings first.'
    if (e.status === 409 && e.code === 'batch_pushing') return 'A push is already running for this batch.'
    if (e.status === 422 && e.code === 'unknown_book')
      return 'Choose a book for every approved capture before pushing.'
  }
  return errorMessage(e)
}

export default function BatchGrid({ batchId, onOpenReview, onBack }: Props) {
  const api = useApi()
  const [batch, setBatch] = useState<Batch | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [notices, setNotices] = useState<string[]>([])
  const [actionError, setActionError] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [working, setWorking] = useState(false)
  const [pushing, setPushing] = useState(false)
  const [pushError, setPushError] = useState<string | null>(null)
  const [pushResult, setPushResult] = useState<PushResult | null>(null)
  const pushingRef = useRef(false)
  const fileInput = useRef<HTMLInputElement>(null)

  const refresh = useCallback(async () => {
    try {
      setBatch(await api.getBatch(batchId))
      setLoadError(null)
    } catch (e) {
      setLoadError(errorMessage(e))
    }
  }, [api, batchId])

  useEffect(() => {
    setBatch(null)
    void refresh()
  }, [refresh])

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined
    const unsubscribe = api.subscribe(batchId, () => {
      clearTimeout(timer)
      timer = setTimeout(() => void refresh(), REFETCH_DEBOUNCE_MS)
    })
    return () => {
      clearTimeout(timer)
      unsubscribe()
    }
  }, [api, batchId, refresh])

  const busy = working || pushing
  // A deleted batch (push succeeded) has nothing left to show or edit.
  const gone = pushResult?.batch_deleted === true
  const captures = batch?.captures ?? []
  const visible = captures.map((c, index) => ({ c, index })).filter(({ c }) => c.status !== 'pushed')
  const firstReviewable = captures.findIndex((c) => REVIEWABLE.includes(c.status))
  const approved = captures.filter((c) => c.status === 'approved').length

  async function upload(all: File[]) {
    if (all.length === 0) return
    const files = all.filter(looksLikeImage)
    const skipped = all.filter((f) => !looksLikeImage(f)).map((f) => `${f.name}: ${REJECTION_TEXT.unsupported}`)
    setNotices(skipped)
    if (files.length === 0) return
    setWorking(true)
    try {
      const result = await api.uploadPhotos(batchId, files)
      setNotices([
        ...skipped,
        ...result.rejected.map((r) => `${r.filename}: ${REJECTION_TEXT[r.reason] ?? r.reason}`)
      ])
      setActionError(null)
    } catch (e) {
      setActionError(errorMessage(e))
    } finally {
      // Refetch even on failure: some files may have been stored before the error.
      await refresh()
      setWorking(false)
    }
  }

  async function removeSelected() {
    setWorking(true)
    const ids = [...selected]
    const results = await Promise.allSettled(ids.map((id) => api.deleteCapture(id)))
    const failed = results.find((r): r is PromiseRejectedResult => r.status === 'rejected')
    setActionError(failed ? errorMessage(failed.reason) : null)
    setSelected(new Set())
    await refresh()
    setWorking(false)
  }

  async function addKindle() {
    setWorking(true)
    try {
      const created = await api.addKindle(batchId, {
        source: 'kindle',
        highlights: [{ text: '' }],
        book_slug: batch?.default_book_slug ?? null
      })
      const fresh = await api.getBatch(batchId)
      setBatch(fresh)
      const index = fresh.captures.findIndex((c) => c.id === created.id)
      onOpenReview(index >= 0 ? index : fresh.captures.length - 1)
    } catch (e) {
      setActionError(errorMessage(e))
    } finally {
      setWorking(false)
    }
  }

  async function setDefaultBook(slug: string | null) {
    try {
      setBatch(await api.patchBatch(batchId, { default_book_slug: slug }))
      setActionError(null)
    } catch (e) {
      setActionError(errorMessage(e))
    }
  }

  async function push() {
    if (pushingRef.current) return
    pushingRef.current = true
    setPushing(true)
    setPushError(null)
    setPushResult(null)
    try {
      const result = await api.push(batchId)
      setPushResult(result)
      if (!result.batch_deleted) await refresh()
    } catch (e) {
      setPushError(pushErrorMessage(e))
      await refresh()
    } finally {
      pushingRef.current = false
      setPushing(false)
    }
  }

  function toggle(id: string) {
    setSelected((s) => {
      const next = new Set(s)
      if (!next.delete(id)) next.add(id)
      return next
    })
  }

  return (
    <main className="screen">
      <header className="row between">
        <button onClick={onBack}>← Batches</button>
        <h1>Batch</h1>
        <div className="row">
          <span className="muted">Live updates may be stale</span>
          <button onClick={() => void refresh()}>Refresh</button>
        </div>
      </header>
      {loadError && <p role="alert" className="error">{loadError}</p>}
      {pushResult && (
        <div role="status" aria-label="Push result" className="banner ok">
          Pushed {pushResult.highlights_written} {pushResult.highlights_written === 1 ? 'highlight' : 'highlights'} (commit{' '}
          {pushResult.commit_sha.slice(0, 7)})
          {pushResult.files_changed.length > 0 && <>: {pushResult.files_changed.join(', ')}</>}
          {pushResult.batch_deleted && ' The batch was removed from this computer.'}
        </div>
      )}
      {!batch || gone ? null : (
        <>
          <section className="row">
            <div
              role="button"
              tabIndex={0}
              aria-label="Drop photos here or press Enter to choose"
              aria-disabled={busy}
              className="dropzone"
              onClick={() => !busy && fileInput.current?.click()}
              onKeyDown={(e) => {
                if (busy) return
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  fileInput.current?.click()
                }
              }}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault()
                if (!busy) void upload(Array.from(e.dataTransfer.files))
              }}
            >
              Drop photos here, or press Enter to choose
            </div>
            <input
              ref={fileInput}
              type="file"
              multiple
              accept={ACCEPT}
              aria-label="Photo files"
              className="hidden"
              disabled={busy}
              onChange={(e) => {
                void upload(Array.from(e.target.files ?? []))
                e.target.value = ''
              }}
            />
            <BookSelect
              label="Book for all"
              value={batch.default_book_slug}
              onChange={(s) => void setDefaultBook(s)}
              allowCreate
              disabled={busy}
            />
          </section>
          {notices.length > 0 && (
            <ul aria-label="Upload notes" className="notices">
              {notices.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          )}
          {actionError && <p role="alert" className="error">{actionError}</p>}
          <section className="row">
            <button onClick={() => void removeSelected()} disabled={busy || selected.size === 0}>
              Remove selected
            </button>
            <button onClick={() => void addKindle()} disabled={busy}>Add Kindle highlight</button>
            <button onClick={() => onOpenReview(firstReviewable)} disabled={firstReviewable < 0}>
              Review {Math.max(firstReviewable, 0) + 1} of {captures.length} →
            </button>
            <button onClick={() => void push()} disabled={approved === 0 || busy}>
              Push all approved ({approved})
            </button>
          </section>
          {pushError && <p role="alert" className="error">{pushError}</p>}
          <ul className="grid">
            {visible.map(({ c, index }) => (
              <Thumb
                key={c.id}
                capture={c}
                position={index + 1}
                imageUrl={c.image_file ? api.imageUrl(c.id) : null}
                selected={selected.has(c.id)}
                disabled={busy}
                onToggle={() => toggle(c.id)}
                onOpen={() => onOpenReview(index)}
              />
            ))}
          </ul>
        </>
      )}
    </main>
  )
}
