import { useEffect, useState } from 'react'

import { ApiError } from './api'

export interface Loadable<T> {
  data: T | null
  error: string | null
  status: number | null // HTTP status of the failure, 0 for network errors
  loading: boolean
}

/** Run an async loader when deps change; ignores stale responses. */
export function useLoad<T>(loader: () => Promise<T>, deps: unknown[]): Loadable<T> {
  const [state, setState] = useState<Loadable<T>>({ data: null, error: null, status: null, loading: true })
  useEffect(() => {
    let alive = true
    // Clear old data so a previous page's content never renders under a new URL.
    setState({ data: null, error: null, status: null, loading: true })
    loader()
      .then((data) => alive && setState({ data, error: null, status: null, loading: false }))
      .catch((e: unknown) =>
        alive &&
        setState({
          data: null,
          error: e instanceof Error ? e.message : String(e),
          status: e instanceof ApiError ? e.status : 0,
          loading: false,
        }),
      )
    return () => {
      alive = false
    }
    // Callers pass their own deps array; the loader is intentionally excluded.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return state
}
