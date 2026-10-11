import { useEffect, useState } from 'react'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { SHORTCUTS, type ShortcutId } from '@/lib/shortcuts'

const GROUPS: { title: string; ids: ShortcutId[] }[] = [
  { title: 'Move', ids: ['next', 'prev', 'open', 'close', 'search', 'palette'] },
  { title: 'Act', ids: ['approve', 'hold', 'verify', 'explain'] },
  { title: 'Go to', ids: ['goPayments', 'goApprove', 'theme'] },
]

export function ShortcutsDialog() {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const on = () => setOpen((v) => !v)
    window.addEventListener('vouch:shortcuts', on)
    return () => window.removeEventListener('vouch:shortcuts', on)
  }, [])
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="w-[520px] max-w-[92vw] gap-0 border bg-popover p-0" showCloseButton={false}>
        <div className="flex h-8 items-center justify-between border-b px-3">
          <DialogTitle className="text-sm font-medium">Keyboard shortcuts</DialogTitle>
          <DialogDescription className="num text-2xs text-muted-foreground">esc</DialogDescription>
        </div>
        <div className="grid grid-cols-3 divide-x">
          {GROUPS.map((g) => (
            <div key={g.title} className="p-2">
              <p className="label-caps px-1 pb-1">{g.title}</p>
              <ul>
                {g.ids.map((id) => (
                  <li key={id} className="flex h-6 items-center justify-between gap-2 px-1 text-xs">
                    <span className="truncate text-foreground/85">{SHORTCUTS[id].label}</span>
                    <span className="num shrink-0 text-muted-foreground">{SHORTCUTS[id].keys.join(' ')}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
