import { formatMoney } from '@/lib/format'
import { cn } from '@/lib/utils'

interface MoneyProps {
  amount: number
  className?: string
  cents?: boolean
}

/** Every amount renders in monospace, tabular numerals. */
export function Money({ amount, className, cents }: MoneyProps) {
  return <span className={cn('num', className)}>{formatMoney(amount, { cents })}</span>
}
