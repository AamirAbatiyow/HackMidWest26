import { cn } from '@/lib/utils'

interface TrustMeterProps {
  /** 0–100 */
  score: number
  className?: string
  /** Show the label text alongside the bar. */
  showLabel?: boolean
  size?: 'sm' | 'md'
}

export function trustBand(score: number): { label: string; tone: 'strong' | 'building' | 'new' } {
  if (score >= 85) return { label: 'Strong', tone: 'strong' }
  if (score >= 55) return { label: 'Building', tone: 'building' }
  return { label: 'New', tone: 'new' }
}

const SEGMENTS = 5

export function TrustMeter({ score, className, showLabel = true, size = 'md' }: TrustMeterProps) {
  const clamped = Math.max(0, Math.min(100, Math.round(score)))
  const filled = Math.round((clamped / 100) * SEGMENTS)
  const band = trustBand(clamped)
  const fill =
    band.tone === 'strong' ? 'bg-vouched' : band.tone === 'building' ? 'bg-navy-400 dark:bg-navy-200' : 'bg-attention'

  return (
    <div className={cn('inline-flex items-center gap-2', className)}>
      <div
        role="meter"
        aria-label="Vendor trust"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={clamped}
        aria-valuetext={`${band.label}, ${clamped} out of 100`}
        className="flex items-center gap-[3px]"
      >
        {Array.from({ length: SEGMENTS }, (_, i) => (
          <span
            key={i}
            className={cn(
              'block rounded-full transition-colors duration-200',
              size === 'sm' ? 'h-1.5 w-3' : 'h-2 w-4',
              i < filled ? fill : 'bg-foreground/10 dark:bg-foreground/15',
            )}
          />
        ))}
      </div>
      {showLabel && (
        <span className={cn('whitespace-nowrap text-muted-foreground', size === 'sm' ? 'text-[11px]' : 'text-xs')}>
          Vendor trust · <span className="font-medium text-foreground">{band.label}</span>
          <span className="sr-only"> ({clamped} of 100)</span>
        </span>
      )}
    </div>
  )
}
