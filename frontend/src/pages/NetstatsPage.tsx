import { useApi } from '@/api/ApiProvider'
import type { LatencyStats, TopologyData } from '@/api/types'
import { useAsync } from '@/api/useAsync'
import { EmptyState, ErrorState, LoadingRows } from '@/components/vouch/States'
import { Block, PageFrame } from '@/components/vouch/Table'
import { COST_LINE, compactWaterfall, EMPTY_TIMINGS_DESCRIPTION, EMPTY_TIMINGS_TITLE, hasTimings } from '@/data/netstats'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'

const TIER_COLORS: Record<string, string> = {
  ingress: 'stroke-amber fill-amber/10',
  app: 'stroke-accent-cool fill-accent-cool/10',
  model: 'stroke-purple-400 fill-purple-400/10',
  data: 'stroke-emerald-400 fill-emerald-400/10',
}

const TIER_TEXT_COLORS: Record<string, string> = {
  ingress: 'text-amber',
  app: 'text-accent-cool',
  model: 'text-purple-400',
  data: 'text-emerald-400',
}

const NODE_W = 110
const NODE_H = 32

/** "12 ms", or a plain dash when nothing was measured (never "— ms"). */
function ms(v: number | null | undefined): string {
  return v == null ? '—' : `${v} ms`
}

function TopologyDiagram({ topology, latency }: { topology: TopologyData; latency: LatencyStats }) {
  const nodeMap = new Map(topology.nodes.map((n) => [n.id, n]))
  const tierRtt: Record<string, number | null> = {}
  for (const [tierId, tierStats] of Object.entries(latency.tiers)) {
    tierRtt[tierId] = tierStats.rttMs
  }

  return (
    <svg viewBox="0 0 920 200" className="block h-auto w-full max-w-[960px]" role="img" aria-label="Network topology diagram">
      {Object.entries(topology.tiers).map(([tierId, tier]) => {
        const tieredNodes = topology.nodes.filter((n) => n.tier === tierId)
        if (tieredNodes.length === 0) return null
        const minX = Math.min(...tieredNodes.map((n) => n.x)) - 20
        const maxX = Math.max(...tieredNodes.map((n) => n.x)) + NODE_W + 20
        const minY = Math.min(...tieredNodes.map((n) => n.y)) - 28
        const maxY = Math.max(...tieredNodes.map((n) => n.y)) + NODE_H + 12
        return (
          <g key={tierId}>
            <rect
              x={minX}
              y={minY}
              width={maxX - minX}
              height={maxY - minY}
              rx={6}
              className={cn('stroke-1', TIER_COLORS[tierId] ?? 'stroke-border fill-surface-1/30')}
              strokeDasharray="4 2"
            />
            <text x={minX + 8} y={minY + 14} fontSize={9} className={cn('font-medium', TIER_TEXT_COLORS[tierId] ?? 'fill-muted-foreground')}>
              {tier.name}
            </text>
          </g>
        )
      })}

      {topology.edges.map((edge) => {
        const fromNode = nodeMap.get(edge.from)
        const toNode = nodeMap.get(edge.to)
        if (!fromNode || !toNode) return null
        const x1 = fromNode.x + NODE_W
        const y1 = fromNode.y + NODE_H / 2
        const x2 = toNode.x
        const y2 = toNode.y + NODE_H / 2
        const mx = (x1 + x2) / 2
        const my = (y1 + y2) / 2
        return (
          <g key={edge.id}>
            <line
              x1={x1}
              y1={y1}
              x2={x2}
              y2={y2}
              className="stroke-foreground/40"
              strokeWidth={1}
              strokeDasharray={edge.private ? '3 3' : undefined}
            />
            {edge.label && (
              <text x={mx} y={my - 4} textAnchor="middle" fontSize={8} className="fill-muted-foreground">
                {edge.label}
              </text>
            )}
          </g>
        )
      })}

      {topology.nodes.map((node) => {
        const tierColor = node.tier ? TIER_COLORS[node.tier] : 'stroke-border'
        const rtt = node.tier ? tierRtt[node.tier] : null
        const isConfigured = node.configured !== false
        return (
          <g key={node.id} transform={`translate(${node.x}, ${node.y})`} className={cn(!isConfigured && 'opacity-40')}>
            <rect
              width={NODE_W}
              height={NODE_H}
              rx={4}
              className={cn('fill-background', tierColor)}
              strokeWidth={1}
            />
            <text x={8} y={14} fontSize={10} className="fill-foreground font-medium">
              {node.label}
            </text>
            {node.product && (
              <text x={8} y={26} fontSize={7} className="fill-muted-foreground">
                {node.product.replace('Akamai ', '')}
              </text>
            )}
            {rtt != null && (
              <g transform={`translate(${NODE_W - 4}, -6)`}>
                <rect x={-20} y={0} width={24} height={12} rx={2} className="fill-accent-cool/20" />
                <text x={-8} y={9} textAnchor="middle" fontSize={8} className="fill-accent-cool num">
                  {rtt}ms
                </text>
              </g>
            )}
          </g>
        )
      })}
    </svg>
  )
}

function WaterfallChart({ steps }: { steps: { step: string; latencyMs: number | null }[] }) {
  const maxMs = Math.max(...steps.map((s) => s.latencyMs ?? 0), 1)
  let cumulative = 0

  return (
    <div className="space-y-1 py-2">
      {steps.map((s, i) => {
        const width = s.latencyMs != null ? (s.latencyMs / maxMs) * 100 : 0
        const offset = (cumulative / maxMs) * 100
        if (s.latencyMs != null) cumulative += s.latencyMs
        const label = s.step.replace(/_/g, ' ').replace('detector ', '').replace(/^\w/, (c) => c.toUpperCase())
        return (
          <div key={s.step} className="flex items-center gap-2 text-xs">
            <span className="w-28 truncate text-right text-muted-foreground">{label}</span>
            <div className="relative h-4 flex-1 rounded-xs bg-surface-1">
              <div
                className={cn('absolute top-0 h-4 rounded-xs', i % 2 === 0 ? 'bg-accent-cool/70' : 'bg-accent-cool/50')}
                style={{ left: `${offset}%`, width: `${Math.max(width, 1)}%` }}
              />
            </div>
            <span className="num w-12 text-right text-foreground">{ms(s.latencyMs)}</span>
          </div>
        )
      })}
    </div>
  )
}

/** One number, one line of context. No sparkline: there is nothing honest to draw from a handful of runs. */
function StatTile({ label, value, note, tone = 'neutral' }: { label: string; value: number | null; note: string; tone?: 'neutral' | 'accent' }) {
  return (
    <div className="flex min-w-0 flex-col gap-1 rounded-sm border bg-surface-1/50 p-3">
      <span className="truncate text-2xs tracking-wider text-muted-foreground uppercase">{label}</span>
      <span className={cn('num text-lg font-medium', tone === 'accent' ? 'text-accent-cool' : 'text-foreground')}>{ms(value)}</span>
      <span className="num truncate text-2xs text-muted-foreground">{note}</span>
    </div>
  )
}

/** One sentence on what the stack costs, set against one median fraud case. */
export function CostLine() {
  return (
    <p className="num max-w-3xl px-3 py-4 text-xs leading-relaxed text-muted-foreground" data-testid="cost-line">
      {COST_LINE.before}
      <a href={COST_LINE.linkHref} target="_blank" rel="noreferrer" className="text-accent-cool underline-offset-2 hover:underline">
        {COST_LINE.linkText}
      </a>
      {COST_LINE.after}
    </p>
  )
}

function p95Note(p95: number | null, count: number, unit = 'calls'): string {
  return `${p95 != null ? `p95 ${p95} ms · ` : ''}${count} ${unit}`
}

function storeNote(store: { configured: boolean; ok: boolean | null; p95Ms: number | null }): string {
  if (!store.configured) return 'not configured'
  const health = store.ok ? 'ok' : store.ok === false ? 'error' : 'unknown'
  return store.p95Ms != null ? `p95 ${store.p95Ms} ms · ${health}` : health
}

/** The few numbers that matter, then one compact per-step waterfall. */
function Timings({ latency }: { latency: LatencyStats }) {
  const chat = latency.inference['hackathon-chat']
  const embedding = latency.inference['hackathon-embedding']
  const waterfall = compactWaterfall(latency)
  return (
    <>
      <Block title="Key Timings" meta="p50 per component">
        <div className="grid grid-cols-2 gap-3 p-3 sm:grid-cols-3 lg:grid-cols-5">
          <StatTile label="hackathon-chat" value={chat?.p50Ms ?? null} tone="accent" note={chat ? p95Note(chat.p95Ms, chat.count) : 'not configured'} />
          <StatTile label="hackathon-embedding" value={embedding?.p50Ms ?? null} note={embedding ? p95Note(embedding.p95Ms, embedding.count) : 'not configured'} />
          <StatTile label="Postgres" value={latency.postgres.p50Ms} tone="accent" note={storeNote(latency.postgres)} />
          <StatTile label="Object Storage" value={latency.objectStorage.p50Ms} note={storeNote(latency.objectStorage)} />
          <StatTile label={`Decider · ${latency.decider.engine}`} value={latency.decider.p50Ms} note={p95Note(latency.decider.p95Ms, latency.decider.count)} />
        </div>
      </Block>

      {waterfall.steps.length > 0 && (
        <Block title="Per-step Timing" meta={waterfall.runId ? `latest run ${waterfall.runId}` : 'rolling p50'}>
          <div className="max-w-xl px-3 py-1">
            <WaterfallChart steps={waterfall.steps} />
          </div>
        </Block>
      )}
    </>
  )
}

export function NetstatsPage() {
  const { api } = useApi()
  const { data: latency, error: latencyError, loading: latencyLoading, reload: reloadLatency } = useAsync(() => api.getLatency(), [api])
  const { data: topology, error: topologyError, loading: topologyLoading, reload: reloadTopology } = useAsync(() => api.getTopology(), [api])

  const error = latencyError || topologyError
  const loading = latencyLoading || topologyLoading

  const reload = () => {
    reloadLatency()
    reloadTopology()
  }

  if (error) return <ErrorState message={error.message} onRetry={reload} />
  if (loading || !latency || !topology) return <LoadingRows count={8} />

  const live = hasTimings(latency)
  const runs = Math.max(0, ...Object.values(latency.pipelineSteps).map((s) => s.count))
  const configuredTiers = Object.values(latency.tiers).filter((t) => t.configured).length
  const healthyTiers = Object.values(latency.tiers).filter((t) => t.healthy === true).length

  return (
    <PageFrame
      summary={`${latency.region} · ${live ? `${runs} runs timed` : 'no runs yet'} · ${configuredTiers} tiers configured · ${healthyTiers} healthy`}
      aside={<span>updated {formatDateTime(latency.updatedAt)}</span>}
    >
      <Block title="Akamai Network Topology" meta="live RTT badges · dashed = private network">
        <div className="overflow-x-auto p-4">
          <TopologyDiagram topology={topology} latency={latency} />
        </div>
      </Block>

      {live ? (
        <Timings latency={latency} />
      ) : (
        <Block title="Timings" meta="hosted inference · Postgres · Object Storage · Decider · per step">
          <EmptyState title={EMPTY_TIMINGS_TITLE} description={EMPTY_TIMINGS_DESCRIPTION} />
        </Block>
      )}

      <CostLine />
    </PageFrame>
  )
}
