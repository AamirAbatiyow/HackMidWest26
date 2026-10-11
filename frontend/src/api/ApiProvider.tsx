import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { HealthStatus, VouchApi } from './types'
import { createMockApi } from './mock'
import { createLiveApi } from './live'

export type ApiMode = 'mock' | 'live'
/** auto = live when reachable, mock otherwise. */
export type ApiPreference = 'auto' | ApiMode

const STORAGE_KEY = 'vouch.apiMode'
const PROBE_MS = 5000

export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL ?? import.meta.env.VITE_API_URL ?? 'http://localhost:8101'

const FORCE_MOCK: boolean = import.meta.env.VITE_USE_MOCK === '1' || import.meta.env.VITE_USE_MOCK === 'true'

function readPreference(): ApiPreference {
  if (FORCE_MOCK) return 'mock'
  if (typeof window !== 'undefined') {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored === 'mock' || stored === 'live' || stored === 'auto') return stored
  }
  const env = import.meta.env.VITE_API_MODE
  return env === 'live' || env === 'mock' ? env : 'auto'
}

interface ApiContextValue {
  api: VouchApi
  /** Effective mode after the reachability probe. */
  mode: ApiMode
  preference: ApiPreference
  setPreference: (pref: ApiPreference) => void
  baseUrl: string
  health: HealthStatus | null
  checkHealth: () => Promise<void>
}

const ApiContext = createContext<ApiContextValue | null>(null)

export function ApiProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ApiPreference>(readPreference)
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const live = useMemo(() => createLiveApi({ baseUrl: API_BASE_URL }), [])
  const mock = useMemo(() => createMockApi(), [])
  const probeId = useRef(0)

  const reachable = health?.ok === true
  const mode: ApiMode = preference === 'auto' ? (reachable ? 'live' : 'mock') : preference
  const api = mode === 'live' ? live : mock

  const setPreference = useCallback((next: ApiPreference) => {
    window.localStorage.setItem(STORAGE_KEY, next)
    setPreferenceState(next)
  }, [])

  const checkHealth = useCallback(async () => {
    const id = ++probeId.current
    const h = await live.getHealth()
    if (id === probeId.current) setHealth(h)
  }, [live])

  // Probe the live API on a fixed cadence so the status tag reflects reality.
  useEffect(() => {
    void checkHealth()
    const t = setInterval(() => void checkHealth(), PROBE_MS)
    return () => clearInterval(t)
  }, [checkHealth])

  const value = useMemo<ApiContextValue>(
    () => ({ api, mode, preference, setPreference, baseUrl: API_BASE_URL, health, checkHealth }),
    [api, mode, preference, setPreference, health, checkHealth],
  )

  return <ApiContext.Provider value={value}>{children}</ApiContext.Provider>
}

export function useApi(): ApiContextValue {
  const ctx = useContext(ApiContext)
  if (!ctx) throw new Error('useApi must be used inside <ApiProvider>')
  return ctx
}
