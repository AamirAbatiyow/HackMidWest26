import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import type { VouchStatus } from '@/api/types'

export type LaneFilter = 'all' | VouchStatus | 'held' | 'settled' | 'fastpay'

interface UiContextValue {
  /** Keyboard cursor / highlighted row. */
  activeId: string | null
  setActive: (id: string | null) => void
  /** Detail panel open state; it shows the active payment. */
  panelOpen: boolean
  setPanelOpen: (open: boolean) => void
  open: (id: string) => void
  /** Bulk selection. */
  checked: ReadonlySet<string>
  toggleChecked: (id: string) => void
  setChecked: (ids: Iterable<string>) => void
  clearChecked: () => void
  /** Lanes */
  collapsed: ReadonlySet<VouchStatus>
  toggleLane: (lane: VouchStatus) => void
  filter: LaneFilter
  setFilter: (f: LaneFilter) => void
  search: string
  setSearch: (q: string) => void
  /** Overlays */
  paletteOpen: boolean
  setPaletteOpen: (open: boolean) => void
  paletteQuery: string
  openPalette: (query?: string) => void
  feedOpen: boolean
  setFeedOpen: (open: boolean) => void
  feedPaused: boolean
  setFeedPaused: (paused: boolean) => void
  explainOpen: boolean
  setExplainOpen: (open: boolean) => void
  lastSettlementId: string | null
  setLastSettlementId: (id: string) => void
}

const UiContext = createContext<UiContextValue | null>(null)

export function UiProvider({ children }: { children: ReactNode }) {
  const initial = typeof window !== 'undefined' ? new URLSearchParams(window.location.search).get('payment') : null
  const [activeId, setActiveId] = useState<string | null>(initial)
  const [panelOpen, setPanelOpen] = useState<boolean>(Boolean(initial))
  const [checked, setCheckedState] = useState<Set<string>>(new Set())
  const [collapsed, setCollapsed] = useState<Set<VouchStatus>>(new Set())
  const [filter, setFilter] = useState<LaneFilter>('all')
  const [search, setSearch] = useState('')
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [paletteQuery, setPaletteQuery] = useState('')
  const [feedOpen, setFeedOpen] = useState(false)
  const [feedPaused, setFeedPaused] = useState(false)
  const [explainOpen, setExplainOpen] = useState(false)
  const [lastSettlementId, setLastSettlementId] = useState<string | null>(null)

  const setActive = useCallback((id: string | null) => setActiveId(id), [])
  const open = useCallback((id: string) => {
    setActiveId(id)
    setPanelOpen(true)
  }, [])
  const toggleChecked = useCallback((id: string) => {
    setCheckedState((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])
  const setChecked = useCallback((ids: Iterable<string>) => setCheckedState(new Set(ids)), [])
  const clearChecked = useCallback(() => setCheckedState(new Set()), [])
  const toggleLane = useCallback((lane: VouchStatus) => {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(lane)) next.delete(lane)
      else next.add(lane)
      return next
    })
  }, [])
  const openPalette = useCallback((query = '') => {
    setPaletteQuery(query)
    setPaletteOpen(true)
  }, [])

  const value = useMemo<UiContextValue>(
    () => ({
      activeId,
      setActive,
      panelOpen,
      setPanelOpen,
      open,
      checked,
      toggleChecked,
      setChecked,
      clearChecked,
      collapsed,
      toggleLane,
      filter,
      setFilter,
      search,
      setSearch,
      paletteOpen,
      setPaletteOpen,
      paletteQuery,
      openPalette,
      feedOpen,
      setFeedOpen,
      feedPaused,
      setFeedPaused,
      explainOpen,
      setExplainOpen,
      lastSettlementId,
      setLastSettlementId,
    }),
    [
      activeId,
      setActive,
      panelOpen,
      open,
      checked,
      toggleChecked,
      setChecked,
      clearChecked,
      collapsed,
      toggleLane,
      filter,
      search,
      paletteOpen,
      paletteQuery,
      openPalette,
      feedOpen,
      feedPaused,
      explainOpen,
      lastSettlementId,
    ],
  )
  return <UiContext.Provider value={value}>{children}</UiContext.Provider>
}

export function useUi(): UiContextValue {
  const ctx = useContext(UiContext)
  if (!ctx) throw new Error('useUi must be used inside <UiProvider>')
  return ctx
}
