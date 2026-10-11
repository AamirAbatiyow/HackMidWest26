import { useMemo } from 'react'
import type { RingGraph as RingGraphData, RingNode } from '@/api/types'
import { cn } from '@/lib/utils'

const KIND_LABEL: Record<RingNode['kind'], string> = { vendor: 'vendor', bank: 'bank acct', phone: 'phone', address: 'address' }

interface Pos {
  x: number
  y: number
}

/**
 * Shared-detail ring. Focus vendor at the center, shared facts (bank, phone,
 * address) on the inner orbit, linked vendors on the outer orbit. Red marks
 * the shared facts; everything else stays neutral.
 */
export function RingGraph({ graph, className, height = 240 }: { graph: RingGraphData; className?: string; height?: number }) {
  const W = 420
  const H = height
  const cx = W / 2
  const cy = H / 2

  const pos = useMemo(() => {
    const map = new Map<string, Pos>()
    const focus = graph.nodes.find((n) => n.focus) ?? graph.nodes.find((n) => n.kind === 'vendor')
    const facts = graph.nodes.filter((n) => n.kind !== 'vendor')
    const others = graph.nodes.filter((n) => n.kind === 'vendor' && n !== focus)
    if (focus) map.set(focus.id, { x: cx, y: cy })
    const r1 = Math.min(H * 0.3, 78)
    const r2 = Math.min(H * 0.44, 108)
    facts.forEach((n, i) => {
      const a = -Math.PI / 2 + (i / Math.max(1, facts.length)) * Math.PI * 2
      map.set(n.id, { x: cx + Math.cos(a) * Math.min(r1 * 1.5, 104), y: cy + Math.sin(a) * r1 })
    })
    others.forEach((n, i) => {
      const a = -Math.PI / 2 + Math.PI / others.length + (i / Math.max(1, others.length)) * Math.PI * 2
      map.set(n.id, { x: cx + Math.cos(a) * (W / 2 - 78), y: cy + Math.sin(a) * r2 })
    })
    return map
  }, [graph, cx, cy, H, W])

  return (
    <figure className={cn('overflow-hidden rounded-sm border bg-surface-1', className)}>
      <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full" role="img" aria-label="Shared-detail ring">
        {graph.edges.map((e, i) => {
          const a = pos.get(e.from)
          const b = pos.get(e.to)
          if (!a || !b) return null
          return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="stroke-red/60" strokeWidth={1} />
        })}
        {graph.nodes.map((n) => {
          const p = pos.get(n.id)
          if (!p) return null
          const isFact = n.kind !== 'vendor'
          const w = Math.min(132, Math.max(60, n.label.length * 6.2 + 12))
          const h = isFact ? 26 : 22
          return (
            <g key={n.id} transform={`translate(${p.x - w / 2}, ${p.y - h / 2})`}>
              <rect
                width={w}
                height={h}
                rx={2}
                className={cn('fill-background', isFact ? 'stroke-red' : n.focus ? 'stroke-foreground' : 'stroke-border')}
                strokeWidth={1}
              />
              {isFact && (
                <text x={6} y={9} className="fill-red num" fontSize={8} fontFamily="var(--font-mono)" letterSpacing="0.04em">
                  {KIND_LABEL[n.kind].toUpperCase()}
                </text>
              )}
              <text
                x={6}
                y={isFact ? 20 : 15}
                className={cn(isFact ? 'fill-foreground num' : n.focus ? 'fill-foreground' : 'fill-muted-foreground')}
                fontSize={isFact ? 9 : 10.5}
                fontFamily={isFact ? 'var(--font-mono)' : 'var(--font-sans)'}
                fontWeight={n.focus ? 600 : 400}
              >
                {n.label.length > 22 ? `${n.label.slice(0, 21)}…` : n.label}
              </text>
            </g>
          )
        })}
      </svg>
      <figcaption className="num flex h-6 items-center gap-3 border-t px-2 text-2xs text-muted-foreground">
        <span className="text-red">red = shared bank, phone or address</span>
      </figcaption>
    </figure>
  )
}
