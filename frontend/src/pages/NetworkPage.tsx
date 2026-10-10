import { Cpu, Database, Globe, Lock, RefreshCw, Server, Smartphone, Waypoints } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'
import { useApi } from '@/api/ApiProvider'
import { useAsync } from '@/api/useAsync'
import { Button } from '@/components/ui/button'
import { ErrorState, StatSkeleton } from '@/components/vouch/States'
import { formatInt } from '@/lib/format'
import { cn } from '@/lib/utils'

const NODES = [
  { id: 'owner', label: 'Owner app', icon: Smartphone, x: 60 },
  { id: 'lb', label: 'NodeBalancer', icon: Waypoints, x: 290 },
  { id: 'api', label: 'API', icon: Server, x: 520 },
  { id: 'model', label: 'Private model server', icon: Cpu, x: 790, y: 60 },
  { id: 'db', label: 'Postgres', icon: Database, x: 790, y: 190 },
] as const

function Stat({ label, value, hint, icon }: { label: string; value: ReactNode; hint?: string; icon: ReactNode }) {
  return (
    <div className="card-surface p-5">
      <p className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
        <span aria-hidden="true">{icon}</span>
        {label}
      </p>
      <p className="mt-2 text-2xl font-semibold tracking-[-0.02em] money">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

function Topology({ privateHops }: { privateHops: Set<string> }) {
  const W = 900
  const H = 250
  const y = 125
  const node = (id: string) => NODES.find((n) => n.id === id)!
  const pos = (id: string) => {
    const n = node(id)
    return { x: n.x, y: 'y' in n ? n.y : y }
  }
  const links: Array<[string, string]> = [
    ['owner', 'lb'],
    ['lb', 'api'],
    ['api', 'model'],
    ['api', 'db'],
  ]

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-labelledby="topo-title topo-desc">
      <title id="topo-title">Vouch corridor topology</title>
      <desc id="topo-desc">
        Owner app connects to the NodeBalancer over TLS. The balancer, API, private model server, and Postgres sit on a private network with locked links.
      </desc>
      {links.map(([a, b]) => {
        const pa = pos(a)
        const pb = pos(b)
        const isPrivate = privateHops.has(`${a}-${b}`)
        const mx = (pa.x + pb.x) / 2
        const my = (pa.y + pb.y) / 2
        return (
          <g key={`${a}-${b}`}>
            <path
              d={`M${pa.x + 80},${pa.y} C${mx},${pa.y} ${mx},${pb.y} ${pb.x - 80},${pb.y}`}
              fill="none"
              className={cn(isPrivate ? 'stroke-vouched' : 'stroke-navy-400')}
              strokeWidth="2"
              strokeDasharray={isPrivate ? undefined : '6 4'}
            />
            <g transform={`translate(${mx - 11}, ${my - 11})`}>
              <circle cx="11" cy="11" r="11" className={cn(isPrivate ? 'fill-vouched-soft stroke-vouched-ring' : 'fill-card stroke-border')} />
              <foreignObject width="22" height="22">
                <div className="flex size-[22px] items-center justify-center">
                  {isPrivate ? <Lock className="size-3 text-vouched" aria-label="Private link" /> : <Globe className="size-3 text-muted-foreground" aria-label="Public TLS" />}
                </div>
              </foreignObject>
            </g>
          </g>
        )
      })}
      <rect x="200" y="12" width="690" height="226" rx="16" className="fill-vouched-soft/40 stroke-vouched-ring" strokeDasharray="4 4" />
      <text x="214" y="34" className="fill-vouched text-[11px] font-semibold">
        Private network · no public ingress
      </text>
      {NODES.map((n) => {
        const p = pos(n.id)
        const Icon = n.icon
        return (
          <g key={n.id} transform={`translate(${p.x - 80}, ${p.y - 26})`}>
            <rect width="160" height="52" rx="12" className="fill-card stroke-border" />
            <foreignObject width="160" height="52">
              <div className="flex h-[52px] items-center gap-2.5 px-3.5">
                <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                  <Icon className="size-4" aria-hidden="true" />
                </span>
                <span className="text-[13px] leading-tight font-medium">{n.label}</span>
              </div>
            </foreignObject>
          </g>
        )
      })}
    </svg>
  )
}

export function NetworkPage() {
  const { api } = useApi()
  const { data, loading, error, reload } = useAsync(() => api.getNetwork(), [api])

  useEffect(() => {
    const t = setInterval(reload, 8000)
    return () => clearInterval(t)
  }, [reload])

  const privateHops = new Set<string>()
  if (data) {
    const key: Record<string, string> = {
      'Owner app': 'owner',
      NodeBalancer: 'lb',
      API: 'api',
      'Private model server': 'model',
      Postgres: 'db',
    }
    for (const h of data.hops) if (h.isPrivate) privateHops.add(`${key[h.from] ?? h.from}-${key[h.to] ?? h.to}`)
  }

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[1.75rem] font-semibold tracking-[-0.02em]">The corridor</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            The path an invoice takes from your screen to a decision. Every hop inside the dashed box is private.
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          {data && <span>Updated {new Date(data.updatedAt).toLocaleTimeString()}</span>}
          <Button variant="outline" size="sm" onClick={reload} disabled={loading}>
            <RefreshCw data-icon="inline-start" className={cn(loading && 'animate-spin')} aria-hidden="true" />
            Refresh
          </Button>
        </div>
      </header>

      {error ? (
        <ErrorState message={error.message} onRetry={reload} />
      ) : !data ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <StatSkeleton key={i} />
          ))}
        </div>
      ) : (
        <>
          <section className="card-surface p-6" aria-label="Topology">
            <Topology privateHops={privateHops} />
          </section>

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Stat label="Model version" value={<span className="text-base">{data.modelVersion}</span>} hint={`Region ${data.region}`} icon={<Cpu className="size-4" />} />
            <Stat
              label="Policy checks passed"
              value={`${formatInt(data.policyChecks.passed)} / ${formatInt(data.policyChecks.total)}`}
              hint="Today, across all payments"
              icon={<Lock className="size-4" />}
            />
            <Stat
              label="Tokens today"
              value={formatInt(data.tokens.promptToday + data.tokens.completionToday)}
              hint={`${formatInt(data.tokens.promptToday)} in · ${formatInt(data.tokens.completionToday)} out`}
              icon={<Waypoints className="size-4" />}
            />
            <Stat label="Tokens per payment" value={formatInt(data.tokens.perPaymentAvg)} hint="Average, read-and-explain only" icon={<Server className="size-4" />} />
          </div>

          <section className="card-surface overflow-hidden" aria-labelledby="latency-heading">
            <div className="border-b px-6 py-4">
              <h2 id="latency-heading" className="text-sm font-semibold">
                Live latency per hop
              </h2>
              <p className="mt-0.5 text-xs text-muted-foreground">p50 is the typical round trip; p95 is the slow end.</p>
            </div>
            <ul className="divide-y">
              {data.hops.map((h) => {
                const maxP95 = Math.max(...data.hops.map((x) => x.p95Ms))
                return (
                  <li key={h.id} className="grid items-center gap-x-6 gap-y-2 px-6 py-4 sm:grid-cols-[1fr_auto_auto_12rem]">
                    <p className="flex items-center gap-2 text-sm font-medium">
                      {h.isPrivate ? (
                        <Lock className="size-3.5 text-vouched" aria-label="Private link" />
                      ) : (
                        <Globe className="size-3.5 text-muted-foreground" aria-label="Public TLS link" />
                      )}
                      {h.from} <span className="text-muted-foreground">→</span> {h.to}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      p50 <span className="font-medium text-foreground money">{h.p50Ms} ms</span>
                    </p>
                    <p className="text-xs text-muted-foreground">
                      p95 <span className="font-medium text-foreground money">{h.p95Ms} ms</span>
                    </p>
                    <div className="relative h-2 w-full overflow-hidden rounded-full bg-foreground/[0.06]" aria-hidden="true">
                      <div className="absolute inset-y-0 left-0 rounded-full bg-navy-200 dark:bg-navy-600 transition-[width] duration-500" style={{ width: `${(h.p95Ms / maxP95) * 100}%` }} />
                      <div className="absolute inset-y-0 left-0 rounded-full bg-primary transition-[width] duration-500" style={{ width: `${(h.p50Ms / maxP95) * 100}%` }} />
                    </div>
                  </li>
                )
              })}
            </ul>
          </section>
        </>
      )}
    </div>
  )
}
