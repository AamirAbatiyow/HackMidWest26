import { CheckCircle2, Clock3, PhoneCall } from 'lucide-react'
import type { VouchStatus } from '@/api/types'
import { cn } from '@/lib/utils'

export const STATUS_META: Record<VouchStatus, { label: string; short: string; description: string }> = {
  vouched: {
    label: 'Vouched',
    short: 'Vouched',
    description: 'Checked and explained. Safe to pay.',
  },
  quick_check: {
    label: 'Quick check',
    short: 'Quick check',
    description: 'Held for a quick check. Usually a one-minute question.',
  },
  verify: {
    label: 'Verify before release',
    short: 'Verify',
    description: 'A short call to your usual contact clears this.',
  },
}

const styles: Record<VouchStatus, string> = {
  vouched: 'bg-vouched-soft text-vouched ring-vouched-ring',
  quick_check: 'bg-attention-soft text-attention ring-attention-ring',
  verify: 'bg-attention-soft text-attention ring-attention-ring',
}

const icons: Record<VouchStatus, typeof CheckCircle2> = {
  vouched: CheckCircle2,
  quick_check: Clock3,
  verify: PhoneCall,
}

interface StatusChipProps {
  status: VouchStatus
  size?: 'sm' | 'md'
  className?: string
}

export function StatusChip({ status, size = 'md', className }: StatusChipProps) {
  const Icon = icons[status]
  const meta = STATUS_META[status]
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center gap-1.5 rounded-full font-medium whitespace-nowrap ring-1 ring-inset transition-colors duration-200',
        size === 'sm' ? 'h-6 px-2 text-xs' : 'h-7 px-2.5 text-[13px]',
        styles[status],
        className,
      )}
      title={meta.description}
    >
      <Icon className={size === 'sm' ? 'size-3.5' : 'size-4'} aria-hidden="true" />
      {meta.label}
    </span>
  )
}
