import { BadgeCheck, HandHeart, Loader2, PauseCircle, PhoneCall, ScrollText } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import type { Payment } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Textarea } from '@/components/ui/textarea'
import { describeDue, formatDateTime } from '@/lib/format'
import { COUNTRY_LABELS } from '@/lib/countries'
import { cn } from '@/lib/utils'
import { usePayments } from '@/store/PaymentsProvider'
import { CountryFlag } from './CountryFlag'
import { EvidenceBar } from './EvidenceBar'
import { Money } from './Money'
import { NetworkMiniGraph } from './NetworkMiniGraph'
import { FastPayBadge } from './PaymentCard'
import { RiskTag } from './RiskTag'
import { StatusChip } from './StatusChip'
import { TrustMeter } from './TrustMeter'
import { VendorTimelineRow } from './VendorTimelineRow'

interface EvidenceDrawerProps {
  payment: Payment | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

type Action = 'approve' | 'hold' | 'appeal'

export function EvidenceDrawer({ payment, open, onOpenChange }: EvidenceDrawerProps) {
  const { approve, hold, appeal, toggleChecklist } = usePayments()
  // The note is scoped to one payment; switching payments starts fresh.
  const [draft, setDraft] = useState<{ forId: string; text: string }>({ forId: '', text: '' })
  const [pending, setPending] = useState<Action | null>(null)

  if (!payment) return null

  const note = draft.forId === payment.id ? draft.text : ''
  const setNote = (text: string) => setDraft({ forId: payment.id, text })

  const flagged = payment.status !== 'vouched'
  const concerns = payment.evidence.filter((e) => e.direction === 'concern')
  const reassuring = payment.evidence.filter((e) => e.direction === 'reassuring')
  const ordered = [...concerns, ...reassuring].sort((a, b) => b.weight - a.weight)
  const settled = payment.lifecycle === 'settled'

  const run = async (action: Action) => {
    setPending(action)
    try {
      if (action === 'approve') {
        await approve(payment.id, note)
        toast.success(`${payment.vendor.name} marked as verified`, {
          description: 'Added to your batch. Nothing is paid until you approve.',
        })
      } else if (action === 'hold') {
        await hold(payment.id, note)
        toast(`${payment.vendor.name} held for a quick check`, {
          description: 'The vendor is not notified. Pick it back up any time.',
        })
      } else {
        await appeal(payment.id, note)
        toast.success(`Thanks. ${payment.vendor.name} is vouched for.`, {
          description: 'We will go easier on this vendor next time.',
        })
      }
      setNote('')
      onOpenChange(false)
    } catch (err) {
      toast.error("That didn't go through", {
        description: err instanceof Error ? err.message : 'Please try again.',
      })
    } finally {
      setPending(null)
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-full gap-0 border-l-0 bg-background p-0 sm:max-w-[560px] data-[side=right]:sm:max-w-[560px]"
        aria-describedby={undefined}
      >
        <SheetHeader className="border-b bg-card px-6 pt-6 pb-5">
          <div className="flex items-start justify-between gap-4 pr-8">
            <div className="min-w-0">
              <SheetDescription className="mb-1 flex items-center gap-2 text-xs">
                <CountryFlag country={payment.vendor.country} size={18} />
                {payment.vendor.city}, {COUNTRY_LABELS[payment.vendor.country]} · Invoice{' '}
                <span className="tabular-nums">{payment.invoiceNumber}</span>
              </SheetDescription>
              <SheetTitle className="text-xl font-semibold tracking-[-0.015em]">{payment.vendor.name}</SheetTitle>
            </div>
            <Money amount={payment.amount} className="shrink-0 text-2xl font-semibold tracking-[-0.02em]" />
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <StatusChip status={payment.status} />
            <RiskTag risk={payment.risk} showNone />
            {payment.fastPayEligible && <FastPayBadge />}
          </div>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
            <TrustMeter score={payment.trustScore} />
            <span className="text-xs text-muted-foreground tabular-nums">{describeDue(payment.dueDate)}</span>
          </div>
        </SheetHeader>

        <ScrollArea className="min-h-0 flex-1">
          <div className="space-y-8 px-6 py-6">
            <section aria-labelledby="why-heading">
              <h3 id="why-heading" className="text-sm font-semibold">
                {flagged ? 'Why we flagged this' : 'Why we vouched for this'}
              </h3>
              <p className="mt-1 text-sm text-muted-foreground">{payment.reason}</p>
              <div className="mt-4 space-y-4">
                {ordered.map((f, i) => (
                  <EvidenceBar key={f.id} factor={f} delayMs={i * 60} />
                ))}
              </div>
              <p className="mt-3 flex items-center gap-3 text-[11px] text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                  <span className="size-2 rounded-full bg-attention" aria-hidden="true" /> Raises a question
                </span>
                <span className="inline-flex items-center gap-1">
                  <span className="size-2 rounded-full bg-vouched" aria-hidden="true" /> Reassuring
                </span>
              </p>
            </section>

            {payment.ring && (
              <section aria-labelledby="ring-heading">
                <h3 id="ring-heading" className="text-sm font-semibold">
                  Vendors sharing details
                </h3>
                <p className="mt-1 text-sm text-muted-foreground">
                  Three vendors share a bank account, and two of them share a phone and an address. That pattern is worth a call.
                </p>
                <NetworkMiniGraph graph={payment.ring} className="mt-3" />
              </section>
            )}

            {payment.checklist.length > 0 && (
              <section aria-labelledby="confirm-heading" className="card-surface bg-muted/30 p-4">
                <h3 id="confirm-heading" className="flex items-center gap-2 text-sm font-semibold">
                  <PhoneCall className="size-4 text-attention" aria-hidden="true" />
                  Confirm with vendor
                </h3>
                <p className="mt-1 text-xs text-muted-foreground">A two-minute call-back, using the number you already have on file.</p>
                <ul className="mt-3 space-y-2.5">
                  {payment.checklist.map((item) => (
                    <li key={item.id} className="flex items-start gap-3">
                      <Checkbox
                        id={`chk-${payment.id}-${item.id}`}
                        checked={item.done}
                        onCheckedChange={() => toggleChecklist(payment.id, item.id)}
                        className="mt-0.5"
                      />
                      <Label
                        htmlFor={`chk-${payment.id}-${item.id}`}
                        className={cn('text-sm leading-snug font-normal', item.done && 'text-muted-foreground line-through')}
                      >
                        {item.text}
                      </Label>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <section aria-labelledby="history-heading">
              <h3 id="history-heading" className="text-sm font-semibold">
                Vendor history
              </h3>
              <p className="mt-1 text-xs text-muted-foreground">
                {payment.vendor.paymentsCompleted > 0
                  ? `${payment.vendor.paymentsCompleted} payments completed since ${formatDateTime(payment.vendor.since).split(',')[0]}, ${new Date(payment.vendor.since).getFullYear()}.`
                  : 'First payment to this vendor.'}
              </p>
              <ol className="mt-4">
                {payment.timeline.map((ev, i) => (
                  <VendorTimelineRow key={ev.id} event={ev} isLast={i === payment.timeline.length - 1} />
                ))}
              </ol>
            </section>

            <Separator />

            <section aria-labelledby="note-heading">
              <h3 id="note-heading" className="flex items-center gap-2 text-sm font-semibold">
                <ScrollText className="size-4 text-muted-foreground" aria-hidden="true" />
                Audit note
              </h3>
              <p className="mt-1 text-xs text-muted-foreground">Saved with whatever you decide, for your records.</p>
              <Textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="e.g. Spoke with Marta, she confirmed the new account."
                className="mt-3 min-h-20 resize-none bg-card"
                aria-label="Audit note"
              />
              {payment.auditNotes.length > 0 && (
                <ul className="mt-3 space-y-2">
                  {payment.auditNotes.map((n) => (
                    <li key={n.id} className="rounded-lg bg-muted/60 px-3 py-2 text-xs">
                      <span className="font-medium">{n.author}</span>{' '}
                      <span className="text-muted-foreground">· {formatDateTime(n.at)}</span>
                      <p className="mt-0.5 text-foreground/85">{n.text}</p>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </ScrollArea>

        <footer className="border-t bg-card px-6 py-4">
          {settled ? (
            <p className="text-center text-sm text-muted-foreground">This payment is settled. Nothing more to do.</p>
          ) : (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              <Button
                size="lg"
                className={cn('h-11 sm:col-span-1', flagged ? '' : 'sm:col-span-1')}
                onClick={() => run('approve')}
                disabled={pending !== null}
              >
                {pending === 'approve' ? <Loader2 className="animate-spin" aria-hidden="true" /> : <BadgeCheck aria-hidden="true" />}
                Mark as verified
              </Button>
              <Button variant="outline" size="lg" className="h-11" onClick={() => run('hold')} disabled={pending !== null}>
                {pending === 'hold' ? <Loader2 className="animate-spin" aria-hidden="true" /> : <PauseCircle aria-hidden="true" />}
                Hold for a quick check
              </Button>
              <Button variant="ghost" size="lg" className="h-11" onClick={() => run('appeal')} disabled={pending !== null}>
                {pending === 'appeal' ? <Loader2 className="animate-spin" aria-hidden="true" /> : <HandHeart aria-hidden="true" />}
                This vendor is fine
              </Button>
            </div>
          )}
          <p className="mt-3 text-center text-[11px] text-muted-foreground">
            Nothing moves until you approve the batch. Vendors are never told about a check.
          </p>
        </footer>
      </SheetContent>
    </Sheet>
  )
}
