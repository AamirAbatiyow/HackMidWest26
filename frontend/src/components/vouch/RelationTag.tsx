import type { Payment } from '@/api/types'
import { cn } from '@/lib/utils'

/** Reverse links: which payments point at this one. */
export function relatedTo(p: Payment, all: Payment[]) {
  const duplicates = all.filter((x) => x.relation?.kind === 'duplicate_of' && x.relation.paymentId === p.id)
  const partner = p.relation ? all.find((x) => x.id === p.relation!.paymentId) : undefined
  return { duplicates, partner }
}

interface RelationTagProps {
  label: string
  onJump?: () => void
  muted?: boolean
  className?: string
}

/** Small square tag; clickable when it points somewhere. */
export function RelationTag({ label, onJump, muted, className }: RelationTagProps) {
  const base = 'num inline-flex h-[18px] shrink-0 items-center rounded-xs border px-1 text-2xs leading-none whitespace-nowrap'
  if (!onJump) return <span className={cn(base, 'border-border text-muted-foreground', className)}>{label}</span>
  return (
    <button
      type="button"
      className={cn(base, muted ? 'border-border text-muted-foreground hover:text-foreground' : 'border-amber/40 text-amber hover:bg-amber-soft', 'outline-none focus-visible:ring-1 focus-visible:ring-ring', className)}
      onClick={(e) => {
        e.stopPropagation()
        onJump()
      }}
      title="Jump to the linked invoice"
    >
      {label}
    </button>
  )
}
