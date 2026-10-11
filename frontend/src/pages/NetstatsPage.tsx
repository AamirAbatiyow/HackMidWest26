import { useApi } from '@/api/ApiProvider'
import type { LatencyStats, TopologyData } from '@/api/types'
import { useAsync } from '@/api/useAsync'
import { Sparkline } from '@/components/vouch/Sparkline'
import { ErrorState, LoadingRows } from '@/components/vouch/States'
import { Block, DenseTable, PageFrame, Td, Th } from '@/components/vouch/Table'
import { series } from '@/data/series'
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
            <span className="num w-12 text-right text-foreground">{s.latencyMs ?? '—'} ms</span>
          </div>
        )
      })}
    </div>
  )
}

function StatTile({ label, value, unit = 'ms', tone = 'neutral', sparkValues }: { label: string; value: number | null; unit?: string; tone?: 'neutral' | 'amber' | 'accent'; sparkValues?: number[] }) {
  return (
    <div className="flex flex-col gap-1 rounded-sm border bg-surface-1/50 p-3">
      <span className="text-2xs uppercase tracking-wider text-muted-foreground">{label}</span>
      <div className="flex items-end justify-between gap-2">
        <span className={cn('num text-lg font-medium', tone === 'amber' ? 'text-amber' : tone === 'accent' ? 'text-accent-cool' : 'text-foreground')}>
          {value != null ? `${value} ${unit}` : '—'}
        </span>
        {sparkValues && sparkValues.length > 0 && <Sparkline values={sparkValues} tone={tone} width={56} height={16} />}
      </div>
    </div>
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

  const totalP50 = Object.values(latency.pipelineSteps).reduce((s, v) => s + (v.p50Ms ?? 0), 0)
  const totalP95 = Object.values(latency.pipelineSteps).reduce((s, v) => s + (v.p95Ms ?? 0), 0)
  const configuredTiers = Object.values(latency.tiers).filter((t) => t.configured).length
  const healthyTiers = Object.values(latency.tiers).filter((t) => t.healthy === true).length

  return (
    <PageFrame
      summary={`${latency.region} · p50 ${totalP50}ms · p95 ${totalP95}ms · ${configuredTiers} tiers configured · ${healthyTiers} healthy`}
      aside={<span>updated {formatDateTime(latency.updatedAt)}</span>}
    >
      <Block title="Akamai Network Topology" meta="live RTT badges · dashed = private network">
        <div className="overflow-x-auto p-4">
          <TopologyDiagram topology={topology} latency={latency} />
        </div>
      </Block>

      <Block title="Latency Overview" meta="p50/p95 sparklines">
        <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-3 lg:grid-cols-6">
          <StatTile label="Pipeline p50" value={totalP50} tone="accent" sparkValues={series('pipeline-p50', 24, totalP50, totalP50 * 0.5)} />
          <StatTile label="Pipeline p95" value={totalP95} tone={totalP95 > 300 ? 'amber' : 'neutral'} sparkValues={series('pipeline-p95', 24, totalP95, totalP95 * 0.5)} />
          <StatTile label="Inference p50" value={latency.inference['hackathon-chat']?.p50Ms ?? null} sparkValues={series('inf-p50', 24, latency.inference['hackathon-chat']?.p50Ms ?? 100, 80)} />
          <StatTile label="Postgres p50" value={latency.postgres.p50Ms} tone="accent" sparkValues={series('pg-p50', 24, latency.postgres.p50Ms ?? 3, 1)} />
          <StatTile label="Object Storage" value={latency.objectStorage.p50Ms} sparkValues={series('obj-p50', 24, latency.objectStorage.p50Ms ?? 15, 5)} />
          <StatTile label="Decider ({latency.decider.engine})" value={latency.decider.p50Ms} sparkValues={series('decider-p50', 24, latency.decider.p50Ms ?? 85, 40)} />
        </div>
      </Block>

      {latency.lastRunWaterfall && (
        <Block title="Latest Run Waterfall" meta={latency.lastRunWaterfall.runId}>
          <div className="max-w-xl px-4 py-2">
            <WaterfallChart steps={latency.lastRunWaterfall.steps} />
          </div>
        </Block>
      )}

      <Block title="Pipeline Steps" meta="rolling p50/p95 over last N runs">
        <DenseTable>
          <thead>
            <tr>
              <Th>Step</Th>
              <Th width={80} right>p50</Th>
              <Th width={80} right>p95</Th>
              <Th width={80} right>Latest</Th>
              <Th width={80} right>Count</Th>
              <Th width={100}>Trend</Th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(latency.pipelineSteps).map(([step, stats]) => (
              <tr key={step} className="row-interactive">
                <Td className="text-foreground capitalize">{step.replace(/_/g, ' ')}</Td>
                <Td num right className="text-foreground">{stats.p50Ms ?? '—'} ms</Td>
                <Td num right className={cn(stats.p95Ms && stats.p95Ms > 100 ? 'text-amber' : undefined)}>
                  {stats.p95Ms ?? '—'} ms
                </Td>
                <Td num right>{stats.latestMs ?? '—'} ms</Td>
                <Td num right muted>{stats.count}</Td>
                <Td>
                  <Sparkline values={series(step, 24, stats.p50Ms ?? 10, (stats.p50Ms ?? 10) * 0.5)} label={`${step} p50 trend`} />
                </Td>
              </tr>
            ))}
          </tbody>
        </DenseTable>
      </Block>

      <Block title="Akamai Hosted Inference" meta="hackathon-chat, hackathon-embedding">
        <DenseTable>
          <thead>
            <tr>
              <Th>Endpoint</Th>
              <Th width={180}>Model</Th>
              <Th width={60}>Live</Th>
              <Th width={80} right>p50</Th>
              <Th width={80} right>p95</Th>
              <Th width={80} right>Calls</Th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(latency.inference).map(([endpoint, stats]) => (
              <tr key={endpoint} className="row-interactive">
                <Td className="text-foreground">{endpoint}</Td>
                <Td muted className="text-xs">{stats.model}</Td>
                <Td>
                  <span className={cn('inline-block h-2 w-2 rounded-full', stats.live ? 'bg-emerald-500' : 'bg-muted-foreground')} />
                </Td>
                <Td num right className="text-foreground">{stats.p50Ms ?? '—'} ms</Td>
                <Td num right className={cn(stats.p95Ms && stats.p95Ms > 500 ? 'text-amber' : undefined)}>
                  {stats.p95Ms ?? '—'} ms
                </Td>
                <Td num right muted>{stats.count}</Td>
              </tr>
            ))}
          </tbody>
        </DenseTable>
      </Block>

      <Block title="Tier Map" meta="ingress / app / model / data subnets">
        <DenseTable>
          <thead>
            <tr>
              <Th>Tier</Th>
              <Th>Subnet</Th>
              <Th>Akamai Products</Th>
              <Th width={100}>Status</Th>
              <Th width={80} right>RTT</Th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(latency.tiers).map(([tierId, tier]) => (
              <tr key={tierId} className="row-interactive">
                <Td className={cn('font-medium', TIER_TEXT_COLORS[tierId])}>{tier.name}</Td>
                <Td className="num text-xs">{tier.subnet}</Td>
                <Td muted className="text-xs">{tier.products.join(' · ')}</Td>
                <Td>
                  {tier.configured ? (
                    <span className={cn('inline-flex items-center gap-1 text-xs', tier.healthy ? 'text-emerald-500' : tier.healthy === false ? 'text-red-500' : 'text-muted-foreground')}>
                      <span className={cn('h-1.5 w-1.5 rounded-full', tier.healthy ? 'bg-emerald-500' : tier.healthy === false ? 'bg-red-500' : 'bg-muted-foreground')} />
                      {tier.healthy ? 'healthy' : tier.healthy === false ? 'error' : 'unknown'}
                    </span>
                  ) : (
                    <span className="text-xs text-muted-foreground">not configured</span>
                  )}
                </Td>
                <Td num right className="text-foreground">{tier.rttMs ?? '—'} ms</Td>
              </tr>
            ))}
          </tbody>
        </DenseTable>
      </Block>

      {topology.firewall.configured && topology.firewall.rules.length > 0 && (
        <Block title="Firewall Rules" meta={topology.firewall.label}>
          <DenseTable>
            <thead>
              <tr>
                <Th width={80}>Direction</Th>
                <Th width={80}>Protocol</Th>
                <Th width={80}>Ports</Th>
                <Th>Source/Dest</Th>
                <Th width={80}>Action</Th>
                <Th>Label</Th>
              </tr>
            </thead>
            <tbody>
              {topology.firewall.rules.map((rule) => (
                <tr key={rule.id} className="row-interactive">
                  <Td className={cn('text-xs', rule.direction === 'inbound' ? 'text-accent-cool' : 'text-amber')}>{rule.direction}</Td>
                  <Td className="num text-xs">{rule.protocol}</Td>
                  <Td className="num text-xs">{rule.ports}</Td>
                  <Td className="num text-xs">{rule.source ?? rule.destination ?? '—'}</Td>
                  <Td className={cn('text-xs font-medium', rule.action === 'ACCEPT' ? 'text-emerald-500' : 'text-red-500')}>{rule.action}</Td>
                  <Td muted className="text-xs">{rule.label}</Td>
                </tr>
              ))}
            </tbody>
          </DenseTable>
        </Block>
      )}
    </PageFrame>
  )
}
