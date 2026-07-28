import { useMemo } from 'react'
import { useAuth } from '@clerk/clerk-react'
import { createApi } from './api.js'

/** Bound API client for the current signed-in user. Use inside any
 * component under <ClerkProvider> — every call automatically attaches a
 * fresh session token. */
export function useApi() {
  const { getToken } = useAuth()
  return useMemo(() => createApi(getToken), [getToken])
}
