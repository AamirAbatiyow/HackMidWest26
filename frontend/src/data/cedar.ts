import type { CedarRule } from '@/api/types'

/**
 * Plain-English copy for the Trust page's Cedar block. Rule ids, principals and Cedar action
 * names come from `/v1/trust` (parsed from `policies/vouch.cedar`); this file only adds the
 * owner-facing wording and the agent's ALLOW / DENY matrix derived from those rules.
 */

export interface RuleCopy {
  /** What the rule says, for a business owner. */
  plain: string
  /** The attack or mistake the rule stops. */
  protects: string
}

export const RULE_COPY: Record<string, RuleCopy> = {
  'P-01': {
    plain: 'Only the owner can approve a payment that is pending, held or appealed.',
    protects: 'The AI, or a prompt hidden in an invoice, approving a payment on its own.',
  },
  'P-02': {
    plain: 'The owner can hold or vouch for any payment that has not settled.',
    protects: 'Vendors being auto-denied; every hold stays reversible by a person.',
  },
  'P-03': {
    plain: 'The automated checks may place a hold, and nothing stronger.',
    protects: 'Automation turning a suspicion into a denial.',
  },
  'P-04': {
    plain: "Fast-pay releases only vouched, eligible payments under the owner's standing limit with no unverified bank change.",
    protects: 'A changed bank account or an oversized invoice slipping through the fast lane.',
  },
  'P-05': {
    plain: 'Money moves only after an owner approval is on record for an approved payment.',
    protects: "Settlement without a human yes, including a forged or prompt-injected 'approval'.",
  },
  'P-06': {
    plain: 'Bank details change only after the owner verifies them by call-back to the number on file.',
    protects: "Business-email-compromise 'we changed our account, pay today' requests.",
  },
  'P-07': {
    plain: 'The system may read invoices and explain its decisions; explanations carry no authority.',
    protects: 'An explanation or model output being treated as a decision.',
  },
  'P-08': {
    plain: 'The owner decides whether a drafted reply to a sender goes out.',
    protects: 'The AI emailing a vendor on its own.',
  },
  'P-09': {
    plain: 'The owner sends an approved reply once, while the approval is on record.',
    protects: 'Duplicate or unapproved emails to vendors.',
  },
}

export function ruleCopy(rule: CedarRule): RuleCopy {
  return (
    RULE_COPY[rule.id] ?? {
      plain: rule.description ?? `${rule.principal} may ${rule.action ?? 'act'} on ${rule.resource ?? 'a payment'}`,
      protects: 'Anything this permit does not cover is denied by default.',
    }
  )
}

/** "Owner" / "System" / "Owner or System" for the Who column. */
export function principalLabel(principal: string): string {
  if (principal === 'any') return 'Owner or System'
  return principal
}

export function ruleActions(rule: CedarRule): string[] {
  return (rule.action ?? '')
    .split(',')
    .map((a) => a.trim())
    .filter(Boolean)
}

export type AgentOutcome = 'allow' | 'limited' | 'deny'

export interface AgentActionSpec {
  /** Cedar `Action::"…"` id, as in policies/vouch.cedar and policy/engine.py. */
  action: string
  label: string
  outcome: AgentOutcome
  reason: string
  /** Where to find the deciding rule in the live rule list; null when no permit exists for anyone. */
  lookup: { principal: 'System' | 'Owner' | 'any'; action: string } | null
}

/**
 * What the agent (the automated `System` principal; the LLM `Model` principal has no permits at all)
 * may do with a payment. Mirrors AUTOMATED_ACTIONS in backend `policy/engine.py`: allowed actions
 * carry a System permit, gated actions need an owner approval in the request context, denied actions
 * have no permit for anyone and fall through to Cedar's default deny.
 */
export const AGENT_ACTIONS: readonly AgentActionSpec[] = [
  {
    action: 'read',
    label: 'Read the invoice',
    outcome: 'allow',
    reason: 'Reading is permitted; nothing read becomes a decision.',
    lookup: { principal: 'System', action: 'read' },
  },
  {
    action: 'explain',
    label: 'Score the risk and explain it',
    outcome: 'allow',
    reason: 'Scores and LIME factors are advice for the owner, not authority.',
    lookup: { principal: 'System', action: 'explain' },
  },
  {
    action: 'hold',
    label: 'Place a hold',
    outcome: 'allow',
    reason: 'A hold is the strongest thing automation can do. Never a denial.',
    lookup: { principal: 'System', action: 'hold' },
  },
  {
    action: 'fast_pay',
    label: 'Fast-pay a vouched invoice',
    outcome: 'limited',
    reason: "Only vouched, eligible payments under the owner's standing limit with no unverified bank change.",
    lookup: { principal: 'System', action: 'fast_pay' },
  },
  {
    action: 'approve',
    label: 'Approve a payment',
    outcome: 'deny',
    reason: 'Owner only. No permit exists for System or Model.',
    lookup: { principal: 'Owner', action: 'approve' },
  },
  {
    action: 'settle',
    label: 'Settle: move the money',
    outcome: 'deny',
    reason: 'Denied until an owner approval is on record for an approved payment.',
    lookup: { principal: 'any', action: 'settle' },
  },
  {
    action: 'change_bank_details',
    label: "Change a vendor's bank details",
    outcome: 'deny',
    reason: 'Owner only, and only after a call-back to the number on file.',
    lookup: { principal: 'Owner', action: 'change_bank_details' },
  },
  {
    action: 'modify_amount',
    label: 'Change an amount, add a fee or round',
    outcome: 'deny',
    reason: 'No rule for anyone. Every dollar comes from the deterministic kernel.',
    lookup: null,
  },
  {
    action: 'deny_vendor',
    label: 'Deny a vendor',
    outcome: 'deny',
    reason: 'No rule for anyone. Vouch holds; it never denies.',
    lookup: null,
  },
  {
    action: 'send_kickback',
    label: 'Email the vendor',
    outcome: 'deny',
    reason: 'Owner only: approves the draft, then sends it once.',
    lookup: { principal: 'Owner', action: 'send_kickback' },
  },
]

export interface AgentDecision extends AgentActionSpec {
  /** Rule id from the live policy, or DEFAULT-DENY when no permit exists for anyone. */
  ruleId: string
}

export const DEFAULT_DENY = 'DEFAULT-DENY'

/** First permit for `action` that applies to `principal`; pass `any` to accept a permit for anyone. */
export function findRule(rules: CedarRule[], principal: string, action: string): CedarRule | undefined {
  return rules.find(
    (r) =>
      r.type === 'permit' &&
      (principal === 'any' || r.principal === principal || r.principal === 'any') &&
      ruleActions(r).includes(action),
  )
}

/** Resolve the agent's action matrix against the live rule list. Allowed rows first, denied last. */
export function agentDecisions(rules: CedarRule[]): AgentDecision[] {
  const order: Record<AgentOutcome, number> = { allow: 0, limited: 1, deny: 2 }
  return AGENT_ACTIONS.map((spec) => {
    const rule = spec.lookup ? findRule(rules, spec.lookup.principal, spec.lookup.action) : undefined
    return { ...spec, ruleId: rule?.id ?? DEFAULT_DENY }
  }).sort((a, b) => order[a.outcome] - order[b.outcome])
}

export interface RedTeamSummary {
  total: number
  blocked: number | null
  allBlocked: boolean
  /** "31/31 blocked" or "31 cases" while a result is pending. */
  label: string
}

export function redTeamSummary(total: number, blocked: number | null | undefined): RedTeamSummary {
  if (blocked == null) return { total, blocked: null, allBlocked: false, label: `${total} cases` }
  return { total, blocked, allBlocked: blocked >= total && total > 0, label: `${blocked}/${total} blocked` }
}
