import { describe, expect, it } from 'vitest'
import { classLabel, formatWeight, limeFromEvidence, limeLabel, sortLime } from './lime'

describe('limeLabel', () => {
  it('interpolates shared-attribute counts', () => {
    expect(limeLabel('shared_bank', 2)).toBe('Bank account shared with 2 other vendors')
    expect(limeLabel('shared_phone', 1)).toBe('Phone number shared with 1 other vendor')
    expect(limeLabel('shared_tax_id', 0)).toBe('Tax ID not shared with other vendors')
  })

  it('phrases binary features by their value', () => {
    expect(limeLabel('tax_id_invalid', 1)).toBe('Tax ID fails checksum')
    expect(limeLabel('tax_id_invalid', 0)).toBe('Tax ID passes checksum')
    expect(limeLabel('address_virtual', 1)).toBe('Virtual office / PO box address')
    expect(limeLabel('round_amount', 1)).toBe('Round-thousand amount')
    expect(limeLabel('has_po', 0)).toBe('No purchase order')
  })

  it('handles count and ratio features', () => {
    expect(limeLabel('urgency_terms', 3)).toBe('Urgency language (3 terms)')
    expect(limeLabel('amount_vs_history', 3.2)).toBe('Amount is 3.2× this vendor’s usual')
    expect(limeLabel('neighbour_suspicion', 0.875)).toBe('Red flags among linked vendors')
    expect(limeLabel('amount_vs_history', 1.0)).toBe('Amount in line with this vendor’s usual')
    expect(limeLabel('history_count_log', 0)).toBe('No payment history yet')
    expect(limeLabel('history_count_log', 2.6)).toBe('Long payment history')
    expect(limeLabel('vendor_age_log', Math.log1p(9))).toBe('Vendor added less than 60 days ago')
    expect(limeLabel('vendor_age_log', Math.log1p(1460))).toBe('Long-standing vendor')
  })

  it('cleans the backend label for unknown features', () => {
    expect(limeLabel('mystery_feature', 1, 'mystery feature (mystery_feature > 0.5)')).toBe('Mystery feature')
    expect(limeLabel('other_thing', 1, 'other thing: yes')).toBe('Other thing')
    expect(limeLabel('bare_name', null)).toBe('bare name')
  })
})

describe('sortLime', () => {
  it('puts concerns first, each group by descending magnitude', () => {
    const sorted = sortLime([
      { id: 'a', weight: -0.9, direction: 'reassuring' as const },
      { id: 'b', weight: 0.6, direction: 'concern' as const },
      { id: 'c', weight: 3.0, direction: 'concern' as const },
      { id: 'd', weight: -0.3, direction: 'reassuring' as const },
    ])
    expect(sorted.map((f) => f.id)).toEqual(['c', 'b', 'a', 'd'])
  })
})

describe('formatWeight and classLabel', () => {
  it('signs weights by direction and names model heads', () => {
    expect(formatWeight({ id: 'x', feature: 'f', label: '', rawLabel: '', weight: 3, value: null, direction: 'concern' })).toBe('+3.00')
    expect(formatWeight({ id: 'x', feature: 'f', label: '', rawLabel: '', weight: -0.6, value: null, direction: 'reassuring' })).toBe('−0.60')
    expect(classLabel('fake_vendor')).toBe('fake vendor')
    expect(classLabel('ato_bec')).toBe('account takeover / BEC')
    expect(classLabel(null)).toBeNull()
  })
})

describe('limeFromEvidence', () => {
  it('lifts evidence into signed LIME factors for mock mode', () => {
    const m = limeFromEvidence([
      { id: 'e1', label: 'Same bank account as two other vendors', weight: 1, direction: 'concern' },
      { id: 'e2', label: 'Invoice format is clean and complete', weight: 0.2, direction: 'reassuring' },
    ])
    expect(m.factors[0]!.weight).toBe(1)
    expect(m.factors[1]!.weight).toBe(-0.2)
    expect(m.targetClass).toBeNull()
  })
})
