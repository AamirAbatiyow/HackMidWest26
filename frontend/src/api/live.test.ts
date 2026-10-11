import { describe, it, expect } from 'vitest'
import { normalizePayment } from './live'

describe('normalizePayment', () => {
  it('normalizes ring from backend format', () => {
    const backendPayment = {
      id: 'run-123.1',
      vendor: { id: 'v-apex', name: 'Apex Global Trading LLC', city: 'Kansas City', country: 'US' },
      invoice_number: 'AGT-1007',
      amount_cents: 1200000,
      due_date: '2026-10-18',
      status: 'verify',
      lifecycle: 'pending',
      risk: 'unrecognized_vendor',
      trust_score: 18,
      reason: 'New vendor shares a bank account with two other vendors.',
      fast_pay_eligible: false,
      source: 'email',
      received_at: '2026-10-11T10:00:00Z',
      evidence: [],
      timeline: [],
      checklist: [],
      audit_notes: [],
      ring: {
        nodes: [
          { id: 'v-apex', label: 'Apex Global Trading LLC', kind: 'vendor', focus: true },
          { id: 'bank:v-apex', label: 'Bank acct ···3345', kind: 'bank', focus: false },
          { id: 'v-northgate', label: 'Northgate Supply LLC', kind: 'vendor', focus: false },
          { id: 'v-summit', label: 'Summit Trading Imports', kind: 'vendor', focus: false },
        ],
        edges: [
          { from: 'v-apex', to: 'bank:v-apex' },
          { from: 'v-northgate', to: 'bank:v-apex' },
          { from: 'v-summit', to: 'bank:v-apex' },
        ],
      },
    }

    const payment = normalizePayment(backendPayment)

    expect(payment.ring).toBeDefined()
    expect(payment.ring?.nodes).toHaveLength(4)
    expect(payment.ring?.edges).toHaveLength(3)

    const focusNode = payment.ring?.nodes.find((n) => n.focus)
    expect(focusNode?.id).toBe('v-apex')
    expect(focusNode?.label).toBe('Apex Global Trading LLC')
    expect(focusNode?.kind).toBe('vendor')

    const bankNode = payment.ring?.nodes.find((n) => n.kind === 'bank')
    expect(bankNode?.id).toBe('bank:v-apex')
    expect(bankNode?.label).toBe('Bank acct ···3345')

    const vendorNodes = payment.ring?.nodes.filter((n) => n.kind === 'vendor')
    expect(vendorNodes).toHaveLength(3)

    expect(payment.ring?.edges[0]).toEqual({ from: 'v-apex', to: 'bank:v-apex' })
  })

  it('returns undefined ring when no ring in backend response', () => {
    const backendPayment = {
      id: 'run-123.1',
      vendor: { id: 'v-prairie', name: 'Prairie Packaging Supply' },
      invoice_number: 'PPS-2207',
      amount_cents: 118000,
      due_date: '2026-10-22',
      status: 'vouched',
      lifecycle: 'settled',
    }

    const payment = normalizePayment(backendPayment)

    expect(payment.ring).toBeUndefined()
  })

  it('returns undefined ring when ring is null', () => {
    const backendPayment = {
      id: 'run-123.1',
      vendor: { id: 'v-prairie', name: 'Prairie Packaging Supply' },
      invoice_number: 'PPS-2207',
      amount_cents: 118000,
      ring: null,
    }

    const payment = normalizePayment(backendPayment)

    expect(payment.ring).toBeUndefined()
  })

  it('returns undefined ring when ring has empty nodes', () => {
    const backendPayment = {
      id: 'run-123.1',
      vendor: { id: 'v-prairie', name: 'Prairie Packaging Supply' },
      invoice_number: 'PPS-2207',
      amount_cents: 118000,
      ring: { nodes: [], edges: [] },
    }

    const payment = normalizePayment(backendPayment)

    expect(payment.ring).toBeUndefined()
  })
})
