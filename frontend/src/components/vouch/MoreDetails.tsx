import { useState, type ReactNode } from 'react'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { cn } from '@/lib/utils'

/** Collapsed-by-default section for technical detail. */
export function MoreDetails({ children, className, label = 'More details' }: { children: ReactNode; className?: string; label?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <Collapsible open={open} onOpenChange={setOpen} className={cn('border-t', className)}>
      <CollapsibleTrigger className="flex h-8 w-full items-center gap-1.5 px-3 text-xs text-muted-foreground outline-none hover:text-foreground focus-visible:ring-1 focus-visible:ring-ring">
        <span className="num w-2 text-2xs" aria-hidden="true">
          {open ? '▾' : '▸'}
        </span>
        {label}
      </CollapsibleTrigger>
      <CollapsibleContent className="px-3 pb-2">{children}</CollapsibleContent>
    </Collapsible>
  )
}
