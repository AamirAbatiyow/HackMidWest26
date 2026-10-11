import type {
  AuditNote,
  ChecklistItem,
  CountryCode,
  EvidenceFactor,
  HighlightSeverity,
  InvoiceHighlight,
  LatencyStats,
  Lifecycle,
  LimeFactor,
  ModelExplanation,
  NetworkStatus,
  Payment,
  RedTeamReport,
  RingGraph,
  RiskType,
  SettlementReceipt,
  TimelineEvent,
  TopologyData,
  TrustData,
  VouchApi,
  VouchStatus,
} from './types'
import { limeLabel } from '@/lib/lime'

export class ApiError extends Error {
  readonly status?: number

  constructor(message: string, status?: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

type Json = Record<string, unknown>

const asRecord = (v: unknown): Json => (v && typeof v === 'object' ? (v as Json) : {})
const str = (v: unknown, fallback = ''): string => (typeof v === 'string' ? v : v == null ? fallback : String(v))
const num = (v: unknown, fallback = 0): number => {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : fallback
}
const pick = (o: Json, ...keys: string[]): unknown => {
  for (const k of keys) if (o[k] !== undefined) return o[k]
  return undefined
}

function normalizeStatus(v: unknown): VouchStatus {
  const s = str(v).toLowerCase().replace(/[\s-]/g, '_')
  if (['vouched', 'safe', 'approved', 'ok', 'pass', 'clear'].includes(s)) return 'vouched'
  if (['verify', 'verify_before_release', 'high', 'block', 'hold', 'review'].includes(s)) return 'verify'
  if (['quick_check', 'check', 'medium', 'warn', 'flag', 'flagged'].includes(s)) return 'quick_check'
  return 'quick_check'
}

function normalizeRisk(v: unknown): RiskType {
  const s = str(v).toLowerCase().replace(/[\s-]/g, '_')
  if (!s || s === 'none' || s === 'null') return 'none'
  if (s.includes('bank')) return 'changed_bank'
  if (s.includes('dup') || s.includes('split')) return 'duplicate_or_split'
  if (s.includes('vendor') || s.includes('ring') || s.includes('unknown') || s.includes('new')) return 'unrecognized_vendor'
  return 'none'
}

function normalizeLifecycle(v: unknown): Lifecycle {
  const s = str(v).toLowerCase()
  if (['approved', 'held', 'appealed', 'settled', 'pending'].includes(s)) return s as Lifecycle
  if (s === 'paid' || s === 'complete') return 'settled'
  return 'pending'
}

function normalizeCountry(v: unknown): CountryCode {
  const s = str(v).toUpperCase()
  if (s === 'MX' || s.startsWith('MEX')) return 'MX'
  if (s === 'PL' || s.startsWith('POL')) return 'PL'
  if (s === 'BR' || s.startsWith('BRA')) return 'BR'
  return 'US'
}

function normalizeEvidence(v: unknown): EvidenceFactor[] {
  if (!Array.isArray(v)) return []
  return v.map((raw, i) => {
    const e = asRecord(raw)
    const weight = num(pick(e, 'weight', 'contribution', 'value'), 0)
    const dir = str(pick(e, 'direction', 'kind'))
    const direction: EvidenceFactor['direction'] =
      dir === 'concern' || dir === 'reassuring' ? dir : weight < 0 ? 'reassuring' : 'concern'
    return {
      id: str(pick(e, 'id'), `e-${i}`),
      label: str(pick(e, 'label', 'feature', 'text', 'reason'), 'Factor'),
      weight: Math.min(1, Math.abs(weight)),
      direction,
    }
  })
}

/**
 * `lime` rows are `{feature, label, rule, weight, value}` toward `lime_class`. When the explained
 * class is legitimacy a positive weight is reassuring; for a risk head it is a concern.
 */
export function normalizeModel(p: Json): ModelExplanation | undefined {
  const rows = pick(p, 'lime')
  const limeClass = pick(p, 'lime_class', 'limeClass')
  const scorer = pick(p, 'scorer')
  if (!Array.isArray(rows) && limeClass == null && scorer == null) return undefined
  const targetClass = limeClass == null ? null : str(limeClass)
  const towardLegit = targetClass === 'legitimacy' || targetClass === 'honest'
  const factors: LimeFactor[] = (Array.isArray(rows) ? rows : []).map((raw, i) => {
    const r = asRecord(raw)
    const weight = num(pick(r, 'weight', 'contribution'), 0)
    const valueRaw = pick(r, 'value')
    const value = valueRaw == null ? null : num(valueRaw, 0)
    const feature = str(pick(r, 'feature', 'name'), `f${i}`)
    const rawLabel = str(pick(r, 'label'), feature)
    const concern = towardLegit ? weight < 0 : weight > 0
    return {
      id: str(pick(r, 'id'), `l-${i}`),
      feature,
      label: limeLabel(feature, value, rawLabel),
      rawLabel,
      weight,
      value,
      direction: concern ? 'concern' : 'reassuring',
    }
  })
  return {
    factors,
    targetClass,
    scorer: scorer == null ? null : str(scorer),
    modelVersion: pick(p, 'model_version', 'modelVersion') == null ? null : str(pick(p, 'model_version', 'modelVersion')),
  }
}

export function normalizeHighlights(v: unknown): InvoiceHighlight[] | undefined {
  if (!Array.isArray(v)) return undefined
  return v.map((raw) => {
    const h = asRecord(raw)
    const sev = str(pick(h, 'severity'), 'ok').toLowerCase()
    const severity: HighlightSeverity = sev === 'high' || sev === 'red' || sev === 'danger' ? 'high' : sev === 'warn' || sev === 'warning' || sev === 'amber' ? 'warn' : 'ok'
    const reasonsRaw = pick(h, 'reasons')
    const reason = pick(h, 'reason')
    const reasons = Array.isArray(reasonsRaw) ? reasonsRaw.map((r) => str(r)).filter(Boolean) : reason ? [str(reason)] : []
    const field = str(pick(h, 'field', 'key'), 'field')
    return {
      field,
      label: str(pick(h, 'label'), field.replace(/_/g, ' ')),
      value: str(pick(h, 'value'), '—'),
      severity,
      reasons,
    }
  })
}

function normalizeTimeline(v: unknown): TimelineEvent[] {
  if (!Array.isArray(v)) return []
  return v.map((raw, i) => {
    const t = asRecord(raw)
    const kind = str(pick(t, 'kind', 'type'), 'note')
    return {
      id: str(pick(t, 'id'), `t-${i}`),
      date: str(pick(t, 'date', 'at', 'timestamp'), new Date().toISOString()),
      title: str(pick(t, 'title', 'event', 'text'), 'Event'),
      detail: pick(t, 'detail', 'description') ? str(pick(t, 'detail', 'description')) : undefined,
      kind: (['payment', 'change', 'onboard', 'check', 'note'] as const).includes(
        kind as TimelineEvent['kind'],
      )
        ? (kind as TimelineEvent['kind'])
        : 'note',
    }
  })
}

function normalizeChecklist(v: unknown): ChecklistItem[] {
  if (!Array.isArray(v)) return []
  return v.map((raw, i) => {
    if (typeof raw === 'string') return { id: `c-${i}`, text: raw, done: false }
    const c = asRecord(raw)
    return { id: str(pick(c, 'id'), `c-${i}`), text: str(pick(c, 'text', 'label')), done: Boolean(pick(c, 'done')) }
  })
}

function normalizeRing(v: unknown): RingGraph | undefined {
  const g = asRecord(v)
  if (!Array.isArray(g.nodes) || g.nodes.length === 0) return undefined
  return {
    nodes: g.nodes.map((raw, i) => {
      const n = asRecord(raw)
      const kind = str(pick(n, 'kind', 'type'), 'vendor')
      return {
        id: str(pick(n, 'id'), `n-${i}`),
        label: str(pick(n, 'label', 'name'), 'Node'),
        kind: (['vendor', 'bank', 'phone', 'address'] as const).includes(kind as never) ? (kind as never) : 'vendor',
        focus: Boolean(pick(n, 'focus')),
      }
    }),
    edges: Array.isArray(g.edges)
      ? g.edges.map((raw) => {
          const e = asRecord(raw)
          return { from: str(pick(e, 'from', 'source')), to: str(pick(e, 'to', 'target')) }
        })
      : [],
  }
}

function normalizeNotes(v: unknown): AuditNote[] {
  if (!Array.isArray(v)) return []
  return v.map((raw, i) => {
    const n = asRecord(raw)
    return {
      id: str(pick(n, 'id'), `n-${i}`),
      at: str(pick(n, 'at', 'created_at', 'timestamp'), new Date().toISOString()),
      text: str(pick(n, 'text', 'note')),
      author: str(pick(n, 'author', 'by'), 'Owner'),
    }
  })
}

export function normalizePayment(raw: unknown): Payment {
  const p = asRecord(raw)
  const vendorRaw = asRecord(pick(p, 'vendor'))
  const vendorName = str(pick(vendorRaw, 'name') ?? pick(p, 'vendor_name', 'vendorName'), 'Vendor')
  const amountRaw = pick(p, 'amount', 'amount_usd', 'total')
  const amountCents = pick(p, 'amount_cents', 'amountCents')
  const amount = amountCents !== undefined ? num(amountCents) / 100 : num(amountRaw)
  const trustRaw = num(pick(p, 'trust_score', 'trustScore', 'trust'), 50)
  return {
    id: str(pick(p, 'id', 'payment_id')),
    vendor: {
      id: str(pick(vendorRaw, 'id') ?? pick(p, 'vendor_id'), vendorName),
      name: vendorName,
      city: str(pick(vendorRaw, 'city') ?? pick(p, 'vendor_city')),
      country: normalizeCountry(pick(vendorRaw, 'country', 'country_code') ?? pick(p, 'country')),
      since: str(pick(vendorRaw, 'since', 'first_payment_at') ?? pick(p, 'vendor_since'), new Date().toISOString()),
      paymentsCompleted: num(pick(vendorRaw, 'payments_completed', 'paymentsCompleted', 'history_count')),
    },
    invoiceNumber: str(pick(p, 'invoice_number', 'invoiceNumber', 'invoice'), '—'),
    amount,
    currency: 'USD',
    dueDate: str(pick(p, 'due_date', 'dueDate', 'due'), new Date().toISOString()),
    status: normalizeStatus(pick(p, 'status', 'decision', 'verdict')),
    lifecycle: normalizeLifecycle(pick(p, 'lifecycle', 'state')),
    risk: normalizeRisk(pick(p, 'risk', 'risk_type', 'riskType', 'flag')),
    trustScore: Math.round(trustRaw <= 1 ? trustRaw * 100 : trustRaw),
    reason: str(pick(p, 'reason', 'explanation', 'summary'), ''),
    fastPayEligible: Boolean(pick(p, 'fast_pay_eligible', 'fastPayEligible', 'fast_pay')),
    source: str(pick(p, 'source', 'channel')).toLowerCase() === 'upload' ? 'upload' : 'email',
    receivedAt: str(pick(p, 'received_at', 'receivedAt', 'created_at', 'createdAt'), new Date().toISOString()),
    relation: normalizeRelation(p),
    evidence: normalizeEvidence(pick(p, 'evidence', 'factors', 'explanations')),
    timeline: normalizeTimeline(pick(p, 'timeline', 'history')),
    checklist: normalizeChecklist(pick(p, 'checklist', 'callback_checklist')),
    ring: normalizeRing(pick(p, 'ring', 'network', 'graph')),
    auditNotes: normalizeNotes(pick(p, 'audit_notes', 'auditNotes', 'notes')),
    model: normalizeModel(p),
    highlights: normalizeHighlights(pick(p, 'highlights', 'invoice_highlights')),
  }
}

function normalizeReceipt(raw: unknown, fallbackIds: string[]): SettlementReceipt {
  const r = asRecord(raw)
  const txId = str(pick(r, 'tx_id', 'txId', 'transaction_id', 'hash'), '')
  const adapter = str(pick(r, 'adapter', 'settlement_adapter'), '')
  const linesRaw = pick(r, 'lines', 'payments', 'items')
  const lines = Array.isArray(linesRaw)
    ? linesRaw.map((l, i) => {
        const x = asRecord(l)
        return {
          paymentId: str(pick(x, 'payment_id', 'paymentId', 'id'), fallbackIds[i] ?? `line-${i}`),
          vendorName: str(pick(x, 'vendor_name', 'vendorName', 'vendor'), 'Vendor'),
          invoiceNumber: str(pick(x, 'invoice_number', 'invoiceNumber'), '—'),
          amount: num(pick(x, 'amount')),
        }
      })
    : []
  const funding = str(pick(r, 'funding'), 'now') === 'scheduled' ? 'scheduled' : 'now'
  const explorerUrlRaw = str(pick(r, 'explorer_url', 'explorerUrl'), '')
  const explorerUrl = explorerUrlRaw
    ? explorerUrlRaw
    : adapter === 'xrpl' && txId
      ? `https://testnet.xrpl.org/transactions/${txId}`
      : txId
        ? `https://basescan.org/tx/${txId}`
        : '#'
  return {
    batchId: str(pick(r, 'batch_id', 'batchId', 'id'), `batch-${Date.now()}`),
    txId,
    explorerUrl,
    settledAt: str(pick(r, 'settled_at', 'settledAt'), new Date().toISOString()),
    funding,
    scheduledFor: pick(r, 'scheduled_for', 'scheduledFor') ? str(pick(r, 'scheduled_for', 'scheduledFor')) : undefined,
    totalAmount: num(pick(r, 'total_amount', 'totalAmount', 'total'), lines.reduce((s, l) => s + l.amount, 0)),
    lines,
    network: str(pick(r, 'network', 'chain'), 'USDC'),
    feeUsd: num(pick(r, 'fee_usd', 'feeUsd', 'fee'), 0),
  }
}

function normalizeRelation(p: Json): Payment['relation'] {
  const rel = asRecord(pick(p, 'relation'))
  const dup = pick(p, 'duplicate_of', 'duplicateOf') ?? (str(pick(rel, 'kind')) === 'duplicate_of' ? pick(rel, 'payment_id', 'paymentId') : undefined)
  if (dup) return { kind: 'duplicate_of', paymentId: str(dup) }
  const split = pick(p, 'split_with', 'splitWith') ?? (str(pick(rel, 'kind')) === 'split_with' ? pick(rel, 'payment_id', 'paymentId') : undefined)
  if (split) return { kind: 'split_with', paymentId: str(split) }
  return undefined
}

function normalizeNetwork(raw: unknown): NetworkStatus {
  const n = asRecord(raw)
  const hopsRaw = pick(n, 'hops', 'links')
  const tokens = asRecord(pick(n, 'tokens', 'token_usage'))
  const policy = asRecord(pick(n, 'policy_checks', 'policyChecks', 'policy'))
  const latency = asRecord(pick(n, 'latency'))
  const p50Raw = pick(n, 'p50_ms', 'p50Ms', 'latency_p50_ms') ?? pick(latency, 'p50_ms', 'p50Ms', 'p50')
  const p95Raw = pick(n, 'p95_ms', 'p95Ms', 'latency_p95_ms') ?? pick(latency, 'p95_ms', 'p95Ms', 'p95')
  const tokensToday = pick(n, 'tokens_today', 'tokensToday')
  return {
    p50Ms: p50Raw == null ? null : num(p50Raw),
    p95Ms: p95Raw == null ? null : num(p95Raw),
    hops: Array.isArray(hopsRaw)
      ? hopsRaw.map((h, i) => {
          const x = asRecord(h)
          return {
            id: str(pick(x, 'id'), `h-${i}`),
            from: str(pick(x, 'from', 'source')),
            to: str(pick(x, 'to', 'target')),
            p50Ms: num(pick(x, 'p50_ms', 'p50Ms', 'p50')),
            p95Ms: num(pick(x, 'p95_ms', 'p95Ms', 'p95')),
            isPrivate: Boolean(pick(x, 'private', 'is_private', 'isPrivate')),
          }
        })
      : [],
    modelVersion: str(pick(n, 'model_version', 'modelVersion', 'model'), 'unknown'),
    tokens: {
      promptToday: num(pick(tokens, 'prompt_today', 'promptToday', 'prompt'), tokensToday == null ? 0 : num(tokensToday)),
      completionToday: num(pick(tokens, 'completion_today', 'completionToday', 'completion')),
      perPaymentAvg: num(pick(tokens, 'per_payment_avg', 'perPaymentAvg', 'avg')),
    },
    policyChecks: {
      passed: num(pick(policy, 'passed')),
      total: num(pick(policy, 'total'), num(pick(policy, 'passed'))),
    },
    region: str(pick(n, 'region'), '—'),
    updatedAt: str(pick(n, 'updated_at', 'updatedAt'), new Date().toISOString()),
  }
}

function normalizeRedTeam(raw: unknown): RedTeamReport {
  const r = Array.isArray(raw) ? { cases: raw } : asRecord(raw)
  const casesRaw = pick(r, 'cases', 'results', 'prompts')
  return {
    modelVersion: str(pick(r, 'model_version', 'modelVersion'), '—'),
    runAt: str(pick(r, 'run_at', 'runAt'), new Date().toISOString()),
    cases: Array.isArray(casesRaw)
      ? casesRaw.map((c, i) => {
          const x = asRecord(c)
          return {
            id: num(pick(x, 'id'), i + 1),
            prompt: str(pick(x, 'prompt', 'input', 'text')),
            category: str(pick(x, 'category', 'type'), 'Adversarial'),
            blocked: pick(x, 'blocked') === undefined ? str(pick(x, 'result')).toLowerCase() === 'blocked' : Boolean(pick(x, 'blocked')),
            rule: str(pick(x, 'rule', 'policy_rule', 'policy'), '—'),
          }
        })
      : [],
  }
}

function normalizeLatency(raw: Json): LatencyStats {
  const pipelineStepsRaw = asRecord(pick(raw, 'pipeline_steps', 'pipelineSteps'))
  const pipelineSteps: Record<string, { p50Ms: number | null; p95Ms: number | null; count: number; latestMs: number | null }> = {}
  for (const [key, val] of Object.entries(pipelineStepsRaw)) {
    const step = asRecord(val)
    pipelineSteps[key] = {
      p50Ms: pick(step, 'p50_ms', 'p50Ms') != null ? num(pick(step, 'p50_ms', 'p50Ms')) : null,
      p95Ms: pick(step, 'p95_ms', 'p95Ms') != null ? num(pick(step, 'p95_ms', 'p95Ms')) : null,
      count: num(pick(step, 'count'), 0),
      latestMs: pick(step, 'latest_ms', 'latestMs') != null ? num(pick(step, 'latest_ms', 'latestMs')) : null,
    }
  }

  const inferenceRaw = asRecord(pick(raw, 'inference'))
  const inference: Record<string, { model: string; baseUrl: string; live: boolean; p50Ms: number | null; p95Ms: number | null; count: number; latestMs: number | null }> = {}
  for (const [key, val] of Object.entries(inferenceRaw)) {
    const ep = asRecord(val)
    inference[key] = {
      model: str(pick(ep, 'model')),
      baseUrl: str(pick(ep, 'base_url', 'baseUrl')),
      live: Boolean(pick(ep, 'live')),
      p50Ms: pick(ep, 'p50_ms', 'p50Ms') != null ? num(pick(ep, 'p50_ms', 'p50Ms')) : null,
      p95Ms: pick(ep, 'p95_ms', 'p95Ms') != null ? num(pick(ep, 'p95_ms', 'p95Ms')) : null,
      count: num(pick(ep, 'count'), 0),
      latestMs: pick(ep, 'latest_ms', 'latestMs') != null ? num(pick(ep, 'latest_ms', 'latestMs')) : null,
    }
  }

  const deciderRaw = asRecord(pick(raw, 'decider'))
  const decider = {
    engine: str(pick(deciderRaw, 'engine')),
    enginesAvailable: Array.isArray(pick(deciderRaw, 'engines_available', 'enginesAvailable'))
      ? (pick(deciderRaw, 'engines_available', 'enginesAvailable') as string[])
      : [],
    p50Ms: pick(deciderRaw, 'p50_ms', 'p50Ms') != null ? num(pick(deciderRaw, 'p50_ms', 'p50Ms')) : null,
    p95Ms: pick(deciderRaw, 'p95_ms', 'p95Ms') != null ? num(pick(deciderRaw, 'p95_ms', 'p95Ms')) : null,
    count: num(pick(deciderRaw, 'count'), 0),
    latestMs: pick(deciderRaw, 'latest_ms', 'latestMs') != null ? num(pick(deciderRaw, 'latest_ms', 'latestMs')) : null,
  }

  const postgresRaw = asRecord(pick(raw, 'postgres'))
  const postgres = {
    configured: Boolean(pick(postgresRaw, 'configured')),
    ok: pick(postgresRaw, 'ok') != null ? Boolean(pick(postgresRaw, 'ok')) : null,
    latencyMs: pick(postgresRaw, 'latency_ms', 'latencyMs') != null ? num(pick(postgresRaw, 'latency_ms', 'latencyMs')) : null,
    p50Ms: pick(postgresRaw, 'p50_ms', 'p50Ms') != null ? num(pick(postgresRaw, 'p50_ms', 'p50Ms')) : null,
    p95Ms: pick(postgresRaw, 'p95_ms', 'p95Ms') != null ? num(pick(postgresRaw, 'p95_ms', 'p95Ms')) : null,
  }

  const objRaw = asRecord(pick(raw, 'object_storage', 'objectStorage'))
  const objectStorage = {
    configured: Boolean(pick(objRaw, 'configured')),
    ok: pick(objRaw, 'ok') != null ? Boolean(pick(objRaw, 'ok')) : null,
    latencyMs: pick(objRaw, 'latency_ms', 'latencyMs') != null ? num(pick(objRaw, 'latency_ms', 'latencyMs')) : null,
    p50Ms: pick(objRaw, 'p50_ms', 'p50Ms') != null ? num(pick(objRaw, 'p50_ms', 'p50Ms')) : null,
    p95Ms: pick(objRaw, 'p95_ms', 'p95Ms') != null ? num(pick(objRaw, 'p95_ms', 'p95Ms')) : null,
  }

  const tiersRaw = asRecord(pick(raw, 'tiers'))
  const tiers: Record<string, { name: string; subnet: string; products: string[]; description: string; configured: boolean; healthy: boolean | null; rttMs: number | null }> = {}
  for (const [key, val] of Object.entries(tiersRaw)) {
    const t = asRecord(val)
    tiers[key] = {
      name: str(pick(t, 'name')),
      subnet: str(pick(t, 'subnet')),
      products: Array.isArray(pick(t, 'products')) ? (pick(t, 'products') as string[]) : [],
      description: str(pick(t, 'description')),
      configured: Boolean(pick(t, 'configured')),
      healthy: pick(t, 'healthy') != null ? Boolean(pick(t, 'healthy')) : null,
      rttMs: pick(t, 'rtt_ms', 'rttMs') != null ? num(pick(t, 'rtt_ms', 'rttMs')) : null,
    }
  }

  const waterfallRaw = asRecord(pick(raw, 'last_run_waterfall', 'lastRunWaterfall'))
  const lastRunWaterfall = waterfallRaw && pick(waterfallRaw, 'run_id', 'runId')
    ? {
        runId: str(pick(waterfallRaw, 'run_id', 'runId')),
        steps: Array.isArray(pick(waterfallRaw, 'steps'))
          ? (pick(waterfallRaw, 'steps') as unknown[]).map((s) => {
              const step = asRecord(s)
              return {
                step: str(pick(step, 'step')),
                latencyMs: pick(step, 'latency_ms', 'latencyMs') != null ? num(pick(step, 'latency_ms', 'latencyMs')) : null,
              }
            })
          : [],
      }
    : null

  return {
    updatedAt: str(pick(raw, 'updated_at', 'updatedAt'), new Date().toISOString()),
    region: str(pick(raw, 'region')),
    pipelineSteps,
    inference,
    decider,
    postgres,
    objectStorage,
    tiers,
    lastRunWaterfall,
  }
}

function normalizeTopology(raw: Json): TopologyData {
  const vpcRaw = asRecord(pick(raw, 'vpc'))
  const firewallRaw = asRecord(pick(raw, 'firewall'))
  const nodebalancerRaw = asRecord(pick(raw, 'nodebalancer'))

  const rulesRaw = pick(firewallRaw, 'rules')
  const rules = Array.isArray(rulesRaw)
    ? rulesRaw.map((r) => {
        const rule = asRecord(r)
        return {
          id: str(pick(rule, 'id')),
          direction: str(pick(rule, 'direction')),
          protocol: str(pick(rule, 'protocol')),
          ports: str(pick(rule, 'ports')),
          source: pick(rule, 'source') ? str(pick(rule, 'source')) : undefined,
          destination: pick(rule, 'destination') ? str(pick(rule, 'destination')) : undefined,
          action: str(pick(rule, 'action')),
          label: str(pick(rule, 'label')),
        }
      })
    : []

  const tiersRaw = asRecord(pick(raw, 'tiers'))
  const tiers: Record<string, { name: string; subnet: string; products: string[]; description: string }> = {}
  for (const [key, val] of Object.entries(tiersRaw)) {
    const t = asRecord(val)
    tiers[key] = {
      name: str(pick(t, 'name')),
      subnet: str(pick(t, 'subnet')),
      products: Array.isArray(pick(t, 'products')) ? (pick(t, 'products') as string[]) : [],
      description: str(pick(t, 'description')),
    }
  }

  const nodesRaw = pick(raw, 'nodes')
  const nodes = Array.isArray(nodesRaw)
    ? nodesRaw.map((n) => {
        const node = asRecord(n)
        return {
          id: str(pick(node, 'id')),
          label: str(pick(node, 'label')),
          tier: pick(node, 'tier') ? str(pick(node, 'tier')) : null,
          product: pick(node, 'product') ? str(pick(node, 'product')) : null,
          x: num(pick(node, 'x')),
          y: num(pick(node, 'y')),
          configured: pick(node, 'configured') != null ? Boolean(pick(node, 'configured')) : undefined,
        }
      })
    : []

  const edgesRaw = pick(raw, 'edges')
  const edges = Array.isArray(edgesRaw)
    ? edgesRaw.map((e) => {
        const edge = asRecord(e)
        return {
          id: str(pick(edge, 'id')),
          from: str(pick(edge, 'from')),
          to: str(pick(edge, 'to')),
          label: str(pick(edge, 'label')),
          private: Boolean(pick(edge, 'private')),
        }
      })
    : []

  return {
    updatedAt: str(pick(raw, 'updated_at', 'updatedAt'), new Date().toISOString()),
    region: str(pick(raw, 'region')),
    vpc: {
      label: str(pick(vpcRaw, 'label')),
      configured: Boolean(pick(vpcRaw, 'configured')),
    },
    firewall: {
      label: str(pick(firewallRaw, 'label')),
      configured: Boolean(pick(firewallRaw, 'configured')),
      rules,
    },
    nodebalancer: {
      configured: Boolean(pick(nodebalancerRaw, 'configured')),
    },
    tiers,
    nodes,
    edges,
  }
}

export interface LiveApiOptions {
  baseUrl: string
  fetchImpl?: typeof fetch
}

export function createLiveApi({ baseUrl, fetchImpl = fetch }: LiveApiOptions): VouchApi {
  const base = baseUrl.replace(/\/$/, '')

  /** Try /v1/<path> first; fall back to the unversioned path when the server does not know it. */
  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    try {
      return await requestAt<T>(`/v1${path}`, init)
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) return requestAt<T>(path, init)
      throw err
    }
  }

  async function requestAt<T>(path: string, init?: RequestInit): Promise<T> {
    let res: Response
    try {
      res = await fetchImpl(`${base}${path}`, {
        headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...(init?.headers ?? {}) },
        ...init,
      })
    } catch (err) {
      throw new ApiError(`Could not reach the Vouch API at ${base}. ${err instanceof Error ? err.message : ''}`.trim())
    }
    if (!res.ok) {
      let detail = ''
      try {
        const body = (await res.json()) as Json
        detail = str(body.detail ?? body.message)
      } catch {
        /* no body */
      }
      throw new ApiError(detail || `${res.status} ${res.statusText}`, res.status)
    }
    if (res.status === 204) return undefined as T
    return (await res.json()) as T
  }

  const unwrapList = (raw: unknown): unknown[] => {
    if (Array.isArray(raw)) return raw
    const r = asRecord(raw)
    const inner = pick(r, 'payments', 'items', 'data', 'results')
    return Array.isArray(inner) ? inner : []
  }

  return {
    mode: 'live',

    async listPayments() {
      const raw = await request<unknown>('/payments')
      return unwrapList(raw).map(normalizePayment)
    },

    async getPayment(id) {
      return normalizePayment(await request<unknown>(`/payments/${encodeURIComponent(id)}`))
    },

    async approvePayment(id, note) {
      return normalizePayment(
        await request<unknown>(`/payments/${encodeURIComponent(id)}/approve`, {
          method: 'POST',
          body: JSON.stringify({ note: note ?? '' }),
        }),
      )
    },

    async holdPayment(id, note) {
      return normalizePayment(
        await request<unknown>(`/payments/${encodeURIComponent(id)}/hold`, {
          method: 'POST',
          body: JSON.stringify({ note: note ?? '' }),
        }),
      )
    },

    async appealPayment(id, note) {
      return normalizePayment(
        await request<unknown>(`/payments/${encodeURIComponent(id)}/appeal`, {
          method: 'POST',
          body: JSON.stringify({ note: note ?? '' }),
        }),
      )
    },

    async settleBatch(paymentIds, funding) {
      const raw = await request<unknown>('/batch/settle', {
        method: 'POST',
        body: JSON.stringify({ payment_ids: paymentIds, funding }),
      })
      return normalizeReceipt(raw, paymentIds)
    },

    async getNetwork() {
      return normalizeNetwork(await request<unknown>('/netz'))
    },

    async getRedTeam() {
      return normalizeRedTeam(await request<unknown>('/redteam'))
    },

    async getHealth() {
      const started = performance.now()
      try {
        const raw = asRecord(await request<unknown>('/health'))
        return {
          ok: true,
          version: str(pick(raw, 'version', 'model_version'), undefined as never) || undefined,
          latencyMs: Math.round(performance.now() - started),
        }
      } catch (err) {
        return { ok: false, latencyMs: Math.round(performance.now() - started), reason: err instanceof Error ? err.message : 'unreachable' }
      }
    },

    async getInfo() {
      const raw = asRecord(await request<unknown>('/info'))
      const model = pick(raw, 'model', 'active_model', 'activeModel', 'model_version', 'modelVersion')
      const policy = pick(raw, 'policy_mode', 'policyMode', 'policy')
      return {
        model: model == null ? null : str(model),
        policyMode: policy == null ? null : str(policy),
        version: str(pick(raw, 'version'), undefined as never) || undefined,
        settlementAdapter: str(pick(raw, 'settlement_adapter', 'settlementAdapter'), undefined as never) || undefined,
        settlementNetwork: str(pick(raw, 'settlement_network', 'settlementNetwork'), undefined as never) || undefined,
        llmMode: str(pick(raw, 'llm_mode', 'llmMode'), undefined as never) || undefined,
        scorer: str(pick(raw, 'scorer'), undefined as never) || undefined,
        runs: num(pick(raw, 'runs'), undefined as never) || undefined,
        vendors: num(pick(raw, 'vendors'), undefined as never) || undefined,
      }
    },

    async getLatency(): Promise<LatencyStats> {
      const raw = asRecord(await request<unknown>('/latency'))
      return normalizeLatency(raw)
    },

    async getTopology(): Promise<TopologyData> {
      const raw = asRecord(await request<unknown>('/topology'))
      return normalizeTopology(raw)
    },

    async getTrust(): Promise<TrustData> {
      return await request<TrustData>('/trust')
    },

    async listRuns() {
      const raw = await request<unknown>('/runs')
      const list = Array.isArray(raw) ? raw : []
      return list.map((item) => {
        const r = asRecord(item)
        const cardIds = Array.isArray(pick(r, 'cards')) ? (pick(r, 'cards') as unknown[]).map((c) => str(asRecord(c).id)) : []
        return {
          id: str(pick(r, 'id')),
          label: str(pick(r, 'label')),
          status: str(pick(r, 'status'), 'completed') as 'running' | 'awaiting_approval' | 'completed' | 'failed',
          createdAt: str(pick(r, 'created_at', 'createdAt')),
          pendingApproval: Boolean(pick(r, 'pending_approval', 'pendingApproval', 'pending')),
          cardIds,
        }
      })
    },

    async getRunEvents(runId, after = 0) {
      const raw = asRecord(await request<unknown>(`/runs/${encodeURIComponent(runId)}/events?after=${after}`))
      const events = Array.isArray(raw.events)
        ? (raw.events as unknown[]).map((e) => {
            const ev = asRecord(e)
            return {
              seq: num(pick(ev, 'seq')),
              type: str(pick(ev, 'type')),
              at: str(pick(ev, 'at', 'timestamp')),
              cardId: str(pick(ev, 'card_id', 'cardId'), undefined as never) || undefined,
              data: ev,
            }
          })
        : []
      return { status: str(raw.status, 'unknown'), events }
    },
  }
}
