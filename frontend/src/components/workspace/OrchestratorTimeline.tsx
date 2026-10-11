import { useEffect, useMemo, useState } from 'react'
import { useApi } from '@/api/ApiProvider'
import type { OrchestratorStep, Payment, StepKind, StepStatus } from '@/api/types'
import { formatMoney } from '@/lib/format'
import { cn } from '@/lib/utils'
import { usePayments } from '@/store/PaymentsProvider'
import { useUi } from '@/store/UiProvider'

/** Live runs keep moving after the page loads; refresh the payloads (and their steps) while the rail is open. */
const LIVE_REFRESH_MS = 3000

const GLYPH: Record<StepStatus, string> = { ok: '✓', flagged: '!', hold: '■', denied: '✕', pending: '○', skipped: '–', failed: '✕' }
const TONE: Record<StepStatus, string> = {
  ok: 'text-green',
  flagged: 'text-amber',
  hold: 'text-amber',
  denied: 'text-red',
  pending: 'text-muted-foreground',
  skipped: 'text-muted-foreground/60',
  failed: 'text-red',
}
const KIND_TAG: Record<StepKind, { text: string; cls: string; title: string }> = {
  deterministic: { text: 'code', cls: 'text-muted-foreground border-border', title: 'deterministic code: no model, no LLM' },
  llm: { text: 'llm', cls: 'text-accent-cool border-accent-cool/40', title: 'LLM call (text generation)' },
  model: { text: 'model', cls: 'text-accent-cool border-accent-cool/40', title: 'model call (classifier / scorer / embedding)' },
  human: { text: 'owner', cls: 'text-foreground/80 border-foreground/30', title: 'human decision' },
}

function fmtMs(ms: number | null): string {
  if (ms == null) return ''
  if (ms < 1) return `${ms.toFixed(1)} ms`
  if (ms < 1000) return `${Math.round(ms)} ms`
  return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`
}

function fmtTime(iso?: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

/** Sum of per-invoice step time; run- and batch-scoped steps are shared, so they are not added. */
function cardMs(steps: OrchestratorStep[]): number {
  return steps.reduce((s, x) => s + (x.durationScope === 'card' && x.durationMs != null ? x.durationMs : 0), 0)
}

function worst(steps: OrchestratorStep[]): StepStatus {
  const order: StepStatus[] = ['failed', 'denied', 'hold', 'flagged', 'pending', 'ok', 'skipped']
  for (const st of order) if (steps.some((s) => s.status === st)) return st
  return 'ok'
}

function counts(steps: OrchestratorStep[]) {
  const n = { deterministic: 0, llm: 0, model: 0, human: 0 }
  for (const s of steps) n[s.kind]++
  return n
}

function StepRow({ step, expanded, onToggle, last }: { step: OrchestratorStep; expanded: boolean; onToggle: () => void; last: boolean }) {
  const tag = KIND_TAG[step.kind]
  const shared = step.durationScope && step.durationScope !== 'card'
  return (
    <li className="relative">
      {!last && <span aria-hidden="true" className="absolute top-[18px] bottom-[-6px] left-[15px] w-px bg-border" />}
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className={cn('grid w-full grid-cols-[22px_minmax(0,1fr)_auto] items-baseline gap-x-1.5 py-1 pr-2 pl-2 text-left outline-none hover:bg-surface-2 focus-visible:ring-1 focus-visible:ring-ring', expanded && 'bg-surface-1')}
      >
        <span className={cn('num relative z-10 w-[14px] text-center text-xs', TONE[step.status])} aria-label={step.status}>
          {GLYPH[step.status]}
        </span>
        <span className="flex min-w-0 items-baseline gap-1.5">
          <span className="num shrink-0 text-xs text-foreground">{step.label}</span>
          <span className={cn('num shrink-0 rounded-xs border px-1 text-[9px] leading-[13px]', tag.cls)} title={tag.title}>
            {tag.text}
          </span>
          <span className="num truncate text-2xs text-muted-foreground" title={step.tool}>
            {step.tool}
          </span>
        </span>
        <span className={cn('num text-2xs tabular-nums', shared ? 'text-muted-foreground/70' : 'text-muted-foreground')} title={shared ? `${step.durationScope}-level: shared by every invoice in the ${step.durationScope}` : 'measured on this invoice'}>
          {fmtMs(step.durationMs)}
          {shared && '*'}
        </span>
        <span className={cn('col-start-2 col-span-2 text-xs leading-4', expanded ? 'break-words' : 'truncate', step.status === 'flagged' || step.status === 'hold' ? 'text-amber' : step.status === 'denied' || step.status === 'failed' ? 'text-red' : 'text-foreground/85')} title={expanded ? undefined : step.summary}>
          {step.summary || '—'}
        </span>
      </button>
      {expanded && (
        <dl className="num grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 gap-y-0.5 border-b bg-surface-1 py-1.5 pr-2 pl-[30px] text-2xs">
          <dt className="text-muted-foreground">tool</dt>
          <dd className="break-words text-foreground/85">{step.tool}</dd>
          <dt className="text-muted-foreground">kind</dt>
          <dd className="text-foreground/85">{tag.title}</dd>
          {step.engine && (
            <>
              <dt className="text-muted-foreground">engine</dt>
              <dd className="text-foreground/85">
                {step.engine}
                {step.confidence != null && ` · confidence ${step.confidence.toFixed(2)}`}
              </dd>
            </>
          )}
          {step.node && (
            <>
              <dt className="text-muted-foreground">node</dt>
              <dd className="text-foreground/85">{step.node}</dd>
            </>
          )}
          {step.durationMs != null && (
            <>
              <dt className="text-muted-foreground">time</dt>
              <dd className="text-foreground/85">
                {fmtMs(step.durationMs)}
                {step.durationScope && step.durationScope !== 'card' && ` · ${step.durationScope}-level (shared, not per invoice)`}
              </dd>
            </>
          )}
          {(step.modelCalls != null || step.llmCalls != null || step.tokens != null) && (
            <>
              <dt className="text-muted-foreground">calls</dt>
              <dd className="text-foreground/85">
                {[step.modelCalls != null && `${step.modelCalls} model`, step.llmCalls != null && `${step.llmCalls} llm`, step.tokens != null && `${step.tokens} tokens`].filter(Boolean).join(' · ')}
              </dd>
            </>
          )}
          {step.lane && (
            <>
              <dt className="text-muted-foreground">lane</dt>
              <dd className="text-foreground/85">{step.lane.replace(/_/g, ' ')}</dd>
            </>
          )}
          {step.match && (
            <>
              <dt className="text-muted-foreground">match</dt>
              <dd className="text-foreground/85">{step.match}</dd>
            </>
          )}
          {step.flags && step.flags.length > 0 && (
            <>
              <dt className="text-muted-foreground">flags</dt>
              <dd className="text-amber">{step.flags.join(' · ')}</dd>
            </>
          )}
          {step.txId && (
            <>
              <dt className="text-muted-foreground">tx</dt>
              <dd className="truncate text-foreground/85">
                {step.explorerUrl ? (
                  <a href={step.explorerUrl} target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline">
                    {step.txId}
                  </a>
                ) : (
                  step.txId
                )}
              </dd>
            </>
          )}
          {step.at && (
            <>
              <dt className="text-muted-foreground">at</dt>
              <dd className="text-foreground/85">{fmtTime(step.at)}</dd>
            </>
          )}
          {step.detail.length > 0 && (
            <>
              <dt className="text-muted-foreground">detail</dt>
              <dd>
                <ul className="space-y-0.5">
                  {step.detail.map((line, i) => (
                    <li key={i} className="break-words text-foreground/85">
                      {line}
                    </li>
                  ))}
                </ul>
              </dd>
            </>
          )}
        </dl>
      )}
    </li>
  )
}

function Timeline({ payment }: { payment: Payment }) {
  const [openStep, setOpenStep] = useState<string | null>(null)
  const steps = payment.steps
  if (steps.length === 0) {
    return <p className="px-3 py-2 text-2xs text-muted-foreground">No orchestrator steps recorded for this invoice.</p>
  }
  const n = counts(steps)
  return (
    <div className="border-b bg-background">
      <ol className="py-0.5">
        {steps.map((s, i) => (
          <StepRow key={`${s.id}-${s.seq}`} step={s} last={i === steps.length - 1} expanded={openStep === `${s.id}-${s.seq}`} onToggle={() => setOpenStep((cur) => (cur === `${s.id}-${s.seq}` ? null : `${s.id}-${s.seq}`))} />
        ))}
      </ol>
      <p className="num flex h-5 items-center gap-2 border-t px-3 text-[9px] text-muted-foreground">
        <span>{n.deterministic} code</span>
        <span>{n.model} model</span>
        <span>{n.llm} llm</span>
        <span>{n.human} owner</span>
        <span className="ml-auto">{fmtMs(cardMs(steps))} on this invoice · * shared</span>
      </p>
    </div>
  )
}

function InvoiceRow({ payment: p, selected, onSelect }: { payment: Payment; selected: boolean; onSelect: () => void }) {
  const status = worst(p.steps)
  const last = p.steps[p.steps.length - 1]
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-expanded={selected}
      className={cn('grid min-h-row w-full grid-cols-[14px_minmax(0,1fr)_auto] items-center gap-x-1.5 border-b px-3 text-left text-xs outline-none hover:bg-surface-2 focus-visible:ring-1 focus-visible:ring-ring', selected && 'bg-accent-cool-soft')}
    >
      <span className={cn('num text-center', TONE[status])} aria-label={status}>
        {GLYPH[status]}
      </span>
      <span className="flex min-w-0 flex-col">
        <span className="flex min-w-0 items-baseline gap-1.5">
          <span className="num truncate text-foreground">{p.invoiceNumber}</span>
          <span className="truncate text-muted-foreground">{p.vendor.name}</span>
        </span>
        <span className="num truncate text-2xs text-muted-foreground">{last ? `${last.label.toLowerCase()} · ${last.summary}` : 'no steps'}</span>
      </span>
      <span className="num flex flex-col items-end text-2xs text-muted-foreground">
        <span className="text-foreground/85">{formatMoney(p.amount)}</span>
        <span>
          {p.steps.length} steps · {fmtMs(cardMs(p.steps))}
        </span>
      </span>
    </button>
  )
}

/**
 * Orchestrator timeline. Collapsed: a 36px rail. Expanded: one row per invoice; the selected invoice
 * (keyboard cursor / open card) unfolds its timeline inline: every step the graph ran, in order, with the
 * tool or model that did it, whether it was code / llm / model / owner, its duration, and a one-line result.
 * Clicking a step shows the detail lines. Live mode reads the backend `steps[]`; mock mode ships fixtures.
 */
export function OrchestratorTimeline({ className }: { className?: string }) {
  const { payments, reload } = usePayments()
  const { mode } = useApi()
  const { activeId, open, feedOpen, setFeedOpen, feedPaused, setFeedPaused } = useUi()

  useEffect(() => {
    if (mode !== 'live' || !feedOpen || feedPaused) return
    const t = setInterval(() => void reload(), LIVE_REFRESH_MS)
    return () => clearInterval(t)
  }, [mode, feedOpen, feedPaused, reload])

  const ordered = useMemo(() => [...payments].sort((a, b) => new Date(b.receivedAt).getTime() - new Date(a.receivedAt).getTime()), [payments])
  const totals = useMemo(() => {
    const all = payments.flatMap((p) => p.steps)
    return { steps: all.length, ...counts(all) }
  }, [payments])
  const status = `${payments.length} invoices · ${totals.steps} steps`

  if (!feedOpen) {
    return (
      <button
        type="button"
        onClick={() => setFeedOpen(true)}
        className={cn('flex w-topbar shrink-0 flex-col items-center gap-2 border-r bg-background pt-3 text-muted-foreground outline-none hover:text-foreground focus-visible:ring-1 focus-visible:ring-ring', className)}
        aria-label={`Orchestrator timeline · ${status}. Expand.`}
        aria-expanded={false}
      >
        <span className={cn('size-1.5 rounded-xs', mode === 'live' && !feedPaused ? 'bg-accent-cool animate-pulse-soft' : 'bg-muted-foreground/60')} aria-hidden="true" />
        <span className="num text-2xs whitespace-nowrap [writing-mode:vertical-rl]">orchestrator · {status}</span>
      </button>
    )
  }

  return (
    <section aria-label="Orchestrator timeline" className={cn('flex w-[320px] shrink-0 flex-col border-r bg-background', className)}>
      <header className="flex h-8 shrink-0 items-center justify-between gap-2 border-b px-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className={cn('size-1.5 rounded-xs', mode === 'live' && !feedPaused ? 'bg-accent-cool animate-pulse-soft' : 'bg-muted-foreground/60')} aria-hidden="true" />
          <h2 className="num truncate text-xs text-foreground/85">
            orchestrator <span className="text-muted-foreground">· {status}</span>
          </h2>
        </div>
        <div className="flex items-center gap-0.5">
          {mode === 'live' && (
            <button type="button" className="num h-5 rounded-xs px-1.5 text-2xs text-muted-foreground hover:bg-surface-2 hover:text-foreground" onClick={() => setFeedPaused(!feedPaused)} aria-pressed={feedPaused} title="pause / resume live refresh">
              {feedPaused ? 'resume' : 'pause'}
            </button>
          )}
          <button type="button" className="num h-5 rounded-xs px-1.5 text-2xs text-muted-foreground hover:bg-surface-2 hover:text-foreground" onClick={() => setFeedOpen(false)} aria-label="Collapse orchestrator timeline">
            ‹
          </button>
        </div>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {ordered.length === 0 && <p className="px-3 py-2 text-2xs text-muted-foreground">No invoices yet.</p>}
        {ordered.map((p) => {
          const selected = p.id === activeId
          return (
            <div key={p.id}>
              <InvoiceRow payment={p} selected={selected} onSelect={() => open(p.id)} />
              {selected && <Timeline key={`${p.id}-${p.steps.length}`} payment={p} />}
            </div>
          )
        })}
      </div>
      <footer className="num flex h-6 shrink-0 items-center gap-2 border-t px-3 text-2xs text-muted-foreground">
        <span className={TONE.ok}>✓</span> ok <span className={TONE.flagged}>!</span> flagged <span className={TONE.hold}>■</span> hold <span className={TONE.pending}>○</span> waiting
        <span className="ml-auto">{mode === 'live' ? (feedPaused ? 'paused' : 'live') : 'mock'}</span>
      </footer>
    </section>
  )
}
