import { useEffect } from 'react'
import { useApi } from '@/api/ApiProvider'
import { useAsync } from '@/api/useAsync'
import { formatInt } from '@/lib/format'

function Cell({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <span className="flex items-center gap-1.5 whitespace-nowrap" title={title}>
      <span className="text-muted-foreground/70">{label}</span>
      <span className="text-foreground/85">{value}</span>
    </span>
  )
}

/** Three facts only: latency p50, tokens today, policy mode. The rest lives on Network. */
export function StatusBar() {
  const { api, health } = useApi()
  const { data, reload } = useAsync(() => api.getNetwork(), [api])

  useEffect(() => {
    const t = setInterval(reload, 5000)
    return () => clearInterval(t)
  }, [reload])

  const p50 = health?.latencyMs ?? (data ? data.hops.reduce((s, h) => s + h.p50Ms, 0) : null)
  const tokens = data ? data.tokens.promptToday + data.tokens.completionToday : null

  return (
    <footer className="num flex h-strip shrink-0 items-center gap-6 overflow-hidden border-t bg-background px-3 text-2xs" aria-label="Status">
      <Cell label="latency p50" value={p50 == null ? '—' : `${p50}ms`} />
      <Cell label="tokens today" value={tokens == null ? '—' : formatInt(tokens)} />
      <Cell label="policy" value="default-deny" title="No payout executes without explicit owner approval." />
    </footer>
  )
}
