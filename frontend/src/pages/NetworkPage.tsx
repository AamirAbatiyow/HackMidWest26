import { useApi } from '@/api/ApiProvider'
import { useAsync } from '@/api/useAsync'
import { Sparkline } from '@/components/vouch/Sparkline'
import { ErrorState, LoadingRows } from '@/components/vouch/States'
import { Block, DenseTable, PageFrame, Td, Th } from '@/components/vouch/Table'
import { series } from '@/data/series'
import { formatDateTime, formatInt } from '@/lib/format'
import { cn } from '@/lib/utils'

/** Fixed topology for the diagram: nodes by name, laid out left to right. */
const LAYOUT: Record<string, { x: number; y: number }> = {
  'Owner app': { x: 16, y: 70 },
  NodeBalancer: { x: 250, y: 70 },
  API: { x: 484, y: 70 },
  'Private model server': { x: 740, y: 30 },
  Postgres: { x: 740, y: 110 },
}
const NODE_W = 140
const NODE_H = 28

export function NetworkPage() {
  const { api } = useApi()
  const { data, error, loading, reload } = useAsync(() => api.getNetwork(), [api])

  if (error) return <ErrorState message={error.message} onRetry={reload} />
  if (loading || !data) return <LoadingRows count={6} />

  const publicHops = data.hops.filter((h) => !h.isPrivate).length
  const names = Array.from(new Set(data.hops.flatMap((h) => [h.from, h.to])))

  return (
    <PageFrame
      summary={`${data.region} · ${data.hops.length} hops · ${publicHops} public hop · ${data.hops.length - publicHops} private`}
      aside={<span>updated {formatDateTime(data.updatedAt)}</span>}
    >
      <Block title="Topology" meta="p50 / p95 per hop · dashed = private network">
        <svg viewBox="0 0 900 150" className="block h-auto w-full max-w-[1000px]" role="img" aria-label="Request path from the owner app to the model server and database">
          {data.hops.map((h) => {
            const a = LAYOUT[h.from]
            const b = LAYOUT[h.to]
            if (!a || !b) return null
            const x1 = a.x + NODE_W
            const y1 = a.y + NODE_H / 2
            const x2 = b.x
            const y2 = b.y + NODE_H / 2
            const mx = (x1 + x2) / 2
            const my = (y1 + y2) / 2
            return (
              <g key={h.id}>
                <line x1={x1} y1={y1} x2={x2} y2={y2} className={cn('stroke-foreground/40')} strokeWidth={1} strokeDasharray={h.isPrivate ? '3 3' : undefined} />
                <text x={mx} y={my - 6} textAnchor="middle" fontSize={9.5} fontFamily="var(--font-mono)" className="fill-foreground/85">
                  {h.p50Ms} / {h.p95Ms} ms
                </text>
              </g>
            )
          })}
          {names.map((n) => {
            const p = LAYOUT[n]
            if (!p) return null
            const isModel = /model/i.test(n)
            return (
              <g key={n} transform={`translate(${p.x}, ${p.y})`}>
                <rect width={NODE_W} height={NODE_H} rx={2} className={cn('fill-background', isModel ? 'stroke-accent-cool' : 'stroke-border')} strokeWidth={1} />
                <text x={8} y={18} fontSize={11} fontFamily="var(--font-sans)" className="fill-foreground">
                  {n}
                </text>
              </g>
            )
          })}
        </svg>
      </Block>

      <Block title="Hops" meta="latency by segment">
        <DenseTable>
          <thead>
            <tr>
              <Th width={48}>#</Th>
              <Th>From</Th>
              <Th>To</Th>
              <Th width={88} right>
                p50
              </Th>
              <Th width={88} right>
                p95
              </Th>
              <Th width={120}>60 min</Th>
              <Th width={96}>Network</Th>
              <Th>Note</Th>
            </tr>
          </thead>
          <tbody>
            {data.hops.map((h, i) => (
              <tr key={h.id} className="row-interactive">
                <Td num muted className="text-xs">
                  {i + 1}
                </Td>
                <Td className="text-foreground">{h.from}</Td>
                <Td className="text-foreground">{h.to}</Td>
                <Td num right className="text-foreground">
                  {h.p50Ms} ms
                </Td>
                <Td num right className={cn(h.p95Ms > 400 ? 'text-amber' : undefined)}>
                  {h.p95Ms} ms
                </Td>
                <Td>
                  <Sparkline values={series(h.id, 24, h.p50Ms, h.p50Ms * 0.6)} label={`${h.from} to ${h.to} p50 trend`} />
                </Td>
                <Td num className="text-xs">
                  {h.isPrivate ? 'private' : 'public'}
                </Td>
                <Td muted className="text-xs">
                  {/model/i.test(h.to) ? 'model inference dominates; amounts never pass through the model' : h.isPrivate ? 'VPC only · no public egress' : 'TLS 1.3 · owner session'}
                </Td>
              </tr>
            ))}
          </tbody>
        </DenseTable>
      </Block>

      <Block title="Runtime" meta={data.modelVersion}>
        <DenseTable>
          <thead>
            <tr>
              <Th>Metric</Th>
              <Th width={260} right>
                Value
              </Th>
              <Th>Note</Th>
            </tr>
          </thead>
          <tbody>
            {[
              ['Model', data.modelVersion, 'private weights · no third-party inference'],
              ['Region', data.region, 'single region · data never leaves'],
              ['Prompt tokens today', formatInt(data.tokens.promptToday), 'PII masked before context'],
              ['Completion tokens today', formatInt(data.tokens.completionToday), 'model writes explanations only'],
              ['Tokens per payment (avg)', formatInt(data.tokens.perPaymentAvg), ''],
              ['Policy mode', 'default-deny', 'nothing moves without owner approval'],
            ].map(([k, v, note]) => (
              <tr key={k} className="row-interactive">
                <Td>{k}</Td>
                <Td num right className="text-foreground">
                  {v}
                </Td>
                <Td muted className="text-xs">
                  {note}
                </Td>
              </tr>
            ))}
          </tbody>
        </DenseTable>
      </Block>
    </PageFrame>
  )
}
