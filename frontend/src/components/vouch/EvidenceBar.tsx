import { ShieldCheck, TriangleAlert } from 'lucide-react'
import type { EvidenceFactor } from '@/api/types'
import { cn } from '@/lib/utils'

interface EvidenceBarProps {
  factor: EvidenceFactor
  className?: string
  /** Delay the fill-in animation, in ms. */
  delayMs?: number
}

/**
 * One LIME-style horizontal contribution bar. Concerns extend right in amber,
 * reassuring factors extend left in green, from a shared center axis.
 */
export function EvidenceBar({ factor, className, delayMs = 0 }: EvidenceBarProps) {
  const pct = Math.round(Math.max(0.06, Math.min(1, factor.weight)) * 100)
  const concern = factor.direction === 'concern'
  const Icon = concern ? TriangleAlert : ShieldCheck
  return (
    <div className={cn('grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1', className)}>
      <p className="flex min-w-0 items-center gap-1.5 text-sm text-foreground">
        <Icon className={cn('size-3.5 shrink-0', concern ? 'text-attention' : 'text-vouched')} aria-hidden="true" />
        <span className="truncate">{factor.label}</span>
      </p>
      <span className={cn('text-xs font-medium tabular-nums', concern ? 'text-attention' : 'text-vouched')}>
        {concern ? '+' : '−'}
        {pct}
        <span className="sr-only"> {concern ? 'raises concern' : 'reassuring'}</span>
      </span>
      <div className="col-span-2 relative h-2.5 w-full overflow-hidden rounded-full bg-foreground/[0.06]">
        <span className="absolute inset-y-0 left-1/2 w-px bg-foreground/15" aria-hidden="true" />
        <span
          aria-hidden="true"
          className={cn(
            'absolute inset-y-0 rounded-full transition-[width] duration-500 ease-[var(--ease-vouch)]',
            concern ? 'left-1/2 bg-attention' : 'right-1/2 bg-vouched',
          )}
          style={{ width: `${pct / 2}%`, transitionDelay: `${delayMs}ms` }}
        />
      </div>
    </div>
  )
}
