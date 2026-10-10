import { ChevronRight, Zap, CheckCheck, PauseCircle } from 'lucide-react'
import type { Payment } from '@/api/types'
import { describeDue } from '@/lib/format'
import { cn } from '@/lib/utils'
import { CountryFlag } from './CountryFlag'
import { Money } from './Money'
import { RiskTag } from './RiskTag'
import { StatusChip } from './StatusChip'
import { TrustMeter } from './TrustMeter'

interface PaymentCardProps {
  payment: Payment
  onOpen?: (payment: Payment) => void
  selected?: boolean
  className?: string
  /** Compact variant used in lists inside the approval sheet. */
  compact?: boolean
}

export function FastPayBadge({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        'inline-flex h-6 items-center gap-1 rounded-full bg-vouched px-2 text-[11px] font-semibold text-white dark:text-navy-950',
        className,
      )}
    >
      <Zap className="size-3" aria-hidden="true" />
      Pay today, full amount, no fee
    </span>
  )
}

export function PaymentCard({ payment, onOpen, selected, className, compact }: PaymentCardProps) {
  const settled = payment.lifecycle === 'settled'
  const held = payment.lifecycle === 'held'
  const tone =
    payment.status === 'vouched' ? 'border-l-vouched' : 'border-l-attention'

  return (
    <article
      className={cn(
        'card-surface group relative border-l-[3px] text-left',
        tone,
        onOpen && 'cursor-pointer hover:-translate-y-px hover:shadow-card-hover',
        selected && 'ring-2 ring-ring/40',
        settled && 'opacity-70',
        className,
      )}
    >
      <button
        type="button"
        onClick={() => onOpen?.(payment)}
        disabled={!onOpen}
        aria-label={`Open evidence for ${payment.vendor.name}, invoice ${payment.invoiceNumber}`}
        className={cn(
          'flex w-full items-start gap-4 rounded-[inherit] p-5 text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50',
          compact && 'p-4',
        )}
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <h3 className="flex min-w-0 items-center gap-2 text-[15px] font-semibold tracking-[-0.01em]">
              <CountryFlag country={payment.vendor.country} />
              <span className="truncate">{payment.vendor.name}</span>
            </h3>
            <span className="text-xs text-muted-foreground">
              {payment.vendor.city} · Invoice <span className="font-medium text-foreground/80 tabular-nums">{payment.invoiceNumber}</span>
            </span>
          </div>

          <div className={cn('mt-3 flex flex-wrap items-end justify-between gap-x-6 gap-y-3')}>
            <div>
              <Money amount={payment.amount} className={cn('block font-semibold tracking-[-0.02em]', compact ? 'text-2xl' : 'text-[2rem] leading-none')} />
              <p className="mt-1.5 text-xs text-muted-foreground tabular-nums">{describeDue(payment.dueDate)}</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {settled ? (
                <span className="inline-flex h-7 items-center gap-1.5 rounded-full bg-muted px-2.5 text-[13px] font-medium text-muted-foreground">
                  <CheckCheck className="size-4" aria-hidden="true" /> Settled
                </span>
              ) : held ? (
                <span className="inline-flex h-7 items-center gap-1.5 rounded-full bg-muted px-2.5 text-[13px] font-medium text-muted-foreground">
                  <PauseCircle className="size-4" aria-hidden="true" /> On hold
                </span>
              ) : (
                <StatusChip status={payment.status} />
              )}
              <RiskTag risk={payment.risk} />
            </div>
          </div>

          {!compact && (
            <>
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                <TrustMeter score={payment.trustScore} />
                {payment.fastPayEligible && !settled && <FastPayBadge />}
              </div>
              <p className="mt-3 text-sm leading-relaxed text-foreground/85">{payment.reason}</p>
            </>
          )}
        </div>

        {onOpen && (
          <ChevronRight
            className="mt-1 size-5 shrink-0 text-muted-foreground/60 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-foreground"
            aria-hidden="true"
          />
        )}
      </button>
    </article>
  )
}
