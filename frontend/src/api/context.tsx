import { createContext, useContext } from 'react'
import type { ApiClient } from './client'

// Screens get the client from context rather than importing a singleton so tests can
// inject a fake without stubbing fetch.
export const ApiContext = createContext<ApiClient | null>(null)

export function useApi(): ApiClient {
  const client = useContext(ApiContext)
  if (!client) throw new Error('useApi must be used inside <ApiContext.Provider>')
  return client
}
