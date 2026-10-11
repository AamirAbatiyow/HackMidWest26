import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Payment, VouchStatus } from '@/api/types'
import { Checkbox } from '@/components/ui/checkbox'
import { RelationTag, relatedTo } from '@/components/vouch/RelationTag'
import { RISK_META, RiskTag } from '@/components/vouch/RiskTag'
import { STATUS_META, STATUS_TONE, StatusChip } from '@/components/vouch/StatusChip'
import { ErrorState, LoadingRows } from '@/components/vouch/States'
import { TrustMeter } from '@/components/vouch/TrustMeter'
import { formatDueShort } from '@/lib/age'
import { formatDate, formatMoney } from '@/lib/format'
import { cn } from '@/lib/utils'
import { usePayments } from '@/store/PaymentsProvider'
import { useUi, type LaneFilter } from '@/store/UiProvider'
import { useVisibleRows, type Lane } from '@/store/useVisibleRows'
import { usePaymentActions } from './usePaymentActions'
import { Shortcut } from './Shortcut'

const FILTERS: { id: LaneFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'vouched', label: 'Vouched' },
  { id: 'quick_check', label: 'Quick check' },
  { id: 'verify', label: 'Verify' },
  { id: 'held', label: 'On hold' },
]

const COLS = [
  { id: 'check', label: '', width: 32 },
  { id: 'vendor', label: 'Vendor', width: undefined },
  { id: 'invoice', label: 'Invoice', width: 100 },
  { id: 'amount', label: 'Amount', width: 88, right: true },
  { id: 'due', label: 'Due', width: 92 },
  { id: 'risk', label: 'Risk', width: 124 },
  { id: 'trust', label: 'Trust', width: 80 },
  { id: 'status', label: 'Status', width: 132 },
] as const

const TH = 'h-7 px-2 text-left align-middle label-caps font-medium whitespace-nowrap'
const TD = 'h-row px-2 py-0 align-middle whitespace-nowrap'

export function PaymentsTable({ className }: { className?: string }) {
  const { payments, loading, error, reload } = usePayments()
  const ui = useUi()
  const { lanes, order } = useVisibleRows()
  const navigate = useNavigate()
  const { run } = usePaymentActions()
  const bodyRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!ui.activeId) return
    bodyRef.current?.querySelector<HTMLElement>(`[data-row-id="${CSS.escape(ui.activeId)}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [ui.activeId])

  const open = payments.filter((p) => p.lifecycle !== 'settled')
  const totalAll = open.reduce((s, p) => s + p.amount, 0)
  const count = (s: VouchStatus) => open.filter((p) => p.status === s).length
  const checkedRows = payments.filter((p) => ui.checked.has(p.id) && p.lifecycle !== 'settled')
  const checkedTotal = checkedRows.reduce((s, p) => s + p.amount, 0)

  const toggleLaneChecked = (lane: Lane) => {
    const ids = lane.rows.map((r) => r.id)
    const all = ids.every((id) => ui.checked.has(id))
    const next = new Set(ui.checked)
    for (const id of ids) {
      if (all) next.delete(id)
      else next.add(id)
    }
    ui.setChecked(next)
  }

  const bulkApprove = async () => {
    for (const p of checkedRows) await run(p, 'approve', undefined, { quiet: true })
    ui.clearChecked()
    navigate('/approve')
  }

  return (
    <section className={cn('flex min-h-0 min-w-0 flex-1 flex-col', className)} aria-label="Payment queue">
      <div className="flex h-8 shrink-0 items-center justify-between gap-4 border-b px-3">
        <p className="num truncate text-xs text-foreground/85">
          {open.length} payments · {formatMoney(totalAll)} · <span className="text-green">{count('vouched')} vouched</span> · {count('quick_check')} quick check · {count('verify')} verify
        </p>
        {checkedRows.length > 0 ? (
          <div className="flex shrink-0 items-center gap-1" role="toolbar" aria-label="Bulk actions">
            <button type="button" className="h-6 rounded-xs bg-primary px-2 text-xs text-primary-foreground hover:bg-primary/90" onClick={() => void bulkApprove()}>
              Approve {checkedRows.length} <span className="num">({formatMoney(checkedTotal)})</span>
              <Shortcut id="approve" className="ml-1.5 text-primary-foreground/70" />
            </button>
            <button type="button" className="h-6 rounded-xs px-2 text-xs text-muted-foreground hover:bg-surface-2 hover:text-foreground" onClick={ui.clearChecked}>
              Clear <Shortcut id="close" className="ml-1" />
            </button>
          </div>
        ) : (
          <div className="flex shrink-0 items-center gap-0.5" role="tablist" aria-label="Filter">
            {FILTERS.map((f) => (
              <button
                key={f.id}
                type="button"
                role="tab"
                aria-selected={ui.filter === f.id}
                onClick={() => ui.setFilter(f.id)}
                className={cn('h-6 rounded-xs px-2 text-xs outline-none focus-visible:ring-1 focus-visible:ring-ring', ui.filter === f.id ? 'bg-surface-3 text-foreground' : 'text-muted-foreground hover:bg-surface-2 hover:text-foreground')}
              >
                {f.label}
              </button>
            ))}
          </div>
        )}
      </div>

      <div ref={bodyRef} className="min-h-0 flex-1 overflow-auto">
        {error ? (
          <ErrorState message={error.message} onRetry={() => void reload()} />
        ) : loading && payments.length === 0 ? (
          <LoadingRows count={8} />
        ) : (
          <table className="w-full table-fixed border-separate border-spacing-0 text-sm">
            <thead className="sticky top-0 z-10 bg-background">
              <tr>
                {COLS.map((c) => (
                  <th key={c.id} scope="col" style={c.width ? { width: c.width } : undefined} className={cn(TH, 'border-b', 'right' in c && c.right && 'text-right')}>
                    {c.id === 'check' ? <span className="sr-only">Select</span> : c.label}
                  </th>
                ))}
              </tr>
            </thead>
            {lanes.map((lane) => (
              <LaneGroup key={lane.status} lane={lane} onToggleChecked={() => toggleLaneChecked(lane)} />
            ))}
            {order.length === 0 && !lanes.some((l) => l.collapsed && l.rows.length) && (
              <tbody>
                <tr>
                  <td colSpan={COLS.length} className="h-16 px-3 text-center text-xs text-muted-foreground">
                    No payments match.{' '}
                    <button
                      type="button"
                      className="underline-offset-2 hover:underline"
                      onClick={() => {
                        ui.setFilter('all')
                        ui.setSearch('')
                      }}
                    >
                      Clear filters
                    </button>
                  </td>
                </tr>
              </tbody>
            )}
          </table>
        )}
      </div>
    </section>
  )
}

const LANE_MARK: Record<VouchStatus, string> = { vouched: 'bg-green', quick_check: 'bg-amber', verify: 'bg-amber' }

function LaneGroup({ lane, onToggleChecked }: { lane: Lane; onToggleChecked: () => void }) {
  const ui = useUi()
  const meta = STATUS_META[lane.status]
  const allChecked = lane.rows.length > 0 && lane.rows.every((r) => ui.checked.has(r.id))
  const someChecked = !allChecked && lane.rows.some((r) => ui.checked.has(r.id))
  if (lane.rows.length === 0) return null
  return (
    <tbody>
      <tr>
        <td className="sticky top-7 z-10 h-7 border-y bg-surface-1 px-2 py-0 align-middle">
          <Checkbox aria-label={`Select all in ${meta.label}`} checked={allChecked ? true : someChecked ? 'indeterminate' : false} onCheckedChange={onToggleChecked} className="size-3.5 rounded-xs border-input" />
        </td>
        <td colSpan={COLS.length - 1} className="sticky top-7 z-10 h-7 border-y bg-surface-1 px-2 py-0 align-middle">
          <button type="button" className="flex h-full w-full items-center gap-2 text-left outline-none focus-visible:ring-1 focus-visible:ring-ring" onClick={() => ui.toggleLane(lane.status)} aria-expanded={!lane.collapsed}>
            <span className="num w-2 text-2xs text-muted-foreground" aria-hidden="true">
              {lane.collapsed ? '▸' : '▾'}
            </span>
            <span className={cn('h-3 w-0.5 shrink-0', LANE_MARK[lane.status])} aria-hidden="true" />
            <span className="text-xs font-medium">{meta.label}</span>
            <span className="num text-2xs text-muted-foreground">
              {lane.rows.length} · {formatMoney(lane.total)}
            </span>
          </button>
        </td>
      </tr>
      {!lane.collapsed && lane.rows.map((p) => <Row key={p.id} payment={p} />)}
    </tbody>
  )
}

function Row({ payment: p }: { payment: Payment }) {
  const ui = useUi()
  const { payments } = usePayments()
  const active = ui.activeId === p.id
  const checked = ui.checked.has(p.id)
  const settled = p.lifecycle === 'settled'
  const { duplicates, partner } = relatedTo(p, payments)
  const jump = (id: string) => {
    ui.setActive(id)
    ui.flash(id)
  }
  return (
    <tr
      data-row-id={p.id}
      data-active={active}
      data-selected={checked}
      aria-selected={active}
      className={cn('row-interactive cursor-default', settled && 'text-muted-foreground', ui.flashId === p.id && 'bg-accent-cool-soft')}
      onClick={() => ui.open(p.id)}
    >
      <td className={cn(TD, 'border-b border-l-2', STATUS_TONE[p.status].border, settled && 'border-l-border')} onClick={(e) => e.stopPropagation()}>
        <Checkbox aria-label={`Select ${p.vendor.name} ${p.invoiceNumber}`} checked={checked} onCheckedChange={() => ui.toggleChecked(p.id)} className="size-3.5 rounded-xs border-input" />
      </td>
      <td className={cn(TD, 'border-b')}>
        <span className="flex items-center gap-2">
          <span className="truncate font-medium text-foreground">{p.vendor.name}</span>
          {duplicates.length > 0 && <RelationTag label={`${duplicates.length} duplicate${duplicates.length === 1 ? '' : 's'}`} onJump={() => jump(duplicates[0]!.id)} muted />}
        </span>
      </td>
      <td className={cn(TD, 'num border-b text-xs text-foreground/85')}>{p.invoiceNumber}</td>
      <td className={cn(TD, 'num border-b text-right text-foreground')}>{formatMoney(p.amount)}</td>
      <td className={cn(TD, 'num border-b text-xs')}>
        <span className="text-foreground/85">{formatDate(p.dueDate)}</span>
        <span className="ml-1.5 text-muted-foreground">{formatDueShort(p.dueDate)}</span>
      </td>
      <td className={cn(TD, 'border-b')} title={p.relation ? RISK_META[p.risk].label : undefined}>
        {p.relation?.kind === 'duplicate_of' && partner ? (
          <RelationTag label={`dup of ${partner.invoiceNumber}`} onJump={() => jump(partner.id)} />
        ) : p.relation?.kind === 'split_with' && partner ? (
          <RelationTag label={`split with ${partner.invoiceNumber}`} onJump={() => jump(partner.id)} />
        ) : (
          <RiskTag risk={p.risk} />
        )}
      </td>
      <td className={cn(TD, 'border-b')}>
        <TrustMeter score={p.trustScore} />
      </td>
      <td className={cn(TD, 'border-b')}>
        <StatusChip status={p.status} lifecycle={p.lifecycle} />
      </td>
    </tr>
  )
}
