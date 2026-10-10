import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'

interface UiContextValue {
  agentPanelOpen: boolean
  agentRunKey: string
  agentSubject?: string
  openAgentPanel: (subject?: string) => void
  closeAgentPanel: () => void
  toggleAgentPanel: () => void
}

const UiContext = createContext<UiContextValue | null>(null)

export function UiProvider({ children }: { children: ReactNode }) {
  const [agentPanelOpen, setAgentPanelOpen] = useState(false)
  const [agentRunKey, setAgentRunKey] = useState('initial')
  const [agentSubject, setAgentSubject] = useState<string | undefined>(undefined)

  const openAgentPanel = useCallback((subject?: string) => {
    setAgentSubject(subject)
    setAgentRunKey(`${subject ?? 'all'}-${Date.now()}`)
    setAgentPanelOpen(true)
  }, [])
  const closeAgentPanel = useCallback(() => setAgentPanelOpen(false), [])
  const toggleAgentPanel = useCallback(() => {
    setAgentPanelOpen((o) => {
      if (!o) setAgentRunKey(`toggle-${Date.now()}`)
      return !o
    })
  }, [])

  const value = useMemo(
    () => ({ agentPanelOpen, agentRunKey, agentSubject, openAgentPanel, closeAgentPanel, toggleAgentPanel }),
    [agentPanelOpen, agentRunKey, agentSubject, openAgentPanel, closeAgentPanel, toggleAgentPanel],
  )
  return <UiContext.Provider value={value}>{children}</UiContext.Provider>
}

export function useUi(): UiContextValue {
  const ctx = useContext(UiContext)
  if (!ctx) throw new Error('useUi must be used inside <UiProvider>')
  return ctx
}
