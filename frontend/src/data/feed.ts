import type { Payment, RunEvent } from '@/api/types'

export type FeedAgent = 'reader' | 'screener' | 'checker' | 'scorer' | 'policy' | 'writer' | 'intake' | 'settlement'
export type FeedLevel = 'info' | 'ok' | 'flag' | 'hold'

export interface FeedEvent {
  id: string
  at: number
  agent: FeedAgent
  step: string
  ref: string
  paymentId: string
  text: string
  level: FeedLevel
}

const EVENT_MAP: Record<string, { agent: FeedAgent; step: string; level?: FeedLevel }> = {
  run_started: { agent: 'reader', step: 'run started' },
  invoice_parsed: { agent: 'reader', step: 'read invoice' },
  sender_checked: { agent: 'checker', step: 'sender check' },
  vendor_resolved: { agent: 'screener', step: 'screen vendor' },
  kernel_checked: { agent: 'checker', step: 'kernel checks' },
  scored: { agent: 'scorer', step: 'score' },
  policy: { agent: 'policy', step: 'policy' },
  card_ready: { agent: 'writer', step: 'ready' },
  card_held: { agent: 'writer', step: 'ready', level: 'hold' },
  owner_approved: { agent: 'writer', step: 'approved', level: 'ok' },
  settled: { agent: 'settlement', step: 'settled', level: 'ok' },
  settlement_failed: { agent: 'settlement', step: 'failed', level: 'flag' },
  intake_received: { agent: 'intake', step: 'received' },
  run_completed: { agent: 'writer', step: 'run completed', level: 'ok' },
  run_failed: { agent: 'writer', step: 'run failed', level: 'flag' },
}

export function runEventToFeedEvent(ev: RunEvent, payments: Payment[]): FeedEvent | null {
  const mapping = EVENT_MAP[ev.type]
  if (!mapping) return null
  const payment = ev.cardId ? payments.find((p) => p.id === ev.cardId) : undefined
  const data = ev.data ?? {}
  let text = ev.type.replace(/_/g, ' ')
  let level: FeedLevel = mapping.level ?? 'info'
  if (ev.type === 'invoice_parsed') {
    text = payment ? `${payment.vendor.name} · $${payment.amount.toLocaleString('en-US')}` : 'invoice parsed'
  } else if (ev.type === 'sender_checked') {
    const flags = Array.isArray(data.flags) ? data.flags : []
    text = flags.length ? `sender: ${flags.length} flag(s)` : 'sender check passed'
    level = flags.length ? 'flag' : 'ok'
  } else if (ev.type === 'vendor_resolved') {
    text = `vendor: ${String(data.status ?? 'resolved')}`
    level = data.status === 'uncertain' || data.status === 'new' ? 'flag' : 'ok'
  } else if (ev.type === 'kernel_checked') {
    const flags = Array.isArray(data.flags) ? data.flags : []
    text = flags.length ? `checks: ${flags.length} flag(s)` : 'kernel checks clean'
    level = flags.length ? 'flag' : 'ok'
  } else if (ev.type === 'scored') {
    const legit = typeof data.legitimacy === 'number' ? Math.round(data.legitimacy * 100) : '?'
    text = `trust ${legit}% · ${String(data.top_class ?? 'scored')}`
    level = Number(legit) < 55 ? 'flag' : 'ok'
  } else if (ev.type === 'policy') {
    text = `lane: ${String(data.lane ?? 'policy').replace(/_/g, ' ')}`
    level = data.lane === 'hold' ? 'hold' : 'ok'
  } else if (ev.type === 'card_ready' || ev.type === 'card_held') {
    text = ev.type === 'card_held' ? 'VERIFY BEFORE RELEASE' : 'VOUCHED'
    level = ev.type === 'card_held' ? 'hold' : 'ok'
  } else if (ev.type === 'owner_approved') {
    text = 'approved by owner'
    level = 'ok'
  } else if (ev.type === 'settled') {
    text = `settled · tx ${String(data.tx_id ?? data.txId ?? '').slice(0, 8)}…`
    level = 'ok'
  } else if (ev.type === 'intake_received') {
    text = `intake: ${String(data.source ?? 'received')}`
    level = 'info'
  }
  return {
    id: `ev-${ev.seq}`,
    at: new Date(ev.at).getTime(),
    agent: mapping.agent,
    step: mapping.step,
    ref: payment?.invoiceNumber ?? String(data.invoice_number ?? data.card_id ?? ev.cardId ?? ''),
    paymentId: ev.cardId ?? '',
    text,
    level,
  }
}

const AGENT_STEPS: Array<{ agent: FeedAgent; step: string }> = [
  { agent: 'reader', step: 'read invoice' },
  { agent: 'screener', step: 'screen vendor' },
  { agent: 'checker', step: 'check 1 bank' },
  { agent: 'checker', step: 'check 2 dup/split' },
  { agent: 'checker', step: 'check 3 network' },
  { agent: 'scorer', step: 'score' },
  { agent: 'policy', step: 'policy' },
  { agent: 'writer', step: 'ready' },
]

function money(n: number) {
  return `$${n.toLocaleString('en-US')}`
}

/** Deterministic script of agent lines for one payment, derived from its evidence. */
export function scriptForPayment(p: Payment): Array<Omit<FeedEvent, 'id' | 'at'>> {
  const base = { ref: p.invoiceNumber, paymentId: p.id }
  const bank = p.risk === 'changed_bank'
  const dup = p.risk === 'duplicate_or_split'
  const ring = p.risk === 'unrecognized_vendor'
  const concerns = p.evidence.filter((e) => e.direction === 'concern')
  const top = concerns[0]?.label.toLowerCase()

  return [
    { ...base, agent: 'reader', step: 'read invoice', level: 'info', text: `${p.vendor.name} · ${money(p.amount)} · due ${p.dueDate.slice(5, 10)}` },
    {
      ...base,
      agent: 'screener',
      step: 'screen vendor',
      level: p.vendor.paymentsCompleted === 0 ? 'flag' : 'ok',
      text: p.vendor.paymentsCompleted === 0 ? `no history · vendor age ${ringOrNewAge(p)}d` : `${p.vendor.paymentsCompleted} prior payments · 0 disputes`,
    },
    { ...base, agent: 'checker', step: 'check 1 bank', level: bank ? 'flag' : 'ok', text: bank ? 'account changed 2d ago · requester unverified' : 'account matches file' },
    {
      ...base,
      agent: 'checker',
      step: 'check 2 dup/split',
      level: dup ? 'flag' : 'ok',
      text: dup ? (top ?? 'duplicate pattern') : 'no duplicate · no split pattern',
    },
    {
      ...base,
      agent: 'checker',
      step: 'check 3 network',
      level: ring ? 'flag' : 'ok',
      text: ring ? 'bank acct ···4471 shared by 3 vendors · phone shared by 2' : 'no shared bank, phone, or address',
    },
    { ...base, agent: 'scorer', step: 'score', level: p.trustScore < 55 ? 'flag' : 'ok', text: `trust ${p.trustScore}/100 · ${concerns.length} concern${concerns.length === 1 ? '' : 's'}` },
    { ...base, agent: 'policy', step: 'policy', level: 'ok', text: 'no fees · amount = invoice · owner approval required' },
    {
      ...base,
      agent: 'writer',
      step: 'ready',
      level: p.status === 'vouched' ? 'ok' : 'hold',
      text: p.status === 'vouched' ? 'VOUCHED' : p.status === 'verify' ? 'VERIFY BEFORE RELEASE' : 'QUICK CHECK',
    },
  ]
}

function ringOrNewAge(p: Payment) {
  const days = Math.round((Date.now() - new Date(p.vendor.since).getTime()) / 86_400_000)
  return Math.max(0, days)
}

export const FEED_AGENT_STEPS = AGENT_STEPS

/** Full interleaved script for all payments, round-robin by step so the feed looks concurrent. */
export function buildFeedScript(payments: Payment[]): Array<Omit<FeedEvent, 'id' | 'at'>> {
  const scripts = payments.map(scriptForPayment)
  const out: Array<Omit<FeedEvent, 'id' | 'at'>> = []
  const maxLen = Math.max(0, ...scripts.map((s) => s.length))
  for (let step = 0; step < maxLen; step++) {
    for (const s of scripts) {
      const line = s[step]
      if (line) out.push(line)
    }
  }
  return out
}
