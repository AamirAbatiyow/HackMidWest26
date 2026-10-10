import { Building2, Landmark, MapPin, Phone } from 'lucide-react'
import type { RingGraph, RingNode } from '@/api/types'
import { cn } from '@/lib/utils'

interface NetworkMiniGraphProps {
  graph: RingGraph
  className?: string
}

const W = 420
const H = 240

/** Fixed layout: vendors on the left column, shared facts on the right. */
function layout(nodes: RingNode[]): Record<string, { x: number; y: number }> {
  const vendors = nodes.filter((n) => n.kind === 'vendor')
  const facts = nodes.filter((n) => n.kind !== 'vendor')
  const pos: Record<string, { x: number; y: number }> = {}
  vendors.forEach((n, i) => {
    pos[n.id] = { x: 96, y: 40 + (i * (H - 80)) / Math.max(1, vendors.length - 1) }
  })
  facts.forEach((n, i) => {
    pos[n.id] = { x: W - 96, y: 40 + (i * (H - 80)) / Math.max(1, facts.length - 1) }
  })
  return pos
}

const factIcon: Record<RingNode['kind'], typeof Building2> = {
  vendor: Building2,
  bank: Landmark,
  phone: Phone,
  address: MapPin,
}

export function NetworkMiniGraph({ graph, className }: NetworkMiniGraphProps) {
  const pos = layout(graph.nodes)
  const degree: Record<string, number> = {}
  for (const e of graph.edges) {
    degree[e.to] = (degree[e.to] ?? 0) + 1
    degree[e.from] = (degree[e.from] ?? 0) + 1
  }

  return (
    <figure className={cn('card-surface overflow-hidden bg-muted/40 p-3', className)}>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-labelledby="ring-title ring-desc">
        <title id="ring-title">Shared details between vendors</title>
        <desc id="ring-desc">
          {graph.nodes.filter((n) => n.kind === 'vendor').map((n) => n.label).join(', ')} share{' '}
          {graph.nodes.filter((n) => n.kind !== 'vendor').map((n) => n.label).join(', ')}.
        </desc>
        {graph.edges.map((e, i) => {
          const a = pos[e.from]
          const b = pos[e.to]
          if (!a || !b) return null
          const shared = (degree[e.to] ?? 0) > 1
          return (
            <path
              key={i}
              d={`M${a.x + 70},${a.y} C${(a.x + b.x) / 2},${a.y} ${(a.x + b.x) / 2},${b.y} ${b.x - 70},${b.y}`}
              fill="none"
              className={cn(shared ? 'stroke-attention' : 'stroke-foreground/25')}
              strokeWidth={shared ? 2 : 1.25}
              strokeDasharray={shared ? undefined : '3 3'}
            />
          )
        })}
        {graph.nodes.map((n) => {
          const p = pos[n.id]
          const Icon = factIcon[n.kind]
          const isFact = n.kind !== 'vendor'
          return (
            <g key={n.id} transform={`translate(${p.x - 70}, ${p.y - 16})`}>
              <rect
                width="140"
                height="32"
                rx="10"
                className={cn(
                  'stroke-1',
                  n.focus
                    ? 'fill-attention-soft stroke-attention'
                    : isFact
                      ? 'fill-card stroke-attention-ring'
                      : 'fill-card stroke-border',
                )}
              />
              <foreignObject x="0" y="0" width="140" height="32">
                <div className="flex h-8 items-center gap-1.5 px-2.5 text-[11px] font-medium leading-none">
                  <Icon className={cn('size-3 shrink-0', isFact ? 'text-attention' : n.focus ? 'text-attention' : 'text-muted-foreground')} aria-hidden="true" />
                  <span className="truncate">{n.label}</span>
                </div>
              </foreignObject>
            </g>
          )
        })}
      </svg>
      <figcaption className="mt-1 px-1 text-xs text-muted-foreground">
        Solid amber lines are details shared by more than one vendor.
      </figcaption>
    </figure>
  )
}
