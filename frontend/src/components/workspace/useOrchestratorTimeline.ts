import { useCallback, useEffect, useRef, useState } from 'react'
import { useApi } from '@/api/ApiProvider'
import type { Payment } from '@/api/types'
import { mockTimelineFor, normalizeTimeline, type OrchestratorTimeline } from '@/data/orchestrator'
import { usePayments } from '@/store/PaymentsProvider'

/** Poll fast while the run is still executing, slowly once it is complete (owner actions still land). */
export const RUNNING_POLL_MS = 1500
export const SETTLED_POLL_MS = 8000
/** Mock mode replays the steps one by one the first time an invoice is opened, so the pane reads live. */
export const MOCK_REVEAL_MS = 220

export async function fetchTimeline(baseUrl: string, paymentId: string, fetchImpl: typeof fetch = fetch): Promise<OrchestratorTimeline> {
  const base = baseUrl.replace(/\/$/, '')
  const res = await fetchImpl(`${base}/v1/payments/${encodeURIComponent(paymentId)}/timeline`, { headers: { Accept: 'application/json' } })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return normalizeTimeline(await res.json())
}

export interface TimelineState {
  timeline: OrchestratorTimeline | null
  /** Steps currently shown (mock mode reveals them progressively). */
  visible: number
  loading: boolean
  error: string | null
  refresh: () => void
}

interface Loaded {
  /** Payment the data belongs to; a different selection renders as empty until its own load lands. */
  forId: string | null
  timeline: OrchestratorTimeline | null
  error: string | null
  loading: boolean
}

const EMPTY: Loaded = { forId: null, timeline: null, error: null, loading: false }

export function useOrchestratorTimeline(payment: Payment | undefined, paused = false): TimelineState {
  const { mode, baseUrl } = useApi()
  const { payments } = usePayments()
  const [data, setData] = useState<Loaded>(EMPTY)
  const [revealed, setRevealed] = useState<Record<string, number>>({})
  const requestId = useRef(0)
  const paymentId = payment?.id ?? null
  // Re-fetch when the payment itself moved (owner action, settlement) even if the run was complete.
  const stamp = payment ? `${payment.lifecycle}:${payment.status}:${payment.auditNotes.length}` : ''

  const load = useCallback(async () => {
    if (!paymentId) return
    const id = ++requestId.current
    await Promise.resolve() // the mock path is synchronous otherwise; keep state updates off the effect tick
    if (mode === 'mock') {
      const p = payments.find((x) => x.id === paymentId)
      if (!p || id !== requestId.current) return
      setData({ forId: paymentId, timeline: mockTimelineFor(p, payments), error: null, loading: false })
      return
    }
    if (id !== requestId.current) return
    setData((prev) => (prev.forId === paymentId ? { ...prev, loading: true } : { forId: paymentId, timeline: null, error: null, loading: true }))
    try {
      const t = await fetchTimeline(baseUrl, paymentId)
      if (id === requestId.current) setData({ forId: paymentId, timeline: t, error: null, loading: false })
    } catch (err) {
      if (id === requestId.current) setData((prev) => ({ forId: paymentId, timeline: prev.forId === paymentId ? prev.timeline : null, error: err instanceof Error ? err.message : String(err), loading: false }))
    }
  }, [paymentId, mode, payments, baseUrl])

  // New selection or a lifecycle change on the same payment: load.
  // `stamp` is a dependency on purpose.
  useEffect(() => {
    void load()
  }, [paymentId, mode, stamp, load])

  const current = data.forId === paymentId ? data : EMPTY
  const timeline = current.timeline
  const total = timeline?.steps.length ?? 0
  const shown = mode === 'mock' && paymentId ? Math.min(revealed[paymentId] ?? 0, total) : total

  // Live polling while the run is in progress (and a slow heartbeat afterwards).
  useEffect(() => {
    if (mode !== 'live' || !paymentId || paused) return
    const every = timeline && !timeline.complete ? RUNNING_POLL_MS : SETTLED_POLL_MS
    const t = setInterval(() => void load(), every)
    return () => clearInterval(t)
  }, [mode, paymentId, paused, timeline, load])

  // Mock replay: reveal one step at a time the first time an invoice is opened.
  useEffect(() => {
    if (mode !== 'mock' || !paymentId || paused || total === 0 || shown >= total) return
    const t = setTimeout(() => setRevealed((prev) => ({ ...prev, [paymentId]: Math.min((prev[paymentId] ?? 0) + 1, total) })), MOCK_REVEAL_MS)
    return () => clearTimeout(t)
  }, [mode, paymentId, paused, total, shown])

  const refresh = useCallback(() => void load(), [load])
  return { timeline, visible: shown, loading: current.loading, error: current.error, refresh }
}

/**
 * While the pane is open in live mode, watch /v1/runs: a run that is still executing means new cards are
 * about to appear, so the payment list is reloaded until the run settles. Returns the ids of active runs.
 */
export function useLiveRuns(enabled: boolean, pollMs = RUNNING_POLL_MS): string[] {
  const { api, mode } = useApi()
  const { reload } = usePayments()
  const [active, setActive] = useState<string[]>([])
  const wasActive = useRef(false)

  useEffect(() => {
    if (!enabled || mode !== 'live') return
    let cancelled = false
    const tick = async () => {
      try {
        const runs = await api.listRuns()
        if (cancelled) return
        const running = runs.filter((r) => r.status === 'running').map((r) => r.id)
        setActive((prev) => (prev.length === running.length && prev.every((id, i) => id === running[i]) ? prev : running))
        if (running.length > 0 || wasActive.current) void reload()
        wasActive.current = running.length > 0
      } catch {
        /* polling errors are silent */
      }
    }
    void tick()
    const t = setInterval(() => void tick(), pollMs)
    return () => {
      cancelled = true
      clearInterval(t)
    }
  }, [enabled, mode, api, reload, pollMs])

  return enabled && mode === 'live' ? active : []
}
