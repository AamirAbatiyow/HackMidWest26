import { describe, expect, it } from 'vitest'
import type { CedarRule } from '@/api/types'
import { AGENT_ACTIONS, DEFAULT_DENY, RULE_COPY, agentDecisions, findRule, principalLabel, redTeamSummary, ruleActions, ruleCopy } from '@/data/cedar'
import { DEMO_TRUST } from '@/data/trust'

const rules = DEMO_TRUST.security_controls.policy_engine.rules

describe('RULE_COPY', () => {
  it('covers every rule the backend parses from vouch.cedar', () => {
    expect(rules.map((r) => r.id)).toEqual(['P-01', 'P-02', 'P-03', 'P-04', 'P-05', 'P-06', 'P-07', 'P-08', 'P-09'])
    for (const rule of rules) {
      expect(RULE_COPY[rule.id], rule.id).toBeDefined()
      expect(ruleCopy(rule).plain.length).toBeGreaterThan(10)
      expect(ruleCopy(rule).protects.length).toBeGreaterThan(10)
    }
  })

  it('falls back to the live description for an unknown rule', () => {
    const rule: CedarRule = { id: 'P-42', type: 'permit', principal: 'Owner', action: 'audit', resource: 'Payment', description: 'Owner may audit' }
    expect(ruleCopy(rule).plain).toBe('Owner may audit')
  })

  it('never uses the words the product avoids', () => {
    for (const copy of Object.values(RULE_COPY)) {
      expect(`${copy.plain} ${copy.protects}`).not.toMatch(/\breject/i)
    }
  })
})

describe('rule helpers', () => {
  it('splits multi-action rules and labels principals', () => {
    expect(ruleActions(rules[1]!)).toEqual(['hold', 'appeal'])
    expect(ruleActions({ ...rules[0]!, action: null })).toEqual([])
    expect(principalLabel('any')).toBe('Owner or System')
    expect(principalLabel('System')).toBe('System')
  })

  it('finds a permit by principal and action, honouring principal "any"', () => {
    expect(findRule(rules, 'System', 'hold')?.id).toBe('P-03')
    expect(findRule(rules, 'Owner', 'hold')?.id).toBe('P-02')
    const anySettle: CedarRule = { id: 'P-05', type: 'permit', principal: 'any', action: 'settle', resource: 'Payment', description: null }
    expect(findRule([anySettle], 'System', 'settle')?.id).toBe('P-05')
    expect(findRule(rules, 'Model', 'approve')).toBeUndefined()
  })
})

describe('agentDecisions', () => {
  const decisions = agentDecisions(rules)
  const byAction = Object.fromEntries(decisions.map((d) => [d.action, d]))

  it('mirrors the backend AUTOMATED_ACTIONS: read, explain, hold allowed; money and identity denied', () => {
    expect(byAction.read!.outcome).toBe('allow')
    expect(byAction.explain!.outcome).toBe('allow')
    expect(byAction.hold!.outcome).toBe('allow')
    expect(byAction.fast_pay!.outcome).toBe('limited')
    for (const action of ['approve', 'settle', 'change_bank_details', 'modify_amount', 'deny_vendor', 'send_kickback']) {
      expect(byAction[action]!.outcome, action).toBe('deny')
    }
  })

  it('attributes each decision to the real rule id from the live rules', () => {
    expect(byAction.read!.ruleId).toBe('P-07')
    expect(byAction.explain!.ruleId).toBe('P-07')
    expect(byAction.hold!.ruleId).toBe('P-03')
    expect(byAction.fast_pay!.ruleId).toBe('P-04')
    expect(byAction.approve!.ruleId).toBe('P-01')
    expect(byAction.settle!.ruleId).toBe('P-05')
    expect(byAction.change_bank_details!.ruleId).toBe('P-06')
    expect(byAction.send_kickback!.ruleId).toBe('P-09')
    expect(byAction.modify_amount!.ruleId).toBe(DEFAULT_DENY)
    expect(byAction.deny_vendor!.ruleId).toBe(DEFAULT_DENY)
  })

  it('orders allowed actions first and denied last', () => {
    const outcomes = decisions.map((d) => d.outcome)
    const firstDeny = outcomes.indexOf('deny')
    expect(outcomes.slice(0, firstDeny)).not.toContain('deny')
    expect(outcomes.slice(firstDeny)).toEqual(outcomes.slice(firstDeny).map(() => 'deny'))
    expect(decisions).toHaveLength(AGENT_ACTIONS.length)
  })

  it('works with a backend-shaped rule list where P-05 has principal "any"', () => {
    const live = rules.map((r) => (r.id === 'P-05' ? { ...r, principal: 'any' } : r))
    const settle = agentDecisions(live).find((d) => d.action === 'settle')!
    expect(settle.outcome).toBe('deny')
    expect(settle.ruleId).toBe('P-05')
  })

  it('falls back to DEFAULT-DENY when the live rule list is empty', () => {
    for (const d of agentDecisions([])) expect(d.ruleId).toBe(DEFAULT_DENY)
  })
})

describe('redTeamSummary', () => {
  it('reads 31/31 blocked from the trust payload', () => {
    const suite = DEMO_TRUST.security_controls.redteam_suite
    expect(redTeamSummary(suite.total_cases, suite.blocked_cases)).toEqual({ total: 31, blocked: 31, allBlocked: true, label: '31/31 blocked' })
  })

  it('flags a partial result and a pending run', () => {
    expect(redTeamSummary(31, 30)).toMatchObject({ allBlocked: false, label: '30/31 blocked' })
    expect(redTeamSummary(31, null)).toMatchObject({ blocked: null, allBlocked: false, label: '31 cases' })
    expect(redTeamSummary(31, undefined).label).toBe('31 cases')
  })
})
