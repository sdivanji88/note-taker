import { useEffect, useState } from 'react'
import App from './App'
import { ApiContext } from './api/context'
import { createClient, type ApiClient } from './api/client'
import type { BackendConfig } from './api/types'
import { errorMessage } from './format'

interface Props {
  getConfig?: () => Promise<BackendConfig>
  makeClient?: (cfg: BackendConfig) => ApiClient
}

// Fetches the backend address once, proves the backend answers, then provides the client.
// Injection points exist for tests; main.tsx passes neither.
export default function Root({
  getConfig = () => window.noteTaker.getConfig(),
  makeClient = createClient
}: Props) {
  const [client, setClient] = useState<ApiClient | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const c = makeClient(await getConfig())
        await c.getHealth()
        if (!cancelled) setClient(c)
      } catch (e) {
        // ApiError messages are already token-free; the config itself is never printed.
        if (!cancelled) setError(errorMessage(e))
      }
    })()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (error) return <p role="alert" className="error screen">Could not start Note Taker: {error}</p>
  if (!client) return <p className="screen">Starting…</p>
  return (
    <ApiContext.Provider value={client}>
      <App />
    </ApiContext.Provider>
  )
}
