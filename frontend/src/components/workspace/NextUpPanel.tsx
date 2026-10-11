import { cn } from '@/lib/utils'
import { usePayments } from '@/store/PaymentsProvider'
import { useUi } from '@/store/UiProvider'
import { Shortcut } from './Shortcut'

/** Panel content when no row is open: what needs action, and how to move. */
export function NextUpPanel({ className }: { className?: string }) {
  const { payments, batchReady } = usePayments()
  const { open } = useUi()
  const openRows = payments.filter((p) => p.lifecycle !== 'settled')
  const needsAction = openRows.filter((p) => p.status !== 'vouched' && p.lifecycle !== 'approved')
  const next = needsAction[0]

  return (
    <aside className={cn('flex min-h-0 flex-col bg-background', className)} aria-label="Next up">
      <header className="flex h-8 shrink-0 items-center border-b px-3">
        <h2 className="text-sm font-medium">Next up</h2>
      </header>
      <div className="px-3 py-1">
        <div className="flex h-6 items-center justify-between border-b text-xs">
          <span className="text-muted-foreground">Needs you</span>
          <span className="num text-foreground">{needsAction.length}</span>
        </div>
        <div className="flex h-6 items-center justify-between border-b text-xs">
          <span className="text-green">Ready to pay</span>
          <span className="num text-green">{batchReady.length}</span>
        </div>
        {next && (
          <button type="button" className="flex h-6 w-full items-center justify-between text-xs outline-none hover:text-foreground focus-visible:ring-1 focus-visible:ring-ring" onClick={() => open(next.id)}>
            <span className="text-muted-foreground">Review first</span>
            <span className="text-foreground">{next.vendor.name}</span>
          </button>
        )}
      </div>
      <p className="num flex flex-wrap items-center gap-x-3 gap-y-1 border-t px-3 py-2 text-2xs text-muted-foreground">
        <span>
          <Shortcut id="open" /> open
        </span>
        <span>
          <Shortcut id="approve" /> approve
        </span>
        <span>
          <Shortcut id="help" /> shortcuts
        </span>
      </p>
    </aside>
  )
}
