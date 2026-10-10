import { useEffect, useRef, useState } from 'react'
import { API_BASE_URL, useApi } from '@/api/ApiProvider'
import type { ApiInfo, NetworkStatus } from '@/api/types'
import { formatInt } from '@/lib/format'
import { cn } from '@/lib/utils'

const POLL_MS = 5000

/** Value cell that re-animates when its text changes. */
function Cell({ label, value, title }: { label: string; value: string; title?: string }) {
  const prev = useRef(value)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    if (prev.current !== value) {
      prev.current = value
      setTick((t) => t + 1)
    }
  }, [value])
  return (
    <span className="flex items-center gap-1.5 whitespace-nowrap" title={title}>
      <span className="text-muted-foreground/70">{label}</span>
      <span key={tick} className={cn('text-foreground/85', tick > 0 && 'animate-feed-in')}>
        {value}
      </span>
    </span>
  )
}

/** Three facts only: latency p50, tokens today, policy mode. Source tag on the right. */
export function StatusBar() {
  const { api, mode, health } = useApi()
  const [net, setNet] = useState<NetworkStatus | null>(null)
  const [info, setInfo] = useState<ApiInfo | null>(null)

  useEffect(() => {
    let alive = true
    const poll = async () => {
      const [n, i] = await Promise.allSettled([api.getNetwork(), api.getInfo()])
      if (!alive) return
      setNet(n.status === 'fulfilled' ? n.value : null)
      setInfo(i.status === 'fulfilled' ? i.value : null)
    }
    void poll()
    const t = setInterval(() => void poll(), POLL_MS)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [api])

  const p50 = net?.p50Ms ?? (net && net.hops.length ? net.hops.reduce((s, h) => s + h.p50Ms, 0) : null)
  const tokens = net ? net.tokens.promptToday + net.tokens.completionToday : null
  const policy = info?.policyMode ?? null

  const liveTitle = `Live API at ${API_BASE_URL}${info?.model ? ` · model ${info.model}` : ''}`
  const mockTitle = `Demo data. ${health?.reason ?? `API at ${API_BASE_URL} unreachable.`}`

  return (
    <footer className="num flex h-strip shrink-0 items-center gap-6 overflow-hidden border-t bg-background px-3 text-2xs" aria-label="Status">
      <Cell label="latency p50" value={p50 == null || p50 <= 0 ? '—' : `${Math.round(p50)}ms`} title={net?.p95Ms ? `p95 ${Math.round(net.p95Ms)}ms` : undefined} />
      <Cell label="tokens today" value={tokens == null || tokens <= 0 ? '—' : formatInt(tokens)} />
      <Cell label="policy" value={policy ?? '—'} title="No payout executes without explicit owner approval." />
      <span
        className={cn('ml-auto inline-flex h-4 items-center rounded-xs border px-1 text-2xs tracking-[0.04em]', mode === 'live' ? 'border-accent-cool/50 text-accent-cool' : 'border-amber/50 text-amber')}
        title={mode === 'live' ? liveTitle : mockTitle}
        aria-label={mode === 'live' ? liveTitle : mockTitle}
      >
        {mode}
      </span>
    </footer>
  )
}
