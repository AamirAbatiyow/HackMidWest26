import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandSeparator } from '@/components/ui/command'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { StatusChip } from '@/components/vouch/StatusChip'
import { formatMoney } from '@/lib/format'
import { QUEUE_PATH } from '@/lib/routes'
import { SHORTCUTS } from '@/lib/shortcuts'
import { usePayments } from '@/store/PaymentsProvider'
import { useUi, type LaneFilter } from '@/store/UiProvider'
import { useTheme } from '@/theme/ThemeProvider'
import { useApi } from '@/api/ApiProvider'
import { VIEWS } from './TopBar'
import { usePaymentActions } from './usePaymentActions'

function Hint({ keys }: { keys: readonly string[] }) {
  return <span className="num ml-auto text-2xs text-muted-foreground/70">{keys.join(' ')}</span>
}

const ITEM = 'h-7 rounded-xs px-2 text-sm data-[selected=true]:bg-surface-3'

export function CommandPalette() {
  const ui = useUi()
  const { payments, batchReady } = usePayments()
  const { run } = usePaymentActions()
  const { toggle } = useTheme()
  const { preference, setPreference, mode } = useApi()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')

  useEffect(() => {
    if (ui.paletteOpen) setQuery(ui.paletteQuery)
  }, [ui.paletteOpen, ui.paletteQuery])

  const active = payments.find((p) => p.id === ui.activeId)
  const close = () => ui.setPaletteOpen(false)
  const go = (to: string) => {
    navigate(to)
    close()
  }
  const act = async (action: 'approve' | 'hold' | 'verify' | 'appeal') => {
    if (!active) return
    close()
    await run(active, action)
    if (action === 'approve') navigate('/approve')
  }
  const filter = (f: LaneFilter) => {
    ui.setFilter(f)
    go(QUEUE_PATH)
  }

  return (
    <Dialog open={ui.paletteOpen} onOpenChange={ui.setPaletteOpen}>
      <DialogContent className="top-[12%] w-[560px] max-w-[92vw] translate-y-0 gap-0 overflow-hidden border bg-popover p-0" showCloseButton={false}>
        <DialogTitle className="sr-only">Command palette</DialogTitle>
        <DialogDescription className="sr-only">Type a command or a vendor name.</DialogDescription>
        <Command className="bg-transparent" loop>
          <CommandInput value={query} onValueChange={setQuery} placeholder="Search vendors or commands" className="h-9 text-sm" />
          <CommandList className="max-h-[360px] p-1">
            <CommandEmpty className="py-6 text-center text-xs text-muted-foreground">No match.</CommandEmpty>

            {active && active.lifecycle !== 'settled' && (
              <>
                <CommandGroup heading={`${active.vendor.name} · ${active.invoiceNumber}`} className="[&_[cmdk-group-heading]]:label-caps [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1">
                  <CommandItem className={ITEM} onSelect={() => void act('approve')}>
                    Approve <Hint keys={SHORTCUTS.approve.keys} />
                  </CommandItem>
                  <CommandItem className={ITEM} onSelect={() => void act('hold')}>
                    Hold <Hint keys={SHORTCUTS.hold.keys} />
                  </CommandItem>
                  <CommandItem className={ITEM} onSelect={() => void act('verify')}>
                    Mark as verified <Hint keys={SHORTCUTS.verify.keys} />
                  </CommandItem>
                  <CommandItem className={ITEM} onSelect={() => void act('appeal')}>
                    Vendor is fine <Hint keys={SHORTCUTS.appeal.keys} />
                  </CommandItem>
                  <CommandItem className={ITEM} onSelect={() => { close(); ui.setExplainOpen(true) }}>
                    Why flagged? <Hint keys={SHORTCUTS.explain.keys} />
                  </CommandItem>
                </CommandGroup>
                <CommandSeparator />
              </>
            )}

            <CommandGroup heading="Batch" className="[&_[cmdk-group-heading]]:label-caps [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1">
              <CommandItem className={ITEM} onSelect={() => go('/approve')} disabled={batchReady.length === 0}>
                Pay ready invoices
                <span className="num ml-2 text-xs text-muted-foreground">{batchReady.length}</span>
                <Hint keys={SHORTCUTS.approve.keys} />
              </CommandItem>
            </CommandGroup>
            <CommandSeparator />

            <CommandGroup heading="Invoices" className="[&_[cmdk-group-heading]]:label-caps [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1">
              {payments.map((p) => (
                <CommandItem
                  key={p.id}
                  value={`${p.vendor.name} ${p.invoiceNumber} ${p.vendor.city} ${p.amount}`}
                  className={ITEM}
                  onSelect={() => {
                    ui.open(p.id)
                    go(QUEUE_PATH)
                  }}
                >
                  <span className="truncate">{p.vendor.name}</span>
                  <span className="num ml-auto shrink-0 text-xs">{formatMoney(p.amount)}</span>
                  <StatusChip status={p.status} lifecycle={p.lifecycle} className="ml-2" />
                </CommandItem>
              ))}
            </CommandGroup>
            <CommandSeparator />

            <CommandGroup heading="Filter" className="[&_[cmdk-group-heading]]:label-caps [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1">
              <CommandItem className={ITEM} onSelect={() => filter('all')}>Show all</CommandItem>
              <CommandItem className={ITEM} onSelect={() => filter('vouched')}>Show vouched</CommandItem>
              <CommandItem className={ITEM} onSelect={() => filter('quick_check')}>Show quick check</CommandItem>
              <CommandItem className={ITEM} onSelect={() => filter('verify')}>Show verify</CommandItem>
              <CommandItem className={ITEM} onSelect={() => filter('held')}>Show held</CommandItem>
            </CommandGroup>
            <CommandSeparator />

            <CommandGroup heading="Go to" className="[&_[cmdk-group-heading]]:label-caps [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1">
              {VIEWS.map((v) => (
                <CommandItem key={v.to} className={ITEM} onSelect={() => go(v.to)}>
                  {v.label} <Hint keys={['g', v.key]} />
                </CommandItem>
              ))}
            </CommandGroup>
            <CommandSeparator />

            <CommandGroup heading="View" className="[&_[cmdk-group-heading]]:label-caps [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1">
              <CommandItem className={ITEM} onSelect={() => { ui.setFeedOpen(!ui.feedOpen); close() }}>
                {ui.feedOpen ? 'Hide' : 'Show'} orchestrator timeline <Hint keys={SHORTCUTS.feed.keys} />
              </CommandItem>
              <CommandItem className={ITEM} onSelect={() => { toggle(); close() }}>
                Toggle theme <Hint keys={SHORTCUTS.theme.keys} />
              </CommandItem>
              <CommandItem className={ITEM} onSelect={() => { close(); window.dispatchEvent(new Event('vouch:shortcuts')) }}>
                Keyboard shortcuts <Hint keys={SHORTCUTS.help.keys} />
              </CommandItem>
            </CommandGroup>
            <CommandSeparator />

            <CommandGroup heading={`Data · ${mode === 'live' ? 'live' : 'demo'}`} className="[&_[cmdk-group-heading]]:label-caps [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1">
              <CommandItem className={ITEM} onSelect={() => { setPreference('auto'); close() }} disabled={preference === 'auto'}>
                Auto
              </CommandItem>
              <CommandItem className={ITEM} onSelect={() => { setPreference('live'); close() }} disabled={preference === 'live'}>
                Live data
              </CommandItem>
              <CommandItem className={ITEM} onSelect={() => { setPreference('mock'); close() }} disabled={preference === 'mock'}>
                Demo data
              </CommandItem>
            </CommandGroup>
          </CommandList>
        </Command>
      </DialogContent>
    </Dialog>
  )
}
