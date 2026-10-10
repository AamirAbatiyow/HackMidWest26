import type { Lifecycle, VouchStatus } from '@/api/types'
import { cn } from '@/lib/utils'

export const STATUS_META: Record<VouchStatus, { label: string; code: string; description: string }> = {
  vouched: { label: 'Vouched', code: 'VCH', description: 'Checked and explained. Clear to pay.' },
  quick_check: { label: 'Quick check', code: 'QCK', description: 'Held for a quick check.' },
  verify: { label: 'Verify before release', code: 'VER', description: 'Call-back required before release.' },
}

/** Row left-border and tag colors per status. Vouched stays neutral; color is for risk. */
export const STATUS_TONE: Record<VouchStatus, { tag: string; border: string }> = {
  vouched: { tag: 'border-border text-vouched', border: 'border-l-vouched/60' },
  quick_check: { tag: 'border-amber/50 text-amber', border: 'border-l-amber' },
  verify: { tag: 'border-amber/60 bg-amber-soft text-amber', border: 'border-l-amber' },
}

const lifecycleMeta: Partial<Record<Lifecycle, { label: string; code: string; className: string }>> = {
  held: { label: 'On hold', code: 'HLD', className: 'border-border text-muted-foreground' },
  settled: { label: 'Settled', code: 'STL', className: 'border-border text-muted-foreground' },
  approved: { label: 'Verified', code: 'VRF', className: 'border-accent-cool/50 text-accent-cool' },
}

interface StatusChipProps {
  status: VouchStatus
  lifecycle?: Lifecycle
  /** short = 3-letter code, full = label */
  variant?: 'short' | 'full'
  className?: string
}

/** Square-cornered status tag. Text always carries the meaning. */
export function StatusChip({ status, lifecycle, variant = 'full', className }: StatusChipProps) {
  const override = lifecycle && lifecycle !== 'pending' && lifecycle !== 'appealed' ? lifecycleMeta[lifecycle] : undefined
  const label = override?.label ?? STATUS_META[status].label
  const code = override?.code ?? STATUS_META[status].code
  return (
    <span
      className={cn(
        'inline-flex h-[18px] shrink-0 items-center rounded-xs border px-1 text-xs leading-none whitespace-nowrap',
        override?.className ?? STATUS_TONE[status].tag,
        variant === 'short' && 'num text-2xs tracking-[0.04em]',
        className,
      )}
      title={override ? label : STATUS_META[status].description}
    >
      {variant === 'short' ? code : label}
    </span>
  )
}
