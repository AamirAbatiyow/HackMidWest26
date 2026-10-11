import { API_BASE_URL, useApi } from '@/api/ApiProvider'
import { cn } from '@/lib/utils'

/** A live dot and one plain line. Technical detail stays in the tooltip. */
export function StatusBar() {
  const { mode, health } = useApi()
  const live = mode === 'live'
  const title = live
    ? 'Payments over $2,500, and every flagged invoice, wait for your approval.'
    : `Demo data. ${health?.reason ?? `API at ${API_BASE_URL} unreachable.`}`

  return (
    <footer className="flex h-strip shrink-0 items-center gap-2 overflow-hidden border-t bg-background px-3 text-2xs" aria-label="Status" title={title}>
      <span className={cn('size-1.5 shrink-0 rounded-full', live ? 'animate-pulse bg-green' : 'bg-amber')} aria-hidden="true" />
      <span className="truncate text-foreground/85">{live ? 'Live' : 'Demo data'}</span>
    </footer>
  )
}
