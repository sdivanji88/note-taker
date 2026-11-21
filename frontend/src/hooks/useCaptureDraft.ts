import { useCallback, useEffect, useRef, useState } from 'react'
import { useApi } from '../api/context'
import type { Capture } from '../api/types'
import {
  buildPatch,
  dirtyFields,
  draftFromCapture,
  isGone,
  isPushing,
  isTransient,
  pageIsValid,
  reviewErrorMessage,
  type Draft
} from '../review/draft'

const DEBOUNCE_MS = 600
const AUTO_RETRY_MS = 3000

export type SaveState =
  | { kind: 'idle' | 'unsaved' | 'saving' | 'saved' }
  | { kind: 'error'; message: string; gone: boolean; pushing: boolean }

// Owns one capture's editable copy and its autosave. Invariants that make edits safe:
//  - at most one PATCH in flight; edits made meanwhile wait and go out as one PATCH;
//  - "dirty" means draft != last server-confirmed copy, so a response (or a re-fetch)
//    can only ever replace fields the user has not changed since;
//  - a failed save leaves the draft untouched and stays dirty until it succeeds.
// The caller keys this by capture id, so a late response can never reach another capture.
export function useCaptureDraft(capture: Capture, onSaved: (c: Capture) => void) {
  const api = useApi()
  const [draft, setDraftState] = useState(() => draftFromCapture(capture))
  const [save, setSave] = useState<SaveState>({ kind: 'idle' })
  const draftRef = useRef(draft)
  const baseRef = useRef(draft)
  const inflight = useRef<Promise<boolean> | null>(null)
  const debounce = useRef<ReturnType<typeof setTimeout>>(undefined)
  const retryTimer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const mounted = useRef(true)
  const onSavedRef = useRef(onSaved)
  onSavedRef.current = onSaved
  const id = capture.id

  const setDraft = useCallback((d: Draft) => {
    draftRef.current = d
    if (mounted.current) setDraftState(d)
  }, [])

  const send = useCallback(
    (body: NonNullable<ReturnType<typeof buildPatch>>, snapshot: Draft): Promise<boolean> => {
      const run = (async () => {
        if (mounted.current) setSave({ kind: 'saving' })
        try {
          const saved = await api.patchCapture(id, body.body)
          inflight.current = null
          // Confirm exactly what was sent (not the response): the response may be
          // normalised, and the user may already have typed past it.
          const base: Draft = { ...baseRef.current }
          for (const f of body.sent) (base as unknown as Record<string, unknown>)[f] = snapshot[f]
          if (body.sent.includes('highlights')) {
            // The backend minted ids for new blocks; adopt them so the next save sends
            // them back instead of creating duplicates.
            const ids = saved.highlights.map((h) => h.id)
            const keyToId = new Map(snapshot.highlights.map((h, i) => [h.key, ids[i] ?? h.id]))
            base.highlights = snapshot.highlights.map((h) => ({ ...h, id: keyToId.get(h.key) ?? h.id }))
            const cur = draftRef.current
            setDraft({
              ...cur,
              highlights: cur.highlights.map((h) => (h.id ? h : { ...h, id: keyToId.get(h.key) ?? null }))
            })
          }
          baseRef.current = base
          if (mounted.current) setSave({ kind: 'saved' })
          onSavedRef.current(saved)
          return true
        } catch (e) {
          inflight.current = null
          if (mounted.current) {
            setSave({ kind: 'error', message: reviewErrorMessage(e), gone: isGone(e), pushing: isPushing(e) })
            if (isTransient(e)) {
              clearTimeout(retryTimer.current)
              retryTimer.current = setTimeout(() => void flushRef.current(), AUTO_RETRY_MS)
            }
          }
          return false
        }
      })()
      inflight.current = run
      return run
    },
    [api, id, setDraft]
  )

  // Resolves true once everything typed so far is saved; false if a save failed or the
  // page number is invalid (so leaving the capture never silently drops it).
  const flush = useCallback(async (): Promise<boolean> => {
    clearTimeout(debounce.current)
    clearTimeout(retryTimer.current)
    for (;;) {
      const running = inflight.current
      if (running) {
        if (!(await running)) return false
        continue
      }
      const cur = draftRef.current
      // buildPatch withholds an invalid page, so every other edit is still saved; only
      // once the queue is drained does the invalid page make this report "not saved".
      const patch = buildPatch(cur, dirtyFields(cur, baseRef.current))
      if (!patch) return pageIsValid(cur)
      if (!(await send(patch, cur))) return false
    }
  }, [send])
  const flushRef = useRef(flush)
  flushRef.current = flush

  const edit = useCallback(
    (fn: (d: Draft) => Draft) => {
      setDraft(fn(draftRef.current))
      setSave((s) => (s.kind === 'error' ? s : { kind: 'unsaved' }))
      clearTimeout(debounce.current)
      debounce.current = setTimeout(() => void flushRef.current(), DEBOUNCE_MS)
    },
    [setDraft]
  )

  // Server data (re-fetch, SSE) only fills fields the user hasn't touched, and never while
  // a save is outstanding (its response follows and is authoritative for those fields).
  useEffect(() => {
    if (inflight.current) return
    const cur = draftRef.current
    const base = baseRef.current
    const server = draftFromCapture(capture, cur)
    const mine = new Set(dirtyFields(cur, base))
    const changed = dirtyFields(server, cur).filter((f) => !mine.has(f))
    if (!changed.length) return
    const next = { ...cur }
    const nextBase = { ...base }
    for (const f of changed) {
      ;(next as unknown as Record<string, unknown>)[f] = server[f]
      ;(nextBase as unknown as Record<string, unknown>)[f] = server[f]
    }
    baseRef.current = nextBase
    setDraft(next)
  }, [capture, setDraft])

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      // Fire and forget: nothing here may set state once unmounted.
      void flushRef.current()
    }
  }, [])

  return { draft, edit, save, flush }
}
