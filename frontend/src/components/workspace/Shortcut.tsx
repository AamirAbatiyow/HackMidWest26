import { SHORTCUTS, type ShortcutId } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

/** Muted inline shortcut hint, e.g. "j k" or "⌘K". */
export function Shortcut({ id, className }: { id: ShortcutId; className?: string }) {
  const { keys, label } = SHORTCUTS[id]
  return (
    <span className={cn('num text-2xs text-muted-foreground/70', className)} aria-label={`Shortcut ${keys.join(' ')} — ${label}`}>
      {keys.join('')}
    </span>
  )
}
