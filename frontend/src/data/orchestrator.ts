import type { Payment } from '@/api/types'
import { APPROVAL_LIMIT } from '@/data/payments'

/**
 * Orchestrator timeline: the ordered steps one payment went through, the tool or model that actually ran
 * each step, its measured duration, a status and a one-line result. Live mode reads
 * GET /v1/payments/{id}/timeline (built from the run's node events); mock mode derives the same shape from
 * the demo payments so the pane tells one consistent story.
 */

export type StepStatus = 'ok' | 'flag' | 'hold' | 'pending'

export interface OrchestratorStep {
  order: number
  step: string
  /** Graph node that ran the step (intake, resolve, sender, kernel, score, policy, settle, …). */
  node: string
  /** The tool or model that actually ran, e.g. "Excel parser (openpyxl)", "Strands Decider 2B", "Cedar (cedarpy)". */
  tool: string
  engine: string | null
  durationMs: number | null
  /** "node": measured once for the whole batch at the graph node; "step": measured for this step alone. */
  durationScope: 'node' | 'step' | null
  status: StepStatus
  result: string
  at: string | null
  /** Inputs/outputs summary for the expanded row. */
  detail: Record<string, unknown>
}

export interface OrchestratorTimeline {
  paymentId: string
  runId: string
  runStatus: string
  complete: boolean
  lastSeq: number
  steps: OrchestratorStep[]
  totals: { steps: number; flagged: number; measuredMs: number }
}

type Json = Record<string, unknown>
const rec = (v: unknown): Json => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Json) : {})
const str = (v: unknown, fallback = ''): string => (typeof v === 'string' ? v : v == null ? fallback : String(v))
const pick = (o: Json, ...keys: string[]): unknown => {
  for (const k of keys) if (o[k] !== undefined) return o[k]
  return undefined
}

function toStatus(v: unknown): StepStatus {
  const s = str(v).toLowerCase()
  if (s === 'ok' || s === 'flag' || s === 'hold' || s === 'pending') return s
  if (s === 'skipped') return 'ok'
  return 'ok'
}

function toMs(v: unknown): number | null {
  if (v == null) return null
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? Math.round(n) : null
}

export function normalizeStep(raw: unknown, index: number): OrchestratorStep {
  const s = rec(raw)
  const scope = str(pick(s, 'duration_scope', 'durationScope'))
  return {
    order: toMs(pick(s, 'order')) ?? index + 1,
    step: str(pick(s, 'step', 'name'), `step ${index + 1}`),
    node: str(pick(s, 'node')),
    tool: str(pick(s, 'tool'), '—'),
    engine: pick(s, 'engine') == null ? null : str(pick(s, 'engine')),
    durationMs: toMs(pick(s, 'duration_ms', 'durationMs')),
    durationScope: scope === 'node' || scope === 'step' ? scope : null,
    status: toStatus(pick(s, 'status')),
    result: str(pick(s, 'result')),
    at: pick(s, 'at') == null ? null : str(pick(s, 'at')),
    detail: rec(pick(s, 'detail')),
  }
}

export function normalizeTimeline(raw: unknown): OrchestratorTimeline {
  const t = rec(raw)
  const stepsRaw = Array.isArray(t.steps) ? t.steps : []
  const steps = stepsRaw.map(normalizeStep).sort((a, b) => a.order - b.order)
  const totals = rec(pick(t, 'totals'))
  const flagged = steps.filter((s) => s.status === 'flag' || s.status === 'hold').length
  return {
    paymentId: str(pick(t, 'payment_id', 'paymentId', 'card_id', 'cardId')),
    runId: str(pick(t, 'run_id', 'runId')),
    runStatus: str(pick(t, 'run_status', 'runStatus', 'status'), 'unknown'),
    complete: pick(t, 'complete') == null ? true : Boolean(pick(t, 'complete')),
    lastSeq: toMs(pick(t, 'last_seq', 'lastSeq')) ?? 0,
    steps,
    totals: {
      steps: toMs(pick(totals, 'steps')) ?? steps.length,
      flagged: toMs(pick(totals, 'flagged')) ?? flagged,
      measuredMs: toMs(pick(totals, 'measured_ms', 'measuredMs')) ?? steps.reduce((sum, s) => sum + (s.durationMs ?? 0), 0),
    },
  }
}

export function formatMs(ms: number | null): string {
  if (ms == null) return '—'
  if (ms < 1) return '<1 ms'
  if (ms >= 1000) return `${(ms / 1000).toFixed(ms >= 10_000 ? 0 : 1)} s`
  return `${ms} ms`
}

/** Most recent first, by receivedAt (then id for a stable order). */
export function byMostRecent(payments: Payment[]): Payment[] {
  return [...payments].sort((a, b) => {
    const d = new Date(b.receivedAt).getTime() - new Date(a.receivedAt).getTime()
    return d !== 0 ? d : b.id.localeCompare(a.id)
  })
}

// ------------------------------------------------------------------------------------------- mock ----

function hash(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619)
  return h >>> 0
}

function money(n: number): string {
  return `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function domainOf(p: Payment): string {
  return `${p.vendor.name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '')
    .slice(0, 18)}.${p.vendor.country === 'US' ? 'com' : p.vendor.country.toLowerCase()}`
}

function riskClass(p: Payment): string {
  if (p.risk === 'changed_bank') return 'ato_bec'
  if (p.risk === 'duplicate_or_split') return 'insider'
  if (p.risk === 'unrecognized_vendor') return 'fake_vendor'
  return 'honest'
}

function holdReason(p: Payment): string {
  if (p.risk === 'changed_bank') return 'bank details changed without out-of-band confirmation'
  if (p.risk === 'duplicate_or_split') return p.relation?.kind === 'split_with' ? 'possible split invoices under the approval limit' : 'possible duplicate invoice'
  if (p.risk === 'unrecognized_vendor') return 'vendor shares bank account or tax id with other vendors'
  return 'owner review'
}

/**
 * Deterministic mock timeline for one demo payment. Node durations are stable per payment id so the pane
 * does not flicker; every result line is derived from the payment's own evidence, risk and lifecycle.
 */
export function mockTimelineFor(p: Payment, allPayments: Payment[] = []): OrchestratorTimeline {
  const h = hash(p.id)
  const ms = (base: number, spread: number, salt: number) => base + ((h >>> (salt % 24)) % (spread + 1))
  const steps: Omit<OrchestratorStep, 'order'>[] = []
  const add = (s: Omit<OrchestratorStep, 'order' | 'at'> & { at?: string | null }) => steps.push({ at: null, ...s })
  const flagged = p.status !== 'vouched'
  const concerns = p.evidence.filter((e) => e.direction === 'concern').sort((a, b) => b.weight - a.weight)
  const known = p.vendor.paymentsCompleted > 0 || p.status === 'vouched'
  const acct = String(1000 + (h % 9000))
  const email = p.source === 'email'
  const file = email ? `${p.invoiceNumber}.pdf` : `${p.invoiceNumber}.xlsx`
  const fmt = email ? 'pdf_attachment' : 'excel_attachment'
  const parser = email ? 'PDF text parser (pypdf + pdfplumber)' : 'Excel parser (openpyxl)'
  const parserShort = email ? 'PDF text parser' : 'Excel parser'
  const intakeMs = ms(6, 9, 1)
  const kernelMs = ms(1, 2, 7)

  add({ step: 'intake', node: 'intake', tool: email ? 'email intake (.eml)' : 'file upload', engine: 'deterministic', durationMs: intakeMs, durationScope: 'node', status: 'ok', result: `received via ${p.source} · 1 attachment: ${file}`, at: p.receivedAt, detail: { source: p.source, documents: [{ filename: file, kind: email ? 'pdf' : 'xlsx' }], submitted_by: 'ap-inbox' } })
  add({ step: 'format decision', node: 'intake', tool: 'deterministic route', engine: 'deterministic', durationMs: intakeMs, durationScope: 'node', status: 'ok', result: `deterministic route: ${fmt} → ${parserShort} · 0 model calls, the route was obvious to code`, detail: { format: fmt, tool: email ? 'pdf_text' : 'excel_reader', decider_calls: 0, llm_calls: 0, format_confidence: 1 } })
  add({ step: 'read/parse', node: 'intake', tool: parser, engine: 'deterministic', durationMs: intakeMs, durationScope: 'node', status: 'ok', result: `${parser}: amount ${money(p.amount)} · invoice ${p.invoiceNumber} · vendor ${p.vendor.name} · bank ····${acct}`, detail: { amount_origin: 'source', amount_cents: Math.round(p.amount * 100), currency: p.currency, due_date: p.dueDate.slice(0, 10) } })

  const matchedOn = known ? (p.vendor.paymentsCompleted > 0 ? ['tax_id', 'bank_account'] : ['tax_id']) : []
  add({
    step: 'vendor screen',
    node: 'resolve',
    tool: 'vendor resolver (master file)',
    engine: 'deterministic',
    durationMs: ms(2, 3, 3),
    durationScope: 'node',
    status: known ? 'ok' : 'flag',
    result: known ? `known vendor ${p.vendor.name} · matched on ${matchedOn.join(', ')} · confidence 1.00` : `not on the master file · claim '${p.vendor.name}' has no match`,
    detail: { status: known ? 'known' : 'new', matched_on: matchedOn, payments_completed: p.vendor.paymentsCompleted, since: p.vendor.since.slice(0, 10) },
  })

  if (email) {
    const senderFlag = p.risk === 'changed_bank'
    add({
      step: 'sender check',
      node: 'sender',
      tool: 'SPF/DKIM/DMARC + lookalike-domain check',
      engine: 'deterministic',
      durationMs: ms(0, 1, 5),
      durationScope: 'node',
      status: senderFlag ? 'flag' : 'ok',
      result: senderFlag ? '1 flag(s): new sender for known vendor' : `authentication passed for ${domainOf(p)}`,
      detail: { from_domain: domainOf(p), auth_pass: true, flags: senderFlag ? ['new_sender_for_known_vendor'] : [] },
    })
  }

  const bank = p.risk === 'changed_bank'
  add({ step: 'bank check', node: 'kernel', tool: 'kernel: bank-details check', engine: 'deterministic', durationMs: kernelMs, durationScope: 'node', status: bank ? 'flag' : 'ok', result: bank ? 'master-file bank details changed 2 day(s) ago, no call-back on record' : `account matches the master file (····${acct})`, detail: { bank_mismatch: false, bank_change_recent: bank, bank_change_confirmed: false } })

  const dup = p.relation?.kind === 'duplicate_of'
  const split = p.relation?.kind === 'split_with'
  const partner = p.relation ? allPayments.find((x) => x.id === p.relation!.paymentId) : undefined
  add({
    step: 'duplicate check',
    node: 'kernel',
    tool: 'kernel: duplicate/split detector',
    engine: 'deterministic',
    durationMs: kernelMs,
    durationScope: 'node',
    status: dup || split ? 'flag' : 'ok',
    result: dup
      ? `possible duplicate of invoice ${partner?.invoiceNumber ?? p.invoiceNumber} in this batch`
      : split
        ? `split pattern: 2 invoices just under the approval limit, together ${money(p.amount + (partner?.amount ?? p.amount))}`
        : 'no duplicate · no split pattern',
    detail: { duplicate_of: dup ? partner?.id ?? null : null, split_group: split ? [p.id, partner?.id].filter(Boolean) : [] },
  })

  const ringKinds = p.ring ? countRing(p.ring) : {}
  const ringBits = Object.entries(ringKinds).map(([k, n]) => `${k} shared with ${n} other vendor(s)`)
  add({ step: 'ring check', node: 'kernel', tool: 'vendor graph (shared attributes)', engine: 'deterministic', durationMs: kernelMs, durationScope: 'node', status: ringBits.length ? 'flag' : 'ok', result: ringBits.length ? `ring check: ${ringBits.join('; ')}` : 'no shared bank account, tax id, phone or address', detail: { shared_attributes: ringKinds } })

  const over = p.amount > APPROVAL_LIMIT
  const near = !over && p.amount >= APPROVAL_LIMIT * 0.9
  add({
    step: 'amount check',
    node: 'kernel',
    tool: 'kernel: amount & limits (integer cents)',
    engine: 'deterministic',
    durationMs: kernelMs,
    durationScope: 'node',
    status: 'ok',
    result: `${money(p.amount)} payable · ${over ? `over the approval limit ${money(APPROVAL_LIMIT)} (owner approval)` : near ? `just under the approval limit ${money(APPROVAL_LIMIT)}` : `under the approval limit ${money(APPROVAL_LIMIT)}`}`,
    detail: { over_approval_limit: over, near_approval_limit: near, approval_limit: APPROVAL_LIMIT, line_items_match: true, amount_origin_ok: true },
  })

  const cls = riskClass(p)
  add({
    step: 'score',
    node: 'score',
    tool: 'VouchNet scorer (inference service) + LIME',
    engine: 'inference-service',
    durationMs: ms(14, 20, 11),
    durationScope: 'node',
    status: flagged || p.trustScore < 60 ? 'flag' : 'ok',
    result: `legitimacy ${p.trustScore}% · top class ${cls.replace('_', ' ')}` + (concerns[0] ? ` · top factor: ${concerns[0].label}` : ''),
    detail: { legitimacy: p.trustScore / 100, top_class: cls, lime: p.evidence.slice(0, 5).map((e) => ({ label: e.label, weight: e.direction === 'concern' ? -e.weight : e.weight })) },
  })

  if (flagged) {
    add({ step: 'investigate', node: 'investigate', tool: `template investigator [${cls}] (no model call)`, engine: 'deterministic', durationMs: ms(0, 1, 13), durationScope: 'node', status: 'flag', result: concerns.map((c) => c.label).slice(0, 2).join('; ') || 'risk above normal for this vendor', detail: { investigator: cls, source: 'template', vendor_questions: p.checklist.slice(0, 2).map((c) => c.text) } })
  }

  const lane = p.status !== 'vouched' ? 'hold' : p.fastPayEligible ? 'fast_pay' : 'standard'
  add({
    step: 'policy',
    node: 'policy',
    tool: 'release policy (Cedar-style, default deny)',
    engine: 'deterministic',
    durationMs: ms(0, 1, 17),
    durationScope: 'node',
    status: lane === 'hold' ? 'hold' : 'ok',
    result: lane === 'hold' ? `lane: hold · ${holdReason(p)}` : lane === 'fast_pay' ? 'lane: fast pay · verified small vendor under the standing limit, pays today' : "lane: standard · passes release policy, waits for the owner's batch approval",
    detail: { lane, reasons: lane === 'hold' ? [holdReason(p)] : [], actions_evaluated: ['payment:release', 'payment:fast_pay'] },
  })
  add({ step: 'funding', node: 'funding', tool: 'cash-forecast recommender', engine: 'deterministic', durationMs: 0, durationScope: 'node', status: 'ok', result: lane === 'hold' ? 'wait · on hold until resolved' : lane === 'fast_pay' ? 'pay now · fast-pay lane: verified small vendor paid today' : `schedule for ${p.dueDate.slice(0, 10)} · cash keeps working until the due date`, detail: { action: lane === 'hold' ? 'wait' : lane === 'fast_pay' ? 'pay_now' : 'schedule' } })
  add({ step: 'explain', node: 'explain', tool: 'template explanation (no model call)', engine: 'deterministic', durationMs: ms(0, 1, 19), durationScope: 'node', status: 'ok', result: p.reason, detail: { source: 'template' } })

  const settled = p.lifecycle === 'settled'
  const approved = p.lifecycle === 'approved' || p.lifecycle === 'appealed' || settled
  if (lane === 'fast_pay' && settled && p.auditNotes.length === 0) {
    add({ step: 'owner approval', node: 'fast_pay', tool: 'standing rule (no interrupt)', engine: 'deterministic', durationMs: null, durationScope: null, status: 'ok', result: 'not required · fast-pay standing rule for verified small vendors', detail: { lane } })
  } else if (approved) {
    const note = p.auditNotes[0]
    add({ step: 'authorization', node: 'policy', tool: 'Cedar (cedarpy)', engine: 'cedar', durationMs: null, durationScope: null, status: 'ok', result: 'Cedar (cedarpy): approve allowed for Owner · P-01 owner may approve', at: note?.at ?? null, detail: { principal: 'Owner', action: 'approve', allowed: true, rules: ['P-01'] } })
    add({ step: 'owner approval', node: 'settle', tool: 'owner (human in the loop)', engine: 'owner', durationMs: null, durationScope: null, status: 'ok', result: `approved by ${note?.author ?? 'Dana'}` + (note?.text ? ` · ${note.text}` : ''), at: note?.at ?? null, detail: { actor: note?.author ?? 'Dana' } })
  } else if (lane === 'hold') {
    add({ step: 'owner approval', node: 'settle', tool: 'owner (human in the loop)', engine: 'owner', durationMs: null, durationScope: null, status: 'hold', result: `on hold, not denied · ${p.checklist[0]?.text ?? 'owner review'}`, detail: { required_actions: p.checklist.map((c) => c.text) } })
  } else {
    add({ step: 'owner approval', node: 'settle', tool: 'owner (human in the loop)', engine: 'owner', durationMs: null, durationScope: null, status: 'pending', result: "waiting at the Strands interrupt for the owner's batch approval", detail: {} })
  }
  if (settled) {
    const tx = (h.toString(16) + hash(p.invoiceNumber).toString(16)).toUpperCase().padStart(16, '0')
    add({ step: 'authorization', node: 'settle', tool: 'Cedar (cedarpy)', engine: 'cedar', durationMs: null, durationScope: null, status: 'ok', result: 'Cedar (cedarpy): settle allowed for System · P-04 settle after owner approval', detail: { principal: 'System', action: 'settle', allowed: true } })
    add({ step: 'settlement', node: 'settle', tool: 'XRPL testnet settlement', engine: 'xrpl', durationMs: ms(1800, 1400, 21), durationScope: 'node', status: 'ok', result: `settled ${money(p.amount)} via ${lane === 'fast_pay' ? 'fast pay' : 'standard'} lane · tx ${tx.slice(0, 10)}…`, detail: { tx_id: tx, network: 'XRPL Testnet (simulated)', lane } })
  }

  const ordered: OrchestratorStep[] = steps.map((s, i) => ({ ...s, order: i + 1 }))
  const flaggedCount = ordered.filter((s) => s.status === 'flag' || s.status === 'hold').length
  return {
    paymentId: p.id,
    runId: 'run-demo',
    runStatus: 'completed',
    complete: true,
    lastSeq: ordered.length,
    steps: ordered,
    totals: { steps: ordered.length, flagged: flaggedCount, measuredMs: ordered.reduce((sum, s) => sum + (s.durationMs ?? 0), 0) },
  }
}

function countRing(ring: NonNullable<Payment['ring']>): Record<string, number> {
  const focus = ring.nodes.find((n) => n.focus)?.id
  if (!focus) return {}
  const out: Record<string, number> = {}
  for (const attr of ring.nodes.filter((n) => n.kind !== 'vendor')) {
    const linked = ring.edges.filter((e) => e.to === attr.id || e.from === attr.id).map((e) => (e.to === attr.id ? e.from : e.to))
    if (!linked.includes(focus)) continue
    const others = linked.filter((id) => id !== focus).length
    if (others > 0) out[attr.kind] = Math.max(out[attr.kind] ?? 0, others)
  }
  return out
}
