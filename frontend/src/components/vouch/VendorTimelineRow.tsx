import type { TimelineEvent } from '@/api/types'
import { formatDate } from '@/lib/format'
import { cn } from '@/lib/utils'

const kindCode: Record<TimelineEvent['kind'], string> = {
  payment: 'PAY',
  change: 'CHG',
  onboard: 'ONB',
  check: 'CHK',
  note: 'NOTE',
}

interface VendorTimelineRowProps {
  event: TimelineEvent
  className?: string
}

/** One history row: date · kind · title · detail. Bank changes read in amber. */
export function VendorTimelineRow({ event, className }: VendorTimelineRowProps) {
  const isChange = event.kind === 'change'
  return (
    <li className={cn('grid min-h-row grid-cols-[64px_36px_minmax(0,1fr)] items-baseline gap-2 border-b py-1.5 last:border-b-0', className)}>
      <time dateTime={event.date} className="num text-xs text-muted-foreground">
        {formatDate(event.date, { year: '2-digit', month: '2-digit', day: '2-digit' })}
      </time>
      <span className={cn('num text-2xs tracking-[0.04em]', isChange ? 'text-amber' : 'text-muted-foreground')}>{kindCode[event.kind]}</span>
      <div className="min-w-0">
        <p className={cn('truncate text-sm', isChange ? 'text-amber' : 'text-foreground')}>{event.title}</p>
        {event.detail && <p className="truncate text-xs text-muted-foreground">{event.detail}</p>}
      </div>
    </li>
  )
}
