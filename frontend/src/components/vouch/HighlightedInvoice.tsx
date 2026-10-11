import type { HighlightSeverity, InvoiceHighlight, Payment } from '@/api/types'
import { countFlagged } from '@/lib/highlights'
import { cn } from '@/lib/utils'

const TONE: Record<HighlightSeverity, { value: string; tag: string; row: string }> = {
  high: { value: 'text-red', tag: 'border-red/50 bg-red-soft text-red', row: 'bg-red-soft/60' },
  warn: { value: 'text-amber', tag: 'border-amber/40 bg-amber-soft text-amber', row: '' },
  ok: { value: 'text-foreground', tag: '', row: '' },
}

/** Fields that read as a document header rather than a table row. */
const HEADER_FIELDS = new Set(['vendor_name', 'invoice_number', 'issue_date', 'due_date'])
const MONO_FIELDS = new Set(['invoice_number', 'issue_date', 'due_date', 'amount', 'bank_account', 'tax_id', 'phone', 'po_number'])

function ReasonTags({ h }: { h: InvoiceHighlight }) {
  if (h.severity === 'ok' || h.reasons.length === 0) return null
  return (
    <span className="flex flex-wrap gap-1">
      {h.reasons.map((r) => (
        <span key={r} className={cn('inline-flex h-[18px] items-center rounded-xs border px-1 text-2xs leading-none whitespace-nowrap', TONE[h.severity].tag)}>
          {r}
        </span>
      ))}
    </span>
  )
}

function Value({ h }: { h: InvoiceHighlight }) {
  return <span className={cn('break-words', MONO_FIELDS.has(h.field) && 'num', TONE[h.severity].value, h.severity === 'high' && 'font-medium')}>{h.value}</span>
}

function Row({ h }: { h: InvoiceHighlight }) {
  return (
    <div className={cn('grid grid-cols-[96px_minmax(0,1fr)] gap-x-3 border-b px-3 py-1.5 last:border-b-0', TONE[h.severity].row)} data-field={h.field} data-severity={h.severity}>
      <dt className="pt-px text-xs text-muted-foreground">{h.label}</dt>
      <dd className="flex min-w-0 flex-col gap-1 text-sm">
        <Value h={h} />
        <ReasonTags h={h} />
      </dd>
    </div>
  )
}

interface HighlightedInvoiceProps {
  payment: Payment
  className?: string
}

/**
 * The invoice as a readable document. Suspicious fields are red with a short reason tag;
 * fields with no finding stay neutral. Driven entirely by `payment.highlights` from the backend.
 */
export function HighlightedInvoice({ payment: p, className }: HighlightedInvoiceProps) {
  const highlights = p.highlights ?? []
  if (highlights.length === 0) return null
  const byField = new Map(highlights.map((h) => [h.field, h]))
  const vendor = byField.get('vendor_name')
  const number = byField.get('invoice_number')
  const issued = byField.get('issue_date')
  const due = byField.get('due_date')
  const body = highlights.filter((h) => !HEADER_FIELDS.has(h.field))
  const { high, warn } = countFlagged(highlights)

  return (
    <div className={cn('overflow-hidden rounded-sm border bg-surface-1', high > 0 && 'border-red/40', className)} data-testid="highlighted-invoice" data-high={high} data-warn={warn}>
      <header className="border-b px-3 py-2">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className={cn('truncate text-lg font-medium', vendor && TONE[vendor.severity].value)}>{vendor?.value ?? p.vendor.name}</p>
            {vendor && <ReasonTags h={vendor} />}
          </div>
          <div className="shrink-0 text-right">
            <p className="label-caps">Invoice</p>
            <p className={cn('num text-sm', number && TONE[number.severity].value, number?.severity === 'high' && 'font-medium')}>{number?.value ?? p.invoiceNumber}</p>
          </div>
        </div>
        {number && number.severity !== 'ok' && <div className="pt-1">{<ReasonTags h={number} />}</div>}
        <div className="num flex flex-wrap gap-x-4 gap-y-1 pt-1.5 text-xs text-muted-foreground">
          {issued && (
            <span>
              Issued <span className={cn(TONE[issued.severity].value)}>{issued.value}</span>
            </span>
          )}
          {due && (
            <span className="flex items-center gap-1.5">
              Due <span className={cn(TONE[due.severity].value)}>{due.value}</span>
              <ReasonTags h={due} />
            </span>
          )}
        </div>
      </header>
      <dl>
        {body.map((h) => (
          <Row key={h.field} h={h} />
        ))}
      </dl>
      <footer className="flex items-center justify-between gap-2 border-t px-3 py-1.5 text-2xs text-muted-foreground">
        <span>
          {high === 0 && warn === 0 ? (
            <span className="text-green">No suspicious fields</span>
          ) : (
            <>
              <span className={cn(high > 0 && 'text-red')}>
                {high} field{high === 1 ? '' : 's'} flagged
              </span>
              {warn > 0 && <span className="text-amber"> · {warn} to glance at</span>}
            </>
          )}
        </span>
        <span>Checks are deterministic; red tags cite the rule that fired.</span>
      </footer>
    </div>
  )
}
