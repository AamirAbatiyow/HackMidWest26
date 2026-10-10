import { Inbox, RefreshCw, TriangleAlert } from 'lucide-react'
import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

interface EmptyStateProps {
  title: string
  description?: string
  icon?: ReactNode
  action?: ReactNode
  className?: string
}

export function EmptyState({ title, description, icon, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        'card-surface flex flex-col items-center justify-center px-6 py-14 text-center',
        className,
      )}
    >
      <span className="flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
        {icon ?? <Inbox className="size-5" aria-hidden="true" />}
      </span>
      <h3 className="mt-4 text-base font-semibold">{title}</h3>
      {description && <p className="mt-1 max-w-sm text-sm text-muted-foreground">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

interface ErrorStateProps {
  title?: string
  message?: string
  onRetry?: () => void
  className?: string
}

export function ErrorState({ title = "We couldn't load this", message, onRetry, className }: ErrorStateProps) {
  return (
    <div
      role="alert"
      className={cn(
        'card-surface flex flex-col items-center justify-center border-problem-ring px-6 py-12 text-center',
        className,
      )}
    >
      <span className="flex size-12 items-center justify-center rounded-full bg-problem-soft text-problem">
        <TriangleAlert className="size-5" aria-hidden="true" />
      </span>
      <h3 className="mt-4 text-base font-semibold">{title}</h3>
      {message && <p className="mt-1 max-w-md text-sm text-muted-foreground">{message}</p>}
      <p className="mt-1 text-xs text-muted-foreground">Nothing was paid. Your payments are exactly where you left them.</p>
      {onRetry && (
        <Button variant="outline" className="mt-5" onClick={onRetry}>
          <RefreshCw data-icon="inline-start" aria-hidden="true" />
          Try again
        </Button>
      )}
    </div>
  )
}

export function PaymentCardSkeleton({ className }: { className?: string }) {
  return (
    <div className={cn('card-surface border-l-[3px] border-l-border p-5', className)} aria-hidden="true">
      <div className="flex items-center gap-3">
        <Skeleton className="h-3.5 w-5 rounded-[3px]" />
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-3 w-28" />
      </div>
      <div className="mt-4 flex items-end justify-between">
        <div>
          <Skeleton className="h-8 w-28" />
          <Skeleton className="mt-2 h-3 w-24" />
        </div>
        <div className="flex gap-2">
          <Skeleton className="h-7 w-24 rounded-full" />
          <Skeleton className="h-6 w-36" />
        </div>
      </div>
      <div className="mt-4 flex items-center justify-between">
        <Skeleton className="h-3 w-40" />
      </div>
      <Skeleton className="mt-3 h-3.5 w-3/4" />
    </div>
  )
}

export function StatSkeleton({ className }: { className?: string }) {
  return (
    <div className={cn('card-surface p-5', className)} aria-hidden="true">
      <Skeleton className="h-3 w-24" />
      <Skeleton className="mt-3 h-7 w-32" />
    </div>
  )
}

export function LoadingList({ count = 3 }: { count?: number }) {
  return (
    <div className="space-y-3" role="status" aria-live="polite" aria-label="Loading payments">
      {Array.from({ length: count }, (_, i) => (
        <PaymentCardSkeleton key={i} />
      ))}
      <span className="sr-only">Loading…</span>
    </div>
  )
}
