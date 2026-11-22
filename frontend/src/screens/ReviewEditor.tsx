import { useCallback, useEffect, useRef, useState } from 'react'
import { useApi } from '../api/context'
import type { Batch, Capture, ExtractorKind } from '../api/types'
import CapturePane, { type PaneActions } from '../components/CapturePane'
import ConfirmDialog from '../components/ConfirmDialog'
import { useBatchUpdates } from '../hooks/useBatchUpdates'
import { navigable } from '../review/navigable'
import { isGone, reviewErrorMessage } from '../review/draft'

interface Props {
  batchId: string
  // A position in the batch's full `captures` array (pushed ones included).
  index: number
  onBack: () => void
}

const GONE = 'This capture no longer exists.'

// Nearest navigable position to `from`, preferring the later one on a tie.
function nearest(captures: Capture[], from: number): number {
  let best = -1
  captures.forEach((c, i) => {
    if (!navigable(c)) return
    if (best < 0 || Math.abs(i - from) < Math.abs(best - from) || (Math.abs(i - from) === Math.abs(best - from) && i > best))
      best = i
  })
  return best
}

const isTextEntry = (t: EventTarget | null) =>
  t instanceof HTMLElement && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName))

export default function ReviewEditor({ batchId, index, onBack }: Props) {
  const api = useApi()
  const [batch, setBatch] = useState<Batch | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [extractor, setExtractor] = useState<ExtractorKind | null>(null)
  const [loads, setLoads] = useState(0)
  const [confirmLeave, setConfirmLeave] = useState(false)
  const actionsRef = useRef<PaneActions | null>(null)
  const mounted = useRef(true)
  // Bumped whenever a PATCH result is merged; a re-fetch that started before that is stale.
  const mutations = useRef(0)
  const lastIndex = useRef(index)
  const byKeyboard = useRef(false)

  const load = useCallback(async (): Promise<void> => {
    const started = mutations.current
    try {
      const b = await api.getBatch(batchId)
      if (!mounted.current) return
      // A save finished while this request was in flight: its data may predate that save.
      if (mutations.current !== started) return load()
      setBatch(b)
      setLoads((n) => n + 1)
      setProblem(null)
    } catch (e) {
      if (!mounted.current) return
      if (isGone(e)) {
        setBatch(null)
        setProblem(GONE)
      } else {
        // Keep the editor (and any unsaved text) on screen; just say the refresh failed.
        setProblem(reviewErrorMessage(e))
      }
    }
  }, [api, batchId])

  useEffect(() => {
    mounted.current = true
    void load()
    return () => {
      mounted.current = false
    }
  }, [load])

  // No banner here: the editor shows the batch only as context, but it still catches up
  // after a reconnect so statuses it missed don't leave it stale.
  useBatchUpdates(batchId, load)

  useEffect(() => {
    api.getSettings().then(
      (s) => mounted.current && setExtractor(s.extractor.kind),
      () => {} // The extractor label is a nicety; the editor works without it.
    )
  }, [api])

  const merge = useCallback((c: Capture) => {
    if (!mounted.current) return
    mutations.current++
    setBatch((b) => b && { ...b, captures: b.captures.map((x) => (x.id === c.id ? c : x)) })
  }, [])

  const captures = batch?.captures ?? []
  const nav = captures.map((c, i) => (navigable(c) ? i : -1)).filter((i) => i >= 0)
  const wanted = selectedId ? captures.findIndex((c) => c.id === selectedId) : index
  const at = batch ? nearest(captures, wanted >= 0 ? wanted : lastIndex.current) : -1
  const current = at >= 0 ? captures[at] : null
  if (at >= 0) lastIndex.current = at
  const position = nav.indexOf(at) + 1

  const view = useRef({ nav, captures, position })
  view.current = { nav, captures, position }

  const moveTo = useCallback((offset: number, viaKey = false): boolean => {
    const { nav: n, captures: cs, position: p } = view.current
    const target = n[p - 1 + offset]
    if (target === undefined) return false
    byKeyboard.current = viaKey
    setSelectedId(cs[target].id)
    return true
  }, [])

  // The just-saved capture the user is leaving, if it is a Kindle entry they never filled
  // in. Deleted here (best effort, awaited so the batch grid's reload can't race it)
  // rather than on unmount: only a deliberate Back/Prev/Next may remove anything.
  // Resolves to the removed id, or null when nothing was removed.
  const dropBlankKindle = useCallback(async (): Promise<string | null> => {
    const pane = actionsRef.current
    const id = pane?.blankKindleId()
    if (!pane || !id) return null
    // Frozen in the same tick as the blank check: a keystroke during the round-trip would
    // otherwise be lost along with the capture.
    pane.setLeaving(true)
    try {
      await api.deleteCapture(id)
      return id
    } catch {
      pane.setLeaving(false) // Cleanup is a courtesy; the capture stays and the user moves on.
      return null
    }
  }, [api])

  // Mirrors the server after a delete without a refetch, so the position count and
  // Prev/Next stop counting the removed capture.
  const forget = useCallback((id: string) => {
    if (!mounted.current) return
    mutations.current++
    setBatch((b) => b && { ...b, captures: b.captures.filter((x) => x.id !== id) })
  }, [])

  const go = useCallback(async (offset: number, viaKey = false) => {
    // Never leave a capture with edits still unsaved.
    if (!(await actionsRef.current?.flush())) return
    const { nav: n, position: p } = view.current
    if (n[p - 1 + offset] === undefined) return // nowhere to go: stay, and keep the capture
    const dropped = await dropBlankKindle()
    moveTo(offset, viaKey)
    if (dropped) forget(dropped) // same tick as moveTo, so one render sees both
  }, [moveTo, dropBlankKindle, forget])

  const afterApproved = useCallback(() => {
    if (!moveTo(1)) onBack()
  }, [moveTo, onBack])
  const afterDiscarded = useCallback(() => {
    if (!moveTo(1) && !moveTo(-1)) onBack()
  }, [moveTo, onBack])

  // Leaving counts as navigation: unsaved edits must be saved first, and if they can't be
  // the user decides explicitly instead of losing them to the unmount flush.
  const back = useCallback(async () => {
    if (!actionsRef.current || (await actionsRef.current.flush())) {
      await dropBlankKindle()
      onBack()
    } else if (mounted.current) setConfirmLeave(true)
  }, [onBack, dropBlankKindle])

  const goRef = useRef(go)
  goRef.current = go
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (document.querySelector('[role="dialog"]')) return
      // The Enter that confirms an IME candidate (keyCode 229 on some engines) must reach
      // the input untouched, and a held key must not approve repeatedly.
      if (e.isComposing || e.keyCode === 229) return
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
        if (e.repeat) return
        const pane = actionsRef.current
        // Not claimed (no preventDefault) when Approve would be disabled: the shortcut
        // must do exactly what the button would, which here is nothing.
        if (!pane?.canApprove()) return
        e.preventDefault()
        void pane.approve()
      } else if ((e.key === 'ArrowLeft' || e.key === 'ArrowRight') && !isTextEntry(e.target)) {
        void goRef.current(e.key === 'ArrowRight' ? 1 : -1, true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  if (!current) actionsRef.current = null

  return (
    <main className="screen review">
      <button type="button" onClick={() => void back()}>← Back to batch</button>
      {problem && <p role="alert" className="error">{problem}</p>}
      {!problem && !batch && <p>Loading…</p>}
      {batch && !current && <p>Nothing left to review in this batch.</p>}
      {batch && current && problem !== GONE && (
        <CapturePane
          key={current.id}
          capture={current}
          position={position}
          total={nav.length}
          batchDefaultSlug={batch.default_book_slug}
          batchPushing={batch.status === 'pushing'}
          extractorName={extractor}
          loads={loads}
          focusFirst={!byKeyboard.current}
          actionsRef={actionsRef}
          onSaved={merge}
          onRefresh={load}
          onPrev={() => void go(-1)}
          onNext={() => void go(1)}
          onApproved={afterApproved}
          onDiscarded={afterDiscarded}
        />
      )}
      {confirmLeave && (
        <ConfirmDialog
          title="Leave without saving?"
          message="Your latest edits on this capture could not be saved. Stay to retry, or leave and lose them."
          confirmLabel="Leave without saving"
          cancelLabel="Stay"
          onConfirm={onBack}
          onCancel={() => setConfirmLeave(false)}
        />
      )}
    </main>
  )
}
