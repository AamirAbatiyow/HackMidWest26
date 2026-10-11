import { cn } from '@/lib/utils'

interface TrustMeterProps {
  /** 0–100 */
  score: number
  className?: string
  showLabel?: boolean
  width?: number
}

export function trustBand(score: number): { label: string; tone: 'strong' | 'building' | 'new' } {
  if (score >= 85) return { label: 'strong', tone: 'strong' }
  if (score >= 55) return { label: 'building', tone: 'building' }
  return { label: 'new', tone: 'new' }
}

/** Thin inline bar plus the number. The number is the primary signal. */
export function TrustMeter({ score, className, showLabel = false, width = 40 }: TrustMeterProps) {
  const clamped = Math.max(0, Math.min(100, Math.round(score)))
  const band = trustBand(clamped)
  const fill = band.tone === 'new' ? 'bg-amber' : 'bg-foreground/70'
  return (
    <span className={cn('inline-flex items-center gap-1.5', className)}>
      <span
        role="meter"
        aria-label="Vendor trust"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={clamped}
        aria-valuetext={`${clamped} of 100, ${band.label}`}
        className="relative block h-[3px] overflow-hidden rounded-xs bg-foreground/12"
        style={{ width }}
      >
        <span className={cn('absolute inset-y-0 left-0', fill)} style={{ width: `${clamped}%` }} aria-hidden="true" />
      </span>
      <span className="num text-xs text-foreground/85">{String(clamped).padStart(2, '0')}</span>
      {showLabel && <span className="text-2xs text-muted-foreground">{band.label}</span>}
    </span>
  )
}
