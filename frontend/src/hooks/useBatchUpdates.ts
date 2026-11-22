import { useEffect, useRef, useState } from 'react'
import type { SubscriptionState } from '../api/client'
import { useApi } from '../api/context'

// Events arrive in bursts (one per capture); one refetch per burst is enough.
const REFETCH_DEBOUNCE_MS = 200
// EventSource drops and reopens by itself all the time (sleep, proxy idle timeouts).
// Only a drop that outlasts this is worth telling the user about.
export const STALE_GRACE_MS = 2000

// Keeps a screen's batch data fresh from the backend's event stream: debounced refetch
// per event burst, plus one catch-up refetch when the stream comes back after a drop
// (events sent while it was down are gone for good).
//
// Returns the connection state to show: 'reconnecting' is only reported after
// STALE_GRACE_MS, so callers can render it directly without flicker handling.
export function useBatchUpdates(batchId: string, refetch: () => unknown): SubscriptionState {
  const api = useApi()
  const [connection, setConnection] = useState<SubscriptionState>('live')
  // The latest refetch without re-subscribing whenever the caller's closure changes.
  const refetchRef = useRef(refetch)
  refetchRef.current = refetch

  useEffect(() => {
    let debounce: ReturnType<typeof setTimeout> | undefined
    let grace: ReturnType<typeof setTimeout> | undefined
    // What the stream is actually doing; `connection` lags it during the grace period.
    // Starts 'live' so the first open is not mistaken for a recovery.
    let actual: SubscriptionState = 'live'
    setConnection('live')

    const unsubscribe = api.subscribe(
      batchId,
      () => {
        clearTimeout(debounce)
        debounce = setTimeout(() => void refetchRef.current(), REFETCH_DEBOUNCE_MS)
      },
      (next) => {
        const previous = actual
        actual = next
        if (next === 'reconnecting') {
          // Every failed retry fires another error; restarting the timer each time would
          // postpone the notice forever.
          if (previous !== 'reconnecting') {
            grace = setTimeout(() => setConnection('reconnecting'), STALE_GRACE_MS)
          }
          return
        }
        clearTimeout(grace)
        setConnection(next)
        if (next === 'live' && previous !== 'live') void refetchRef.current()
      }
    )
    return () => {
      clearTimeout(debounce)
      clearTimeout(grace)
      unsubscribe()
    }
  }, [api, batchId])

  return connection
}
