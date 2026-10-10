import type {
  AuditNote,
  ChecklistItem,
  CountryCode,
  EvidenceFactor,
  FairnessReport,
  Lifecycle,
  NetworkStatus,
  Payment,
  RedTeamReport,
  RingGraph,
  RiskType,
  SettlementReceipt,
  TimelineEvent,
  VouchApi,
  VouchStatus,
} from './types'
import { DEMO_FAIRNESS } from '@/data/fairness'

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
    evidence: normalizeEvidence(pick(p, 'evidence', 'factors', 'explanations')),
    timeline: normalizeTimeline(pick(p, 'timeline', 'history')),
    checklist: normalizeChecklist(pick(p, 'checklist', 'callback_checklist')),
    ring: normalizeRing(pick(p, 'ring', 'network', 'graph')),
    auditNotes: normalizeNotes(pick(p, 'audit_notes', 'auditNotes', 'notes')),
  }
}

function normalizeReceipt(raw: unknown, fallbackIds: string[]): SettlementReceipt {
  const r = asRecord(raw)
  const txId = str(pick(r, 'tx_id', 'txId', 'transaction_id', 'hash'), '')
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
  return {
    batchId: str(pick(r, 'batch_id', 'batchId', 'id'), `batch-${Date.now()}`),
    txId,
    explorerUrl: str(pick(r, 'explorer_url', 'explorerUrl'), txId ? `https://basescan.org/tx/${txId}` : '#'),
    settledAt: str(pick(r, 'settled_at', 'settledAt'), new Date().toISOString()),
    funding,
    scheduledFor: pick(r, 'scheduled_for', 'scheduledFor') ? str(pick(r, 'scheduled_for', 'scheduledFor')) : undefined,
    totalAmount: num(pick(r, 'total_amount', 'totalAmount', 'total'), lines.reduce((s, l) => s + l.amount, 0)),
    lines,
    network: str(pick(r, 'network', 'chain'), 'USDC'),
    feeUsd: num(pick(r, 'fee_usd', 'feeUsd', 'fee'), 0),
  }
}

function normalizeNetwork(raw: unknown): NetworkStatus {
  const n = asRecord(raw)
  const hopsRaw = pick(n, 'hops', 'links')
  const tokens = asRecord(pick(n, 'tokens', 'token_usage'))
  const policy = asRecord(pick(n, 'policy_checks', 'policyChecks', 'policy'))
  return {
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
      promptToday: num(pick(tokens, 'prompt_today', 'promptToday', 'prompt')),
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

export interface LiveApiOptions {
  baseUrl: string
  fetchImpl?: typeof fetch
}

export function createLiveApi({ baseUrl, fetchImpl = fetch }: LiveApiOptions): VouchApi {
  const base = baseUrl.replace(/\/$/, '')

  async function request<T>(path: string, init?: RequestInit): Promise<T> {
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

    async getFairness() {
      try {
        const raw = asRecord(await request<unknown>('/fairness'))
        if (Object.keys(raw).length === 0) return DEMO_FAIRNESS
        return { ...DEMO_FAIRNESS, ...(raw as Partial<FairnessReport>) }
      } catch (err) {
        // The backend may not expose a fairness endpoint yet; fall back to the reference report.
        if (err instanceof ApiError && err.status === 404) return DEMO_FAIRNESS
        throw err
      }
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
      } catch {
        return { ok: false, latencyMs: Math.round(performance.now() - started) }
      }
    },
  }
}
