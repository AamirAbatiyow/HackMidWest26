import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { EvidenceBar } from '@/components/vouch/EvidenceBar'
import { RiskTag } from '@/components/vouch/RiskTag'
import { StatusChip } from '@/components/vouch/StatusChip'
import { usePayments } from '@/store/PaymentsProvider'
import { useUi } from '@/store/UiProvider'

/** Plain-English explanation of a flag. Read from evidence, never generated. */
export function ExplainDialog() {
  const { explainOpen, setExplainOpen, activeId } = useUi()
  const { payments } = usePayments()
  const p = payments.find((x) => x.id === activeId)
  if (!p) return null
  const concerns = p.evidence.filter((e) => e.direction === 'concern').sort((a, b) => b.weight - a.weight)
  const reassuring = p.evidence.filter((e) => e.direction === 'reassuring').sort((a, b) => b.weight - a.weight)
  return (
    <Dialog open={explainOpen} onOpenChange={setExplainOpen}>
      <DialogContent className="w-[560px] max-w-[92vw] gap-0 border bg-popover p-0" showCloseButton={false}>
        <div className="flex h-8 items-center justify-between gap-2 border-b px-3">
          <DialogTitle className="truncate text-sm font-medium">
            {p.vendor.name} <span className="num text-muted-foreground">{p.invoiceNumber}</span>
          </DialogTitle>
          <span className="flex items-center gap-1.5">
            <RiskTag risk={p.risk} />
            <StatusChip status={p.status} lifecycle={p.lifecycle} />
          </span>
        </div>
        <DialogDescription className="border-b px-3 py-2 text-sm text-foreground/85">{p.reason}</DialogDescription>
        <div className="px-3 py-2">
          {concerns.length > 0 && <p className="label-caps pb-1">Raises concern</p>}
          {concerns.map((f) => (
            <EvidenceBar key={f.id} factor={f} showWeight />
          ))}
          <p className="label-caps pt-2 pb-1">Reassuring</p>
          {reassuring.map((f) => (
            <EvidenceBar key={f.id} factor={f} showWeight />
          ))}
        </div>
        <p className="border-t px-3 py-2 text-xs text-muted-foreground">Weights come from the screening model; the recommendation is code-enforced. Vouch never auto-denies.</p>
      </DialogContent>
    </Dialog>
  )
}
