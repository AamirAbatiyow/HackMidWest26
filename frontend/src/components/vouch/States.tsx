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
    <div className={cn('flex flex-col items-center justify-center px-4 py-10 text-center', className)}>
      <span className="flex size-8 items-center justify-center rounded-sm border text-muted-foreground">
        {icon ?? <Inbox className="size-3.5" aria-hidden="true" />}
      </span>
      <p className="mt-3 text-sm font-medium">{title}</p>
      {description && <p className="mt-0.5 max-w-xs text-xs text-muted-foreground">{description}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  )
}

interface ErrorStateProps {
  title?: string
  message?: string
  onRetry?: () => void
  className?: string
}

export function ErrorState({ title = 'Load failed', message, onRetry, className }: ErrorStateProps) {
  return (
    <div role="alert" className={cn('flex flex-col items-center justify-center px-4 py-10 text-center', className)}>
      <span className="flex size-8 items-center justify-center rounded-sm border border-red/50 bg-red-soft text-red">
        <TriangleAlert className="size-3.5" aria-hidden="true" />
      </span>
      <p className="mt-3 text-sm font-medium">{title}</p>
      {message && <p className="num mt-0.5 max-w-sm text-xs break-words text-muted-foreground">{message}</p>}
      <p className="mt-1 text-xs text-muted-foreground">No payment was sent. State unchanged.</p>
      {onRetry && (
        <Button variant="outline" size="sm" className="mt-3" onClick={onRetry}>
          <RefreshCw data-icon="inline-start" aria-hidden="true" />
          Retry
        </Button>
      )}
    </div>
  )
}

export function RowSkeleton({ className }: { className?: string }) {
  return (
    <div className={cn('grid h-9 grid-cols-[14px_1fr_80px_90px_60px] items-center gap-3 border-b px-3', className)} aria-hidden="true">
      <Skeleton className="h-2.5 w-3.5 rounded-xs" />
      <Skeleton className="h-2.5 w-2/3" />
      <Skeleton className="h-2.5 w-16" />
      <Skeleton className="h-4 w-20 rounded-sm" />
      <Skeleton className="h-2.5 w-12" />
    </div>
  )
}

export function BlockSkeleton({ className }: { className?: string }) {
  return (
    <div className={cn('space-y-2 p-3', className)} aria-hidden="true">
      <Skeleton className="h-2.5 w-24" />
      <Skeleton className="h-5 w-32" />
      <Skeleton className="h-2.5 w-full" />
      <Skeleton className="h-2.5 w-5/6" />
    </div>
  )
}

export function LoadingRows({ count = 6 }: { count?: number }) {
  return (
    <div role="status" aria-live="polite" aria-label="Loading">
      {Array.from({ length: count }, (_, i) => (
        <RowSkeleton key={i} />
      ))}
      <span className="sr-only">Loading</span>
    </div>
  )
}
