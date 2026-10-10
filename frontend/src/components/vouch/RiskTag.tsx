import type { RiskType } from '@/api/types'
import { cn } from '@/lib/utils'

export const RISK_META: Record<RiskType, { label: string; code: string; tone: string }> = {
  changed_bank: { label: 'Changed bank details', code: 'BANK-CHG', tone: 'text-amber border-amber/40' },
  duplicate_or_split: { label: 'Duplicate or split invoice', code: 'DUP-SPLIT', tone: 'text-amber border-amber/40' },
  unrecognized_vendor: { label: 'Unrecognized vendor', code: 'UNREC', tone: 'text-red border-red/50' },
  none: { label: 'No concerns found', code: 'CLEAR', tone: 'text-muted-foreground border-border' },
}

interface RiskTagProps {
  risk: RiskType
  className?: string
  showNone?: boolean
  variant?: 'short' | 'full'
}

/** Risk class tag. Amber for bank/dup, red for a confirmed shared-detail ring. */
export function RiskTag({ risk, className, showNone = true, variant = 'short' }: RiskTagProps) {
  if (risk === 'none' && !showNone) return null
  const { label, code, tone } = RISK_META[risk]
  return (
    <span
      className={cn('inline-flex h-[18px] items-center rounded-xs border px-1 text-2xs leading-none whitespace-nowrap', variant === 'short' && 'num tracking-[0.04em]', tone, className)}
      title={label}
    >
      {variant === 'short' ? code : label}
    </span>
  )
}
