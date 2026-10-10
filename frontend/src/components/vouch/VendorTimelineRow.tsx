import { ArrowLeftRight, CircleDollarSign, Handshake, SearchCheck, StickyNote } from 'lucide-react'
import type { TimelineEvent } from '@/api/types'
import { formatDate } from '@/lib/format'
import { cn } from '@/lib/utils'

const icons: Record<TimelineEvent['kind'], typeof CircleDollarSign> = {
  payment: CircleDollarSign,
  change: ArrowLeftRight,
  onboard: Handshake,
  check: SearchCheck,
  note: StickyNote,
}

interface VendorTimelineRowProps {
  event: TimelineEvent
  isLast?: boolean
  className?: string
}

export function VendorTimelineRow({ event, isLast, className }: VendorTimelineRowProps) {
  const Icon = icons[event.kind]
  const isChange = event.kind === 'change'
  return (
    <li className={cn('relative flex gap-3 pb-5', isLast && 'pb-0', className)}>
      {!isLast && <span aria-hidden="true" className="absolute top-7 left-[13px] h-[calc(100%-1.75rem)] w-px bg-border" />}
      <span
        className={cn(
          'mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full ring-1 ring-inset',
          isChange ? 'bg-attention-soft text-attention ring-attention-ring' : 'bg-muted text-muted-foreground ring-border',
        )}
      >
        <Icon className="size-3.5" aria-hidden="true" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-3">
          <p className={cn('text-sm font-medium', isChange && 'text-attention')}>{event.title}</p>
          <time dateTime={event.date} className="shrink-0 text-xs text-muted-foreground tabular-nums">
            {formatDate(event.date, { month: 'short', day: 'numeric', year: 'numeric' })}
          </time>
        </div>
        {event.detail && <p className="mt-0.5 text-xs text-muted-foreground">{event.detail}</p>}
      </div>
    </li>
  )
}
