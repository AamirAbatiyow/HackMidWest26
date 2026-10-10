import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { HealthStatus, VouchApi } from './types'
import { createMockApi } from './mock'
import { createLiveApi } from './live'

export type ApiMode = 'mock' | 'live'

const STORAGE_KEY = 'vouch.apiMode'

export const API_BASE_URL: string = import.meta.env.VITE_API_URL ?? 'http://localhost:8101'

function readInitialMode(): ApiMode {
  if (typeof window !== 'undefined') {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored === 'mock' || stored === 'live') return stored
  }
  return import.meta.env.VITE_API_MODE === 'live' ? 'live' : 'mock'
}

interface ApiContextValue {
  api: VouchApi
  mode: ApiMode
  setMode: (mode: ApiMode) => void
  baseUrl: string
  health: HealthStatus | null
  checkHealth: () => Promise<void>
}

const ApiContext = createContext<ApiContextValue | null>(null)

export function ApiProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ApiMode>(readInitialMode)
  const [health, setHealth] = useState<HealthStatus | null>(null)

  const api = useMemo<VouchApi>(
    () => (mode === 'live' ? createLiveApi({ baseUrl: API_BASE_URL }) : createMockApi()),
    [mode],
  )

  const setMode = useCallback((next: ApiMode) => {
    window.localStorage.setItem(STORAGE_KEY, next)
    setModeState(next)
  }, [])

  const checkHealth = useCallback(async () => {
    setHealth(await api.getHealth())
  }, [api])

  useEffect(() => {
    void checkHealth()
  }, [checkHealth])

  const value = useMemo<ApiContextValue>(
    () => ({ api, mode, setMode, baseUrl: API_BASE_URL, health, checkHealth }),
    [api, mode, setMode, health, checkHealth],
  )

  return <ApiContext.Provider value={value}>{children}</ApiContext.Provider>
}

export function useApi(): ApiContextValue {
  const ctx = useContext(ApiContext)
  if (!ctx) throw new Error('useApi must be used inside <ApiProvider>')
  return ctx
}
