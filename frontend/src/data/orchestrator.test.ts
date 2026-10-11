import { describe, expect, it } from 'vitest'
import { DEMO_PAYMENTS } from '@/data/payments'
import { byMostRecent, formatMs, mockTimelineFor, normalizeTimeline } from './orchestrator'

const byId = (id: string) => DEMO_PAYMENTS.find((p) => p.id === id)!

describe('normalizeTimeline', () => {
  it('maps the backend payload and keeps the recorded order', () => {
    const raw = {
      card_id: 'run_1.2',
      run_id: 'run_1',
      run_status: 'awaiting_approval',
      complete: true,
      last_seq: 31,
      steps: [
        { order: 2, step: 'format decision', node: 'intake', tool: 'deterministic route', engine: 'deterministic', duration_ms: 9, duration_scope: 'node', status: 'ok', result: 'deterministic route: csv_attachment → CSV parser · 0 model calls', at: '2026-10-10T15:00:01+00:00', detail: { decider_calls: 0 } },
        { order: 1, step: 'intake', node: 'intake', tool: 'file upload', engine: 'deterministic', duration_ms: 9.4, duration_scope: 'node', status: 'ok', result: 'received via upload', detail: {} },
        { order: 3, step: 'owner approval', node: 'settle', tool: 'owner (human in the loop)', engine: 'owner', duration_ms: null, duration_scope: null, status: 'pending', result: 'waiting', detail: {} },
      ],
      totals: { steps: 3, flagged: 0, measured_ms: 18 },
    }
    const t = normalizeTimeline(raw)
    expect(t.paymentId).toBe('run_1.2')
    expect(t.runId).toBe('run_1')
    expect(t.complete).toBe(true)
    expect(t.lastSeq).toBe(31)
    expect(t.steps.map((s) => s.step)).toEqual(['intake', 'format decision', 'owner approval'])
    expect(t.steps[0]!.durationMs).toBe(9)
    expect(t.steps[0]!.durationScope).toBe('node')
    expect(t.steps[2]!.durationMs).toBeNull()
    expect(t.steps[2]!.status).toBe('pending')
    expect(t.totals).toEqual({ steps: 3, flagged: 0, measuredMs: 18 })
  })

  it('tolerates a sparse payload and unknown statuses', () => {
    const t = normalizeTimeline({ steps: [{ step: 'x', status: 'weird' }, {}] })
    expect(t.complete).toBe(true)
    expect(t.steps).toHaveLength(2)
    expect(t.steps[0]!.status).toBe('ok')
    expect(t.steps[1]!.step).toBe('step 2')
    expect(t.steps[1]!.tool).toBe('—')
    expect(t.totals.flagged).toBe(0)
  })
})

describe('formatMs', () => {
  it('renders durations for humans', () => {
    expect(formatMs(null)).toBe('—')
    expect(formatMs(0)).toBe('<1 ms')
    expect(formatMs(12)).toBe('12 ms')
    expect(formatMs(1800)).toBe('1.8 s')
    expect(formatMs(12_400)).toBe('12 s')
  })
})

describe('byMostRecent', () => {
  it('orders invoices by receivedAt, newest first', () => {
    const ids = byMostRecent(DEMO_PAYMENTS).map((p) => p.id)
    expect(ids[0]).toBe('pay-007') // received -1 day at 16:00
    expect(ids.at(-1)).toBe('pay-003') // received -3 days at 09:00
    expect(ids).toHaveLength(DEMO_PAYMENTS.length)
  })
})

describe('mockTimelineFor', () => {
  it('is deterministic and follows the graph order', () => {
    const a = mockTimelineFor(byId('pay-001'), DEMO_PAYMENTS)
    const b = mockTimelineFor(byId('pay-001'), DEMO_PAYMENTS)
    expect(a).toEqual(b)
    const names = a.steps.map((s) => s.step)
    expect(a.steps.map((s) => s.order)).toEqual(names.map((_, i) => i + 1))
    const order = ['intake', 'format decision', 'read/parse', 'vendor screen', 'sender check', 'bank check', 'duplicate check', 'ring check', 'amount check', 'score', 'policy', 'funding', 'explain']
    expect(order.map((n) => names.indexOf(n))).toEqual([...order.keys()])
  })

  it('tells the demo story: clean fast-pay invoice', () => {
    const t = mockTimelineFor(byId('pay-001'), DEMO_PAYMENTS)
    const step = (n: string) => t.steps.find((s) => s.step === n)!
    expect(step('format decision').tool).toBe('deterministic route')
    expect(step('format decision').result).toContain('0 model calls')
    expect(step('read/parse').result).toContain('amount $6,400.00')
    expect(step('read/parse').result).toContain('RP-10482')
    expect(step('vendor screen').status).toBe('ok')
    expect(step('policy').result).toContain('lane: fast pay')
    expect(step('owner approval').status).toBe('pending')
    expect(t.totals.flagged).toBe(0)
  })

  it('flags the changed bank account and the sender for Warsaw Steel', () => {
    const t = mockTimelineFor(byId('pay-002'), DEMO_PAYMENTS)
    const step = (n: string) => t.steps.find((s) => s.step === n)!
    expect(step('sender check').status).toBe('flag')
    expect(step('bank check').status).toBe('flag')
    expect(step('bank check').result).toContain('changed 2 day(s) ago')
    expect(step('investigate').tool).toContain('[ato_bec]')
    expect(step('policy').status).toBe('hold')
    expect(step('policy').result).toContain('bank details changed')
    expect(step('owner approval').status).toBe('hold')
    expect(step('owner approval').result).toContain('Call Marta Kowalski')
  })

  it('names the duplicate, the split and the ring from the payment relations', () => {
    const dup = mockTimelineFor(byId('pay-004'), DEMO_PAYMENTS).steps.find((s) => s.step === 'duplicate check')!
    expect(dup.status).toBe('flag')
    expect(dup.result).toBe('possible duplicate of invoice MP-5521 in this batch')

    const split = mockTimelineFor(byId('pay-005'), DEMO_PAYMENTS).steps.find((s) => s.step === 'duplicate check')!
    expect(split.status).toBe('flag')
    expect(split.result).toContain('together $9,800.00')

    const ring = mockTimelineFor(byId('pay-007'), DEMO_PAYMENTS).steps.find((s) => s.step === 'ring check')!
    expect(ring.status).toBe('flag')
    expect(ring.result).toContain('bank shared with 2 other vendor(s)')
    expect(ring.result).toContain('phone shared with 1 other vendor(s)')
    const nova = mockTimelineFor(byId('pay-007'), DEMO_PAYMENTS)
    expect(nova.steps.find((s) => s.step === 'format decision')!.result).toContain('excel_attachment → Excel parser')
    expect(nova.steps.find((s) => s.step === 'sender check')).toBeUndefined() // uploads have no email headers
  })

  it('adds Cedar authorization, owner approval and settlement once the owner acted', () => {
    const settled = { ...byId('pay-003'), lifecycle: 'settled' as const, auditNotes: [{ id: 'n1', at: '2026-10-10T15:00:00Z', author: 'Dana', text: 'Approved in batch' }] }
    const t = mockTimelineFor(settled, DEMO_PAYMENTS)
    const names = t.steps.map((s) => s.step)
    expect(names.slice(-4)).toEqual(['authorization', 'owner approval', 'authorization', 'settlement'])
    expect(t.steps.find((s) => s.step === 'owner approval')!.result).toBe('approved by Dana · Approved in batch')
    expect(t.steps.at(-1)!.engine).toBe('xrpl')
    expect(t.steps.at(-1)!.result).toContain('settled $4,950.00 via standard lane')
  })
})
