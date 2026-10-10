import { formatMoney } from '@/lib/format'
import { cn } from '@/lib/utils'

interface MoneyProps {
  amount: number
  className?: string
  cents?: boolean
}

export function Money({ amount, className, cents }: MoneyProps) {
  return <span className={cn('money', className)}>{formatMoney(amount, { cents })}</span>
}
