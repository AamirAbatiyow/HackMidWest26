import { Check, CircleDashed, Loader2, Pause, TriangleAlert } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useApi } from '@/api/ApiProvider'
import type { Payment } from '@/api/types'
import { byMostRecent, formatMs, type OrchestratorStep, type StepStatus } from '@/data/orchestrator'
import { formatMoney } from '@/lib/format'
import { cn } from '@/lib/utils'
import { usePayments } from '@/store/PaymentsProvider'
import { useUi } from '@/store/UiProvider'
import { useLiveRuns, useOrchestratorTimeline } from './useOrchestratorTimeline'

const PANE_W = 'w-[320px]'

const STATUS_TONE: Record<StepStatus, string> = {
  ok: 'text-green',
  flag: 'text-red',
  hold: 'text-amber',
  pending: 'text-muted-foreground',
}
const STATUS_LABEL: Record<StepStatus, string> = { ok: 'ok', flag: 'flagged', hold: 'on hold', pending: 'pending' }

function StatusIcon({ status, className }: { status: StepStatus; className?: string }) {
  const cls = cn('size-3 shrink-0', STATUS_TONE[status], className)
  if (status === 'ok') return <Check className={cls} aria-hidden="true" strokeWidth={2.5} />
  if (status === 'flag') return <TriangleAlert className={cls} aria-hidden="true" />
  if (status === 'hold') return <Pause className={cls} aria-hidden="true" strokeWidth={2.5} />
  return <CircleDashed className={cn(cls, 'animate-pulse-soft')} aria-hidden="true" />
}

function detailValue(v: unknown): string {
  if (v == null || v === '') return '—'
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(3)
  if (typeof v === 'string') return v
  if (Array.isArray(v)) {
    if (v.length === 0) return 'none'
    return v.map((x) => (typeof x === 'object' && x !== null ? summarizeObject(x as Record<string, unknown>) : String(x))).join('; ')
  }
  if (typeof v === 'object') return summarizeObject(v as Record<string, unknown>)
  return String(v)
}

function summarizeObject(o: Record<string, unknown>): string {
  const entries = Object.entries(o).filter(([, val]) => val != null && val !== '')
  if ('label' in o && 'weight' in o) return `${String(o.label)} (${Number(o.weight).toFixed(2)})`
  if ('key' in o && 'answer' in o) return `${String(o.key)} → ${String(o.answer)} [${String(o.engine ?? '?')}${o.accepted === false ? ', rejected' : ''}]`
  if ('filename' in o) return [o.filename, o.extractor, o.tool].filter(Boolean).map(String).join(' · ')
  return entries
    .slice(0, 4)
    .map(([k, val]) => `${k}=${typeof val === 'object' ? JSON.stringify(val) : String(val)}`)
    .join(', ')
}

/** Expanded row: the inputs/outputs summary the backend attached to the step. */
function StepDetail({ step }: { step: OrchestratorStep }) {
  const entries = Object.entries(step.detail).filter(([k]) => !(k === 'llm_calls' || k === 'tokens') || Number(step.detail[k]) > 0)
  return (
    <dl className="mt-1 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-2 gap-y-0.5 border-l border-border/70 pl-2 text-2xs">
      <dt className="text-muted-foreground">node</dt>
      <dd className="num break-words">{step.node || '—'}</dd>
      <dt className="text-muted-foreground">engine</dt>
      <dd className="num break-words">{step.engine ?? '—'}</dd>
      <dt className="text-muted-foreground">duration</dt>
      <dd className="num">
        {formatMs(step.durationMs)}
        {step.durationScope === 'node' && <span className="text-muted-foreground"> · measured at the graph node, shared by the batch</span>}
        {step.durationScope === 'step' && <span className="text-muted-foreground"> · measured for this step</span>}
      </dd>
      {step.at && (
        <>
          <dt className="text-muted-foreground">at</dt>
          <dd className="num">{step.at.replace('T', ' ').replace(/\+00:00$/, 'Z')}</dd>
        </>
      )}
      {entries.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted-foreground">{k.replace(/_/g, ' ')}</dt>
          <dd className="break-words">{detailValue(v)}</dd>
        </div>
      ))}
    </dl>
  )
}

function StepRow({ step, expanded, onToggle, isLast }: { step: OrchestratorStep; expanded: boolean; onToggle: () => void; isLast: boolean }) {
  const flagged = step.status === 'flag' || step.status === 'hold'
  return (
    <li className={cn('animate-feed-in', !isLast && 'border-b border-border/50')} data-status={step.status} data-testid="timeline-step">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className={cn('grid w-full grid-cols-[18px_12px_minmax(0,1fr)_max-content] items-start gap-x-1.5 px-3 py-1.5 text-left text-xs outline-none hover:bg-surface-2 focus-visible:ring-1 focus-visible:ring-ring', expanded && 'bg-surface-1')}
      >
        <span className="num pt-px text-2xs text-muted-foreground">{String(step.order).padStart(2, '0')}</span>
        <span className="pt-px" aria-label={STATUS_LABEL[step.status]}>
          <StatusIcon status={step.status} />
        </span>
        <span className="min-w-0">
          <span className="flex min-w-0 items-baseline gap-1.5">
            <span className={cn('truncate font-medium', flagged ? (step.status === 'flag' ? 'text-red' : 'text-amber') : 'text-foreground/90')}>{step.step}</span>
            <span className="num min-w-0 truncate text-2xs text-muted-foreground" title={step.tool}>
              {step.tool}
            </span>
          </span>
          <span className={cn('block leading-4 break-words', flagged ? 'text-foreground/90' : 'text-foreground/75')}>{step.result || (step.status === 'pending' ? '…' : '—')}</span>
          {expanded && <StepDetail step={step} />}
        </span>
        <span className="num pt-px text-2xs text-muted-foreground" title={step.durationScope === 'node' ? 'measured at the graph node (shared by the batch)' : undefined}>
          {formatMs(step.durationMs)}
        </span>
      </button>
    </li>
  )
}

function InvoiceRow({ p, selected, onClick }: { p: Payment; selected: boolean; onClick: () => void }) {
  const flagged = p.status !== 'vouched'
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        aria-pressed={selected}
        data-selected={selected}
        className={cn(
          'row-interactive grid h-7 w-full grid-cols-[8px_minmax(0,1fr)_max-content] items-center gap-x-2 px-3 text-left text-xs outline-none focus-visible:ring-1 focus-visible:ring-ring',
          selected && 'bg-accent-cool-soft',
        )}
      >
        <span className={cn('size-1.5 rounded-xs', p.lifecycle === 'settled' ? 'bg-muted-foreground/50' : flagged ? (p.status === 'verify' ? 'bg-red' : 'bg-amber') : 'bg-green')} aria-hidden="true" />
        <span className="flex min-w-0 items-baseline gap-1.5">
          <span className="num shrink-0 text-foreground/90">{p.invoiceNumber}</span>
          <span className="truncate text-muted-foreground">{p.vendor.name}</span>
        </span>
        <span className="num text-muted-foreground">{formatMoney(p.amount)}</span>
      </button>
    </li>
  )
}

/**
 * Orchestrator timeline. Collapsed: a 36px rail. Expanded: the invoices (most recent first) and, for the
 * selected one, the ordered steps the orchestrator ran: step, tool/model, duration, status and result.
 * Clicking a step expands the inputs/outputs summary. Live mode polls while the run is in progress.
 */
export function OrchestratorTimeline({ className }: { className?: string }) {
  const { payments } = usePayments()
  const { mode } = useApi()
  const { activeId, open, feedOpen, setFeedOpen, feedPaused, setFeedPaused } = useUi()
  const [expanded, setExpanded] = useState<{ id: string; order: number } | null>(null)
  const [listOpen, setListOpen] = useState(true)
  const recent = useMemo(() => byMostRecent(payments), [payments])
  const selected = payments.find((p) => p.id === activeId) ?? recent[0]
  const activeRuns = useLiveRuns(feedOpen)
  const { timeline, visible, loading, error } = useOrchestratorTimeline(feedOpen ? selected : undefined, feedPaused)

  const expandedOrder = expanded && expanded.id === selected?.id ? expanded.order : null

  const steps = timeline?.steps.slice(0, visible) ?? []
  const flagged = steps.filter((s) => s.status === 'flag' || s.status === 'hold').length
  const inProgress = (timeline != null && !timeline.complete) || (timeline != null && visible < timeline.steps.length) || activeRuns.length > 0
  const status = timeline ? `${steps.length}/${timeline.steps.length} steps · ${flagged} flagged` : loading ? 'loading…' : `${payments.length} invoices`

  if (!feedOpen) {
    return (
      <button
        type="button"
        onClick={() => setFeedOpen(true)}
        className={cn('flex w-topbar shrink-0 flex-col items-center gap-2 border-r bg-background pt-3 text-muted-foreground outline-none hover:text-foreground focus-visible:ring-1 focus-visible:ring-ring', className)}
        aria-label={`Orchestrator timeline · ${status}. Expand.`}
        aria-expanded={false}
      >
        <span className={cn('size-1.5 rounded-xs', activeRuns.length > 0 ? 'bg-accent-cool animate-pulse-soft' : 'bg-muted-foreground/60')} aria-hidden="true" />
        <span className="num text-2xs whitespace-nowrap [writing-mode:vertical-rl]">Orchestrator timeline</span>
      </button>
    )
  }

  return (
    <section aria-label="Orchestrator timeline" className={cn('flex shrink-0 flex-col border-r bg-background', PANE_W, className)}>
      <header className="flex h-8 shrink-0 items-center justify-between gap-2 border-b px-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className={cn('size-1.5 rounded-xs', feedPaused ? 'bg-muted-foreground/60' : inProgress ? 'bg-accent-cool animate-pulse-soft' : 'bg-green')} aria-hidden="true" />
          <h2 className="truncate text-xs font-medium text-foreground/90">Orchestrator timeline</h2>
        </div>
        <div className="flex items-center gap-0.5">
          <button type="button" className="num h-5 rounded-xs px-1.5 text-2xs text-muted-foreground hover:bg-surface-2 hover:text-foreground" onClick={() => setFeedPaused(!feedPaused)} aria-pressed={feedPaused}>
            {feedPaused ? 'resume' : 'pause'}
          </button>
          <button type="button" className="num h-5 rounded-xs px-1.5 text-2xs text-muted-foreground hover:bg-surface-2 hover:text-foreground" onClick={() => setFeedOpen(false)} aria-label="Collapse orchestrator timeline">
            ‹
          </button>
        </div>
      </header>

      <section aria-label="Invoices" className="shrink-0 border-b">
        <button type="button" onClick={() => setListOpen((v) => !v)} aria-expanded={listOpen} className="label-caps flex h-6 w-full items-center justify-between bg-surface-1 px-3 hover:text-foreground">
          <span>invoices · most recent first</span>
          <span className="num">{listOpen ? '−' : `${recent.length}`}</span>
        </button>
        {listOpen && (
          <ol className="max-h-[200px] overflow-y-auto">
            {recent.map((p) => (
              <InvoiceRow key={p.id} p={p} selected={p.id === selected?.id} onClick={() => open(p.id)} />
            ))}
            {recent.length === 0 && <li className="px-3 py-2 text-xs text-muted-foreground">No invoices yet.</li>}
          </ol>
        )}
      </section>

      <div className="flex h-6 shrink-0 items-center justify-between gap-2 bg-surface-1 px-3">
        <h3 className="label-caps flex min-w-0 items-center gap-1.5">
          <span className="truncate">{selected ? `${selected.invoiceNumber} · ${selected.vendor.name}` : 'steps'}</span>
        </h3>
        <span className="num flex items-center gap-1 text-2xs text-muted-foreground">
          {(loading || inProgress) && !feedPaused && <Loader2 className="size-2.5 animate-spin" aria-hidden="true" />}
          {timeline ? `${steps.length}/${timeline.steps.length} · ${flagged} flagged` : ''}
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {error && (
          <p className="px-3 py-2 text-xs text-amber" role="alert">
            Timeline unavailable: {error}
          </p>
        )}
        {!error && selected && timeline && steps.length === 0 && <p className="px-3 py-2 text-xs text-muted-foreground">Waiting for the first step…</p>}
        {!error && !selected && <p className="px-3 py-2 text-xs text-muted-foreground">Select an invoice to see what the orchestrator ran.</p>}
        <ol aria-label={selected ? `Steps for ${selected.invoiceNumber}` : 'Steps'}>
          {steps.map((s, i) => (
            <StepRow key={`${s.order}-${s.step}`} step={s} expanded={expandedOrder === s.order} onToggle={() => setExpanded((cur) => (cur?.id === selected?.id && cur?.order === s.order ? null : { id: selected?.id ?? '', order: s.order }))} isLast={i === steps.length - 1} />
          ))}
        </ol>
      </div>

      <footer className="num flex h-6 shrink-0 items-center justify-between border-t px-3 text-2xs text-muted-foreground">
        <span>{mode === 'live' ? (timeline ? `run ${timeline.runId} · ${timeline.runStatus.replace(/_/g, ' ')}` : 'live') : 'mock run · demo data'}</span>
        <span>{timeline ? `${formatMs(timeline.totals.measuredMs)} measured` : ''}</span>
      </footer>
    </section>
  )
}
