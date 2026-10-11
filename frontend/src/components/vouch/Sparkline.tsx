import { cn } from '@/lib/utils'

interface SparklineProps {
  values: number[]
  width?: number
  height?: number
  className?: string
  /** 'line' for trends, 'bars' for counts. */
  kind?: 'line' | 'bars'
  tone?: 'neutral' | 'amber' | 'accent'
  /** Optional reference line (same units as values). */
  reference?: number
  label?: string
}

const STROKE = { neutral: 'stroke-foreground/70', amber: 'stroke-amber', accent: 'stroke-accent-cool' }
const FILL = { neutral: 'fill-foreground/60', amber: 'fill-amber', accent: 'fill-accent-cool' }

/** Tiny inline chart; 12–16px tall, no axes, mono caption lives outside. */
export function Sparkline({ values, width = 72, height = 14, className, kind = 'line', tone = 'neutral', reference, label }: SparklineProps) {
  if (values.length === 0) return null
  const min = Math.min(...values, reference ?? Infinity)
  const max = Math.max(...values, reference ?? -Infinity)
  const span = max - min || 1
  const y = (v: number) => height - 1 - ((v - min) / span) * (height - 2)
  const step = width / Math.max(1, values.length - (kind === 'line' ? 1 : 0))
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className={cn('inline-block shrink-0 align-middle', className)} role="img" aria-label={label ?? `Trend of ${values.length} points`}>
      {reference != null && <line x1={0} x2={width} y1={y(reference)} y2={y(reference)} className="stroke-foreground/20" strokeDasharray="2 2" strokeWidth={1} />}
      {kind === 'line' ? (
        <polyline fill="none" strokeWidth={1} className={STROKE[tone]} points={values.map((v, i) => `${i * step},${y(v)}`).join(' ')} />
      ) : (
        values.map((v, i) => <rect key={i} x={i * step + 0.5} y={y(v)} width={Math.max(1, step - 1.5)} height={height - 1 - y(v)} className={FILL[tone]} />)
      )}
    </svg>
  )
}
