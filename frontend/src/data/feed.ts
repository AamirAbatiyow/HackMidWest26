import type { Payment } from '@/api/types'

export type FeedAgent = 'reader' | 'screener' | 'checker' | 'scorer' | 'policy' | 'writer'
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
