import { Landmark, Copy, UserSearch, ShieldCheck } from 'lucide-react'
import type { RiskType } from '@/api/types'
import { cn } from '@/lib/utils'

export const RISK_META: Record<RiskType, { label: string; icon: typeof Landmark }> = {
  changed_bank: { label: 'Changed bank details', icon: Landmark },
  duplicate_or_split: { label: 'Duplicate or split invoice', icon: Copy },
  unrecognized_vendor: { label: 'Unrecognized vendor', icon: UserSearch },
  none: { label: 'No concerns found', icon: ShieldCheck },
}

interface RiskTagProps {
  risk: RiskType
  className?: string
  /** Render the "none" variant too (default hides it). */
  showNone?: boolean
}

export function RiskTag({ risk, className, showNone = false }: RiskTagProps) {
  if (risk === 'none' && !showNone) return null
  const { label, icon: Icon } = RISK_META[risk]
  return (
    <span
      className={cn(
        'inline-flex h-6 items-center gap-1.5 rounded-md border border-dashed px-2 text-xs font-medium text-muted-foreground',
        risk === 'none' ? 'border-vouched-ring text-vouched' : 'border-border',
        className,
      )}
    >
      <Icon className="size-3.5" aria-hidden="true" />
      {label}
    </span>
  )
}
