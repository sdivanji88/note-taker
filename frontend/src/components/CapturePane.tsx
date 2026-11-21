import { useEffect, useRef, useState, type MutableRefObject } from 'react'
import { useApi } from '../api/context'
import { ApiError, type Capture, type ExtractorKind } from '../api/types'
import { useCaptureDraft } from '../hooks/useCaptureDraft'
import { isGone, isPushing, newKey, pageIsValid, PAGE_ERROR, reviewErrorMessage } from '../review/draft'
import BookSelect from './BookSelect'
import CapturePhoto from './CapturePhoto'
import ConfirmDialog from './ConfirmDialog'
import HighlightBlock from './HighlightBlock'
import ReviewFooter from './ReviewFooter'

// What the parent needs from a mounted pane: keyboard shortcuts and navigation must
// flush edits (and approve) through the pane that owns them.
export interface PaneActions {
  flush: () => Promise<boolean>
  approve: () => Promise<boolean>
}

interface Props {
  capture: Capture
  position: number
  total: number
  batchDefaultSlug: string | null
  batchPushing: boolean
  extractorName: ExtractorKind | null
  // Counts successful batch (re-)fetches, so the pane can tell a fresh answer from the old one.
  loads: number
  focusFirst: boolean
  actionsRef: MutableRefObject<PaneActions | null>
  onSaved: (c: Capture) => void
  onRefresh: () => Promise<void>
  onPrev: () => void
  onNext: () => void
  onApproved: () => void
  onDiscarded: () => void
}

const SAVE_TEXT = { idle: '', unsaved: 'Not saved', saving: 'Saving…', saved: 'Saved' } as const

export default function CapturePane(props: Props) {
  const { capture, batchDefaultSlug, extractorName, actionsRef, onSaved, onRefresh } = props
  const api = useApi()
  const { draft, edit, save, flush } = useCaptureDraft(capture, onSaved)
  const [actionError, setActionError] = useState<string | null>(null)
  const [gone, setGone] = useState(false)
  // Set by a 409 batch_pushing; cleared (and the held edit re-sent) once a fresh batch
  // fetch says the push is over. Read-only while pushing comes from the batch itself.
  const [pushHeld, setPushHeld] = useState(false)
  const heldAtLoad = useRef(0)
  const [busy, setBusy] = useState(false)
  const [confirmDiscard, setConfirmDiscard] = useState(false)
  const [rotated, setRotated] = useState(false)
  const [retryKind, setRetryKind] = useState<ExtractorKind>(extractorName ?? 'tesseract')
  const [lastAdded, setLastAdded] = useState<string | null>(null)
  const busyRef = useRef(false)
  const mounted = useRef(true)
  const root = useRef<HTMLElement>(null)
  const firstField = useRef<HTMLInputElement>(null)

  const { status } = capture
  const unfinished = status === 'pending' || status === 'extracting'
  const isPushingNow = props.batchPushing || pushHeld
  const readOnly = unfinished || isPushingNow
  // Pending with an error = waiting on an unavailable extractor; the backend allows a
  // retry (possibly with the other extractor) from there, just as from failed.
  const waiting = status === 'pending' && !!capture.error
  const isGoneNow = gone || (save.kind === 'error' && save.gone)
  const pageOk = pageIsValid(draft)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  const holdForPush = () => {
    heldAtLoad.current = props.loads
    setPushHeld(true)
    void onRefresh()
  }
  const autosavePushed = save.kind === 'error' && save.pushing
  useEffect(() => {
    if (autosavePushed && !pushHeld) holdForPush()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autosavePushed])
  useEffect(() => {
    if (pushHeld && !props.batchPushing && props.loads > heldAtLoad.current) {
      setPushHeld(false)
      void flush()
    }
  }, [pushHeld, props.batchPushing, props.loads, flush])
  useEffect(() => {
    // Keyboard navigation keeps focus off the inputs so the next arrow press still works.
    ;(props.focusFirst ? firstField.current : root.current)?.focus()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  useEffect(() => {
    if (extractorName) setRetryKind(extractorName)
  }, [extractorName])

  // Runs a user action after saving pending edits; the busy latch stops a double ⌘↵ or
  // click from sending the same transition twice.
  async function act(fn: () => Promise<void>, opts: { needFlush?: boolean } = {}): Promise<boolean> {
    if (busyRef.current) return false
    busyRef.current = true
    setBusy(true)
    setActionError(null)
    try {
      const saved = await flush()
      if (!saved && opts.needFlush !== false) return false
      await fn()
      return true
    } catch (e) {
      if (!mounted.current) return false
      setActionError(reviewErrorMessage(e))
      if (isGone(e)) setGone(true)
      if (isPushing(e)) holdForPush()
      if (e instanceof ApiError && e.code === 'invalid_transition') void onRefresh()
      return false
    } finally {
      busyRef.current = false
      if (mounted.current) setBusy(false)
    }
  }

  const patch = async (body: Parameters<typeof api.patchCapture>[1]) => onSaved(await api.patchCapture(capture.id, body))

  async function approve(): Promise<boolean> {
    // Already-approved captures are editable too, so they still flush (and may be refused)
    // before moving on.
    const ok = await act(async () => {
      if (status === 'approved') return
      // A failed capture the user fixed by hand has to become ready first.
      if (status === 'failed') await patch({ status: 'ready' })
      await patch({ status: 'approved' })
    })
    if (ok && mounted.current) props.onApproved()
    return ok
  }
  // After commit, not during render. The parent clears it when no pane is shown; a
  // successor pane overwrites it, so an unmounting pane must not null it out.
  useEffect(() => {
    // A capture that no longer exists has nothing to save, so leaving it never prompts.
    actionsRef.current = isGoneNow ? { flush: async () => true, approve: async () => false } : { flush, approve }
  })

  const unapprove = () => void act(() => patch({ status: 'ready' }))
  const rotate = () =>
    void act(async () => {
      await patch({ rotation: ((capture.rotation + 90) % 360) as Capture['rotation'] })
      setRotated(true)
    })
  const retry = () =>
    void act(async () => {
      onSaved(await api.retryCapture(capture.id, retryKind))
    })
  const discard = async () => {
    setConfirmDiscard(false)
    const ok = await act(
      async () => {
        if (status === 'approved') await patch({ status: 'ready' })
        await patch({ status: 'discarded' })
      },
      { needFlush: false }
    )
    if (ok && mounted.current) props.onDiscarded()
  }

  if (isGoneNow) return <p role="alert" className="error">This capture no longer exists.</p>

  const problem = actionError ?? (save.kind === 'error' ? save.message : null)
  const setHighlight = (key: string, p: object) =>
    edit((d) => ({ ...d, highlights: d.highlights.map((h) => (h.key === key ? { ...h, ...p } : h)) }))
  const retrying = status === 'failed' && rotated

  return (
    <section ref={root} tabIndex={-1} className="review-pane">
      <header className="row between">
        <BookSelect
          value={draft.book_slug}
          disabled={readOnly}
          noneLabel={batchDefaultSlug ? `(batch default: ${batchDefaultSlug})` : '(none)'}
          onChange={(slug) => edit((d) => ({ ...d, book_slug: slug }))}
        />
        <div>
          {extractorName && <span className="muted">Extractor: {extractorName}</span>}
          <div role="status" aria-live="polite" className="muted">
            {save.kind === 'error' ? (
              <>
                Couldn&apos;t save — retrying…{' '}
                <button type="button" className="link" onClick={() => void flush()}>Retry now</button>
              </>
            ) : !pageOk ? (
              'Not saved — fix the page number'
            ) : (
              SAVE_TEXT[save.kind]
            )}
          </div>
        </div>
      </header>

      {problem && <p role="alert" className="error">{problem}</p>}
      {waiting ? (
        <p className="banner warn">
          Waiting for the extractor: {capture.error}. Change it in Settings, or retry with the other extractor.
        </p>
      ) : (
        unfinished && <p className="banner">Still extracting… you can edit once it&apos;s ready.</p>
      )}
      {status === 'failed' && capture.error && <p className="banner warn">Extraction failed: {capture.error}</p>}
      {isPushingNow && !unfinished && (
        <p className="banner warn">A push is running for this batch; editing is paused until it finishes.</p>
      )}

      <div className="review-body">
        <CapturePhoto
          capture={capture}
          src={`${api.imageUrl(capture.id)}&v=${capture.rotation}`}
          rotateDisabled={busy || readOnly || !(status === 'ready' || status === 'failed')}
          rotatedReady={rotated && status !== 'failed'}
          rerunVisible={retrying}
          rerunDisabled={busy || readOnly}
          onRotate={rotate}
          onRerun={retry}
        />
        <div className="review-fields">
          <label>
            Page
            <input ref={firstField} type="number" min={0} step={1} value={draft.page} disabled={readOnly}
              onChange={(e) => edit((d) => ({ ...d, page: e.target.value }))} />
          </label>
          {!pageOk && <p className="error">{PAGE_ERROR}</p>}
          <label>
            Chapter
            <input value={draft.chapter} disabled={readOnly}
              onChange={(e) => edit((d) => ({ ...d, chapter: e.target.value }))} />
          </label>
          <label>
            Captured
            <input type="datetime-local" step={1} value={draft.captured_at} disabled={readOnly}
              onChange={(e) => edit((d) => ({ ...d, captured_at: e.target.value }))} />
          </label>
          {draft.highlights.map((h) => (
            <HighlightBlock
              key={h.key}
              highlight={h}
              disabled={readOnly}
              autoFocus={h.key === lastAdded}
              onChange={(p) => setHighlight(h.key, p)}
              onRemove={() => edit((d) => ({ ...d, highlights: d.highlights.filter((x) => x.key !== h.key) }))}
            />
          ))}
          <button
            type="button"
            disabled={readOnly}
            onClick={() => {
              const key = newKey()
              setLastAdded(key)
              edit((d) => ({ ...d, highlights: [...d.highlights, { key, id: null, text: '', note: '' }] }))
            }}
          >
            + Add highlight
          </button>
        </div>
      </div>

      <ReviewFooter
        position={props.position}
        total={props.total}
        status={status}
        busy={busy}
        readOnly={readOnly}
        canDiscard={!isPushingNow}
        canRetry={status === 'failed' || waiting}
        retryDisabled={isPushingNow}
        extractor={retryKind}
        onPrev={props.onPrev}
        onNext={props.onNext}
        onDiscard={() => setConfirmDiscard(true)}
        onApprove={() => void approve()}
        onUnapprove={unapprove}
        onExtractor={setRetryKind}
        onRetry={retry}
      />
      {confirmDiscard && (
        <ConfirmDialog
          title="Discard this capture?"
          message="It will be removed from the batch and nothing from it will be pushed."
          confirmLabel="Discard"
          onConfirm={() => void discard()}
          onCancel={() => setConfirmDiscard(false)}
        />
      )}
    </section>
  )
}
