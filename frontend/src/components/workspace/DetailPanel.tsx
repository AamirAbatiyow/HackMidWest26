import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Payment } from '@/api/types'
import { Checkbox } from '@/components/ui/checkbox'
import { EvidenceBar } from '@/components/vouch/EvidenceBar'
import { HighlightedInvoice } from '@/components/vouch/HighlightedInvoice'
import { LimeExplanation } from '@/components/vouch/LimeExplanation'
import { countFlagged } from '@/lib/highlights'
import { RelationTag, relatedTo } from '@/components/vouch/RelationTag'
import { APPROVAL_LIMIT } from '@/data/payments'
import { StatusChip } from '@/components/vouch/StatusChip'
import { VendorTimelineRow } from '@/components/vouch/VendorTimelineRow'
import { formatMoney } from '@/lib/format'
import { cn } from '@/lib/utils'
import { usePayments } from '@/store/PaymentsProvider'
import { useUi } from '@/store/UiProvider'
import { DecisionMatrix } from './DecisionMatrix'
import { RingGraph } from './RingGraph'
import { Shortcut } from './Shortcut'
import { usePaymentActions, type PaymentAction } from './usePaymentActions'

const BTN = 'flex h-7 items-center justify-between gap-2 rounded-xs border px-2 text-xs outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50'

function Section({ title, meta, children, className }: { title: string; meta?: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn('border-b px-3 py-2', className)}>
      <div className="flex h-5 items-center justify-between gap-2">
        <h3 className="label-caps">{title}</h3>
        {meta && <span className="num text-2xs text-muted-foreground">{meta}</span>}
      </div>
      <div className="pt-1">{children}</div>
    </section>
  )
}

/** Decide-now panel: who, how much, why, what to do. Everything else is under "More details". */
export function DetailPanel({ payment: p, className }: { payment: Payment; className?: string }) {
  const { toggleChecklist, batchReady, payments } = usePayments()
  const ui = useUi()
  const navigate = useNavigate()
  const { run, pending } = usePaymentActions()
  const [more, setMore] = useState(false)

  const flagged = p.status !== 'vouched'
  const settled = p.lifecycle === 'settled'
  const inBatch = batchReady.some((x) => x.id === p.id)
  // LIME rows render in their own section; evidence that duplicates them stays out of "Other factors".
  const limeLabels = new Set((p.model?.factors ?? []).map((f) => f.rawLabel))
  const ordered = [...p.evidence].sort((a, b) => (a.direction === b.direction ? b.weight - a.weight : a.direction === 'concern' ? -1 : 1))
  const rest = limeLabels.size > 0 ? ordered.filter((f) => !limeLabels.has(f.label)) : []
  const highlights = p.highlights ?? []
  const flaggedFields = countFlagged(highlights)
  const checklistDone = p.checklist.filter((c) => c.done).length
  const checklistComplete = p.checklist.length === 0 || checklistDone === p.checklist.length

  const { duplicates, partner } = relatedTo(p, payments)
  const jump = (id: string) => {
    ui.open(id)
    ui.flash(id)
  }

  const act = async (action: PaymentAction) => {
    await run(p, action)
    if (action === 'approve') navigate('/approve')
  }

  return (
    <aside className={cn('flex min-h-0 flex-col bg-background', className)} aria-label={`${p.vendor.name} ${p.invoiceNumber}`}>
      <header className="flex h-8 shrink-0 items-center justify-between gap-2 border-b px-3">
        <div className="flex min-w-0 items-baseline gap-2">
          <h2 className="truncate text-sm font-medium">{p.vendor.name}</h2>
          <span className="num text-sm text-foreground">{formatMoney(p.amount)}</span>
          <span className="num truncate text-xs text-muted-foreground">{p.invoiceNumber}</span>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <StatusChip status={p.status} lifecycle={p.lifecycle} />
          <button type="button" className="num h-5 rounded-xs px-1.5 text-2xs text-muted-foreground hover:bg-surface-2 hover:text-foreground" onClick={() => ui.setActive(null)} aria-label="Close panel">
            esc
          </button>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <section className="border-b px-3 py-2">
          <p className="text-sm text-foreground/90">{p.reason}</p>
          {p.relation?.kind === 'duplicate_of' && partner && (
            <p className="num flex items-center gap-1.5 pt-1.5 text-xs text-muted-foreground">
              <RelationTag label={`dup of ${partner.invoiceNumber}`} onJump={() => jump(partner.id)} />
              {formatMoney(partner.amount)} already in the {partner.status === 'vouched' ? 'vouched' : 'queue'} lane
            </p>
          )}
          {p.relation?.kind === 'split_with' && partner && (
            <p className="num flex items-center gap-1.5 pt-1.5 text-xs text-muted-foreground">
              <RelationTag label={`split with ${partner.invoiceNumber}`} onJump={() => jump(partner.id)} />
              {formatMoney(p.amount + partner.amount)} combined · each just under the {formatMoney(APPROVAL_LIMIT)} limit
            </p>
          )}
          {duplicates.length > 0 && (
            <p className="num flex items-center gap-1.5 pt-1.5 text-xs text-muted-foreground">
              <RelationTag label={`${duplicates.length} duplicate${duplicates.length === 1 ? '' : 's'}`} onJump={() => jump(duplicates[0]!.id)} muted />
              {duplicates.map((d) => d.invoiceNumber).join(', ')} in Quick check
            </p>
          )}
          {flagged && !settled && <p className="pt-1 text-xs text-muted-foreground">Not denied. Waiting for you; the vendor has not been told.</p>}
        </section>

        <LimeExplanation payment={p} />

        {highlights.length > 0 && (
          <Section title="Highlighted invoice" meta={flaggedFields.high > 0 ? `${flaggedFields.high} field${flaggedFields.high === 1 ? '' : 's'} in red` : flaggedFields.warn > 0 ? `${flaggedFields.warn} to glance at` : 'nothing flagged'}>
            <HighlightedInvoice payment={p} />
          </Section>
        )}

        {p.ring && (
          <Section title="Shared details" meta={`${p.ring.nodes.filter((n) => n.kind === 'vendor').length} vendors`}>
            <RingGraph graph={p.ring} height={170} />
          </Section>
        )}

        {p.checklist.length > 0 && !settled && (
          <Section title="Before you release it" meta={`${checklistDone}/${p.checklist.length}`}>
            <ul>
              {p.checklist.map((item) => (
                <li key={item.id} className="flex min-h-row items-center gap-2 border-b last:border-b-0">
                  <Checkbox id={`chk-${p.id}-${item.id}`} checked={item.done} onCheckedChange={() => toggleChecklist(p.id, item.id)} className="size-3.5 rounded-xs border-input" />
                  <label htmlFor={`chk-${p.id}-${item.id}`} className={cn('text-sm', item.done && 'text-muted-foreground line-through')}>
                    {item.text}
                  </label>
                </li>
              ))}
            </ul>
          </Section>
        )}

        <section className="border-b">
          <button type="button" className="flex h-8 w-full items-center justify-between px-3 text-left outline-none hover:bg-surface-2 focus-visible:ring-1 focus-visible:ring-ring" onClick={() => setMore((v) => !v)} aria-expanded={more}>
            <span className="label-caps">More details</span>
            <span className="num text-2xs text-muted-foreground">{more ? '▾' : '▸'}</span>
          </button>
          {more && (
            <div>
              {rest.length > 0 && (
                <Section title="More reasons" meta={`${rest.length}`}>
                  {rest.map((f) => (
                    <EvidenceBar key={f.id} factor={f} />
                  ))}
                </Section>
              )}
              <Section title="Checks we ran">
                <DecisionMatrix payment={p} />
              </Section>
              <Section title="Vendor history" meta={p.vendor.paymentsCompleted > 0 ? `${p.vendor.paymentsCompleted} paid · since ${new Date(p.vendor.since).getFullYear()}` : 'first payment'} className="border-b-0">
                <ol>
                  {p.timeline.map((ev) => (
                    <VendorTimelineRow key={ev.id} event={ev} />
                  ))}
                </ol>
              </Section>
            </div>
          )}
        </section>
      </div>

      <footer className="shrink-0 border-t p-2">
        {settled ? (
          <p className="px-1 text-xs text-muted-foreground">Paid. Nothing more to do.</p>
        ) : (
          <div className="grid grid-cols-3 gap-1">
            {flagged ? (
              <button type="button" className={cn(BTN, 'bg-primary text-primary-foreground')} onClick={() => void act('verify')} disabled={pending !== null || inBatch || !checklistComplete} title={!checklistComplete ? 'Finish the steps above first' : undefined}>
                {inBatch ? 'In batch' : 'Verify'}
                <Shortcut id="verify" className="text-primary-foreground/70" />
              </button>
            ) : (
              <button type="button" className={cn(BTN, 'bg-primary text-primary-foreground')} onClick={() => void act('approve')} disabled={pending !== null || inBatch}>
                {inBatch ? 'In batch' : 'Approve'}
                <Shortcut id="approve" className="text-primary-foreground/70" />
              </button>
            )}
            <button type="button" className={BTN} onClick={() => void act('hold')} disabled={pending !== null || p.lifecycle === 'held'}>
              {p.lifecycle === 'held' ? 'On hold' : 'Hold'}
              <Shortcut id="hold" />
            </button>
            <button type="button" className={BTN} onClick={() => void act('appeal')} disabled={pending !== null}>
              Appeal
              <Shortcut id="appeal" />
            </button>
          </div>
        )}
      </footer>
    </aside>
  )
}
