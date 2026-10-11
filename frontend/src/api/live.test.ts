import { describe, expect, it } from 'vitest'
import { normalizeHighlights, normalizeModel, normalizePayment } from './live'

/** Trimmed copy of what GET /v1/payments returns for the Apex Global Trading demo card. */
const APEX = {
  id: 'run_abc.6',
  vendor: { id: 'v-apex', name: 'Apex Global Trading LLC', city: 'Kansas City', country: 'US', since: '2026-10-02', payments_completed: 0 },
  invoice_number: 'AGT-1007',
  amount: 12000.0,
  amount_cents: 1200000,
  due_date: '2026-10-18',
  status: 'verify',
  lifecycle: 'pending',
  risk: 'unrecognized_vendor',
  trust_score: 4,
  reason: 'Shares a bank account with two other vendors.',
  evidence: [
    { id: 'e1', label: 'bank account shared with other vendors (shared_bank)', weight: 1.0, direction: 'concern' },
    { id: 'e7', label: 'SPF/DKIM/DMARC pass for proton.me', weight: 0.35, direction: 'reassuring' },
  ],
  lime: [
    { feature: 'shared_bank', label: 'bank account shared with other vendors (shared_bank)', rule: 'shared_bank', weight: 3.0, value: 2.0 },
    { feature: 'tax_id_invalid', label: 'tax id fails checksum: yes', rule: 'tax_id_invalid', weight: 1.5, value: 1.0 },
    { feature: 'oob_verified', label: 'identity verified out-of-band: no', rule: 'oob_verified', weight: -0.4, value: 0.0 },
  ],
  lime_class: 'fake_vendor',
  scorer: 'local-torch',
  model_version: 'vouch-risk-3',
  highlights: [
    { field: 'vendor_name', label: 'Vendor', value: 'Apex Global Trading LLC', severity: 'warn', reason: 'vendor added 9 days ago, no payments yet', reasons: ['vendor added 9 days ago, no payments yet'] },
    { field: 'amount', label: 'Amount due', value: '$12,000.00', severity: 'high', reason: 'round-thousand amount', reasons: ['round-thousand amount'] },
    { field: 'bank_account', label: 'Bank account', value: 'US071000013345', severity: 'high', reason: 'bank account shared with 2 other vendors (Northgate Supply LLC, Summit Trading Imports)', reasons: ['bank account shared with 2 other vendors (Northgate Supply LLC, Summit Trading Imports)'] },
    { field: 'tax_id', label: 'Tax ID', value: '84-7712093', severity: 'high', reason: 'tax ID fails checksum', reasons: ['tax ID fails checksum'] },
    { field: 'phone', label: 'Phone', value: '+1-888-555-0123', severity: 'ok', reason: null, reasons: [] },
  ],
}

describe('normalizeModel', () => {
  it('maps lime rows toward a risk head: positive weight is a concern', () => {
    const m = normalizeModel(APEX)!
    expect(m.targetClass).toBe('fake_vendor')
    expect(m.scorer).toBe('local-torch')
    expect(m.modelVersion).toBe('vouch-risk-3')
    expect(m.factors).toHaveLength(3)
    expect(m.factors[0]).toMatchObject({ feature: 'shared_bank', weight: 3, value: 2, direction: 'concern', label: 'Bank account shared with 2 other vendors' })
    expect(m.factors[1]).toMatchObject({ direction: 'concern', label: 'Tax ID fails checksum' })
    expect(m.factors[2]).toMatchObject({ direction: 'reassuring', label: 'Identity not verified out-of-band' })
    expect(m.factors[0]!.rawLabel).toBe('bank account shared with other vendors (shared_bank)')
  })

  it('flips the sign convention when LIME explained the legitimacy head', () => {
    const m = normalizeModel({ lime: [{ feature: 'new_vendor', weight: -0.6, value: 1 }], lime_class: 'legitimacy' })!
    expect(m.factors[0]!.direction).toBe('concern')
  })

  it('returns undefined when the payload carries no model fields', () => {
    expect(normalizeModel({ id: 'x' })).toBeUndefined()
  })
})

describe('normalizeHighlights', () => {
  it('keeps field order and severities, preferring the reasons list', () => {
    const hs = normalizeHighlights(APEX.highlights)!
    expect(hs.map((h) => h.field)).toEqual(['vendor_name', 'amount', 'bank_account', 'tax_id', 'phone'])
    expect(hs.map((h) => h.severity)).toEqual(['warn', 'high', 'high', 'high', 'ok'])
    expect(hs[2]!.reasons).toEqual(['bank account shared with 2 other vendors (Northgate Supply LLC, Summit Trading Imports)'])
    expect(hs[4]!.reasons).toEqual([])
  })

  it('falls back to a single reason string and tolerates unknown severities', () => {
    const hs = normalizeHighlights([{ field: 'x', value: 'v', severity: 'danger', reason: 'bad' }, { field: 'y', value: 'w', severity: 'weird' }])!
    expect(hs[0]).toMatchObject({ severity: 'high', reasons: ['bad'], label: 'x' })
    expect(hs[1]!.severity).toBe('ok')
    expect(normalizeHighlights(undefined)).toBeUndefined()
  })
})

describe('normalizePayment', () => {
  it('wires model and highlights through alongside the existing fields', () => {
    const p = normalizePayment(APEX)
    expect(p.id).toBe('run_abc.6')
    expect(p.status).toBe('verify')
    expect(p.model?.factors.map((f) => f.feature)).toEqual(['shared_bank', 'tax_id_invalid', 'oob_verified'])
    expect(p.highlights?.filter((h) => h.severity === 'high')).toHaveLength(3)
    expect(p.evidence).toHaveLength(2)
  })
})
