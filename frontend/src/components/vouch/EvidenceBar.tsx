import type { EvidenceFactor } from '@/api/types'
import { cn } from '@/lib/utils'

interface EvidenceBarProps {
  factor: EvidenceFactor
  className?: string
  /** Print the weight. Off in the detail panel; on in the explain dialog. */
  showWeight?: boolean
}

/**
 * LIME-style contribution row. Concerns extend right (amber) from the center
 * axis, reassuring factors extend left (green).
 */
export function EvidenceBar({ factor, className, showWeight = false }: EvidenceBarProps) {
  const pct = Math.round(Math.max(0.06, Math.min(1, factor.weight)) * 100)
  const concern = factor.direction === 'concern'
  return (
    <div className={cn('grid h-row items-center gap-3 border-b last:border-b-0', showWeight ? 'grid-cols-[minmax(0,1fr)_120px_36px]' : 'grid-cols-[minmax(0,1fr)_120px]', className)}>
      <p className="truncate text-sm">
        <span className={cn('num mr-1.5 text-2xs', concern ? 'text-amber' : 'text-green')} aria-hidden="true">
          {concern ? '+' : '−'}
        </span>
        {factor.label}
        <span className="sr-only">, {concern ? 'raises concern' : 'reassuring'}</span>
      </p>
      <div className="relative h-[3px] w-full bg-foreground/10" aria-hidden="true">
        <span className="absolute inset-y-0 left-1/2 w-px bg-foreground/30" />
        <span className={cn('absolute inset-y-0', concern ? 'left-1/2 bg-amber' : 'right-1/2 bg-green')} style={{ width: `${pct / 2}%` }} />
      </div>
      {showWeight && (
        <span className={cn('num text-right text-xs', concern ? 'text-amber' : 'text-green')}>
          {concern ? '+' : '−'}
          {pct}
        </span>
      )}
    </div>
  )
}
