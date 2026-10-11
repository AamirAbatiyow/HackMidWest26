import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useApi } from '@/api/ApiProvider'
import { buildFeedScript, runEventToFeedEvent, type FeedAgent, type FeedEvent, type FeedLevel } from '@/data/feed'
import { cn } from '@/lib/utils'
import { usePayments } from '@/store/PaymentsProvider'
import { useUi } from '@/store/UiProvider'

const KEEP = 12
const BACKLOG = 8
const LIVE_POLL_MS = 2000

type Step = 'read' | 'screen' | 'check' | 'score' | 'policy' | 'intake' | 'settlement'
const STEP_OF: Record<FeedAgent, Step> = {
  reader: 'read',
  screener: 'screen',
  checker: 'check',
  scorer: 'score',
  policy: 'policy',
  writer: 'policy',
  intake: 'intake',
  settlement: 'settlement',
}
const STEPS: Step[] = ['intake', 'read', 'screen', 'check', 'score', 'policy', 'settlement']

const levelTone: Record<FeedLevel, string> = { info: 'text-muted-foreground', ok: 'text-foreground/85', flag: 'text-amber', hold: 'text-amber' }
const levelGlyph: Record<FeedLevel, string> = { info: '·', ok: '✓', flag: '!', hold: '■' }

/**
 * Agent log. Collapsed: a 36px rail with a live dot and the number of
 * checks completed. Expanded: the last 12 events grouped by step.
 * In live mode, polls /v1/runs for real events; falls back to generated script in mock mode.
 */
export function AgentFeed({ className }: { className?: string }) {
  const { payments, reload } = usePayments()
  const { api, mode } = useApi()
  const { activeId, open, feedOpen, setFeedOpen, feedPaused, setFeedPaused } = useUi()
  const script = useMemo(() => buildFeedScript(payments), [payments])
  const [events, setEvents] = useState<FeedEvent[]>([])
  const [checksDone, setChecksDone] = useState(0)
  const cursor = useRef(0)
  const seq = useRef(0)
  const lastEventSeq = useRef<Record<string, number>>({})
  const prevPaymentCount = useRef(payments.length)

  const pollLiveEvents = useCallback(async () => {
    try {
      const runs = await api.listRuns()
      const activeRuns = runs.filter((r) => r.status === 'running' || r.status === 'awaiting_approval')
      let newEvents: FeedEvent[] = []
      for (const run of activeRuns.slice(0, 3)) {
        const afterSeq = lastEventSeq.current[run.id] ?? 0
        const result = await api.getRunEvents(run.id, afterSeq)
        for (const ev of result.events) {
          const feedEv = runEventToFeedEvent(ev, payments)
          if (feedEv) {
            newEvents.push(feedEv)
            lastEventSeq.current[run.id] = Math.max(lastEventSeq.current[run.id] ?? 0, ev.seq)
          }
        }
      }
      if (newEvents.length > 0) {
        setEvents((prev) => [...prev.slice(-(KEEP - newEvents.length)), ...newEvents])
        const checkerEvents = newEvents.filter((e) => e.agent === 'checker').length
        if (checkerEvents > 0) setChecksDone((n) => n + checkerEvents)
      }
      if (payments.length !== prevPaymentCount.current) {
        prevPaymentCount.current = payments.length
        void reload()
      }
    } catch {
      /* polling errors are silent */
    }
  }, [api, payments, reload])

  useEffect(() => {
    if (script.length === 0) return
    const n = Math.min(BACKLOG, script.length)
    const stride = Math.max(1, Math.floor(script.length / n))
    const seed = Array.from({ length: n }, (_, i) => script[(i * stride + i) % script.length]!)
    setEvents(seed.map((line, i) => ({ ...line, id: `f-${seq.current++}`, at: Date.now() - (n - i) * 900 })))
    cursor.current = Math.floor(script.length / 2)
    setChecksDone(Math.floor(script.length / 2 / Math.max(1, script.length / n)) * 3 + seed.filter((l) => l.agent === 'checker').length)
  }, [script])

  useEffect(() => {
    if (feedPaused) return
    if (mode === 'live') {
      void pollLiveEvents()
      const t = setInterval(() => void pollLiveEvents(), LIVE_POLL_MS)
      return () => clearInterval(t)
    }
    if (script.length === 0) return
    let timer: ReturnType<typeof setTimeout>
    const tick = () => {
      const line = script[cursor.current % script.length]!
      cursor.current = (cursor.current + 1) % script.length
      setEvents((prev) => [...prev.slice(-(KEEP - 1)), { ...line, id: `f-${seq.current++}`, at: Date.now() }])
      if (line.agent === 'checker') setChecksDone((n) => n + 1)
      timer = setTimeout(tick, 900 + Math.random() * 900)
    }
    timer = setTimeout(tick, 900)
    return () => clearTimeout(timer)
  }, [feedPaused, script, mode, pollLiveEvents])

  const grouped = STEPS.map((step) => ({ step, items: events.filter((e) => STEP_OF[e.agent] === step) })).filter((g) => g.items.length > 0)
  const status = `${checksDone} checks done`

  if (!feedOpen) {
    return (
      <button
        type="button"
        onClick={() => setFeedOpen(true)}
        className={cn('flex w-topbar shrink-0 flex-col items-center gap-2 border-r bg-background pt-3 text-muted-foreground outline-none hover:text-foreground focus-visible:ring-1 focus-visible:ring-ring', className)}
        aria-label={`Agent log · ${status}. Expand.`}
        aria-expanded={false}
      >
        <span className={cn('size-1.5 rounded-xs', feedPaused ? 'bg-muted-foreground/60' : 'bg-accent-cool animate-pulse-soft')} aria-hidden="true" />
        <span className="num text-2xs whitespace-nowrap [writing-mode:vertical-rl]">{status}</span>
      </button>
    )
  }

  return (
    <section aria-label="Agent log" className={cn('flex w-[260px] shrink-0 flex-col border-r bg-background', className)}>
      <header className="flex h-8 shrink-0 items-center justify-between gap-2 border-b px-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className={cn('size-1.5 rounded-xs', feedPaused ? 'bg-muted-foreground/60' : 'bg-accent-cool animate-pulse-soft')} aria-hidden="true" />
          <h2 className="num text-xs text-foreground/85">{status}</h2>
        </div>
        <div className="flex items-center gap-0.5">
          <button type="button" className="num h-5 rounded-xs px-1.5 text-2xs text-muted-foreground hover:bg-surface-2 hover:text-foreground" onClick={() => setFeedPaused(!feedPaused)} aria-pressed={feedPaused}>
            {feedPaused ? 'resume' : 'pause'}
          </button>
          <button type="button" className="num h-5 rounded-xs px-1.5 text-2xs text-muted-foreground hover:bg-surface-2 hover:text-foreground" onClick={() => setFeedOpen(false)} aria-label="Collapse agent log">
            ‹
          </button>
        </div>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {grouped.map((g) => (
          <section key={g.step} className="border-b last:border-b-0">
            <h3 className="label-caps flex h-6 items-center bg-surface-1 px-3">{g.step}</h3>
            <ol>
              {g.items.map((e) => {
                const selected = e.paymentId === activeId
                return (
                  <li
                    key={e.id}
                    className={cn('animate-feed-in grid min-h-row cursor-default grid-cols-[10px_72px_minmax(0,1fr)] items-baseline gap-x-1.5 px-3 py-1 text-xs hover:bg-surface-2', selected && 'bg-accent-cool-soft')}
                    onClick={() => open(e.paymentId)}
                  >
                    <span className={cn('num text-center', levelTone[e.level])} aria-label={e.level}>
                      {levelGlyph[e.level]}
                    </span>
                    <span className="num truncate text-muted-foreground">{e.ref}</span>
                    <span className={cn('leading-4 break-words', e.level === 'flag' || e.level === 'hold' ? 'text-amber' : 'text-foreground/85')}>{e.text}</span>
                  </li>
                )
              })}
            </ol>
          </section>
        ))}
      </div>
      <footer className="num flex h-6 shrink-0 items-center border-t px-3 text-2xs text-muted-foreground">last {events.length} events</footer>
    </section>
  )
}
