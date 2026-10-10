import type {
  AuditNote,
  FundingChoice,
  Payment,
  SettlementReceipt,
  VouchApi,
} from './types'
import { DEMO_PAYMENTS } from '@/data/payments'
import { DEMO_NETWORK } from '@/data/network'
import { DEMO_REDTEAM } from '@/data/redteam'
import { DEMO_FAIRNESS } from '@/data/fairness'

const LATENCY_MS = 350

function wait(ms = LATENCY_MS): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

function clone<T>(v: T): T {
  return structuredClone(v)
}

function randomHex(len: number): string {
  const bytes = new Uint8Array(len / 2)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

function note(text: string | undefined, fallback: string): AuditNote {
  return {
    id: `n-${randomHex(8)}`,
    at: new Date().toISOString(),
    author: 'Dana',
    text: text?.trim() || fallback,
  }
}

/**
 * In-memory mock. State survives route changes but resets on reload,
 * which is what we want for a demo walkthrough.
 */
export function createMockApi(): VouchApi {
  let payments: Payment[] = clone(DEMO_PAYMENTS)

  const find = (id: string): Payment => {
    const p = payments.find((x) => x.id === id)
    if (!p) throw new Error(`Payment ${id} not found`)
    return p
  }

  const update = (id: string, patch: (p: Payment) => Payment): Payment => {
    payments = payments.map((p) => (p.id === id ? patch(p) : p))
    return clone(find(id))
  }

  return {
    mode: 'mock',

    async listPayments() {
      await wait()
      return clone(payments)
    },

    async getPayment(id) {
      await wait(150)
      return clone(find(id))
    },

    async approvePayment(id, text) {
      await wait(250)
      return update(id, (p) => ({
        ...p,
        status: 'vouched',
        lifecycle: 'approved',
        auditNotes: [note(text, 'Marked as verified by owner.'), ...p.auditNotes],
      }))
    },

    async holdPayment(id, text) {
      await wait(250)
      return update(id, (p) => ({
        ...p,
        lifecycle: 'held',
        auditNotes: [note(text, 'Held for a quick check.'), ...p.auditNotes],
      }))
    },

    async appealPayment(id, text) {
      await wait(250)
      return update(id, (p) => ({
        ...p,
        status: 'vouched',
        lifecycle: 'appealed',
        trustScore: Math.max(p.trustScore, 70),
        auditNotes: [note(text, 'Owner vouched for this vendor.'), ...p.auditNotes],
      }))
    },

    async settleBatch(ids, funding: FundingChoice) {
      await wait(400)
      const lines = ids.map((id) => {
        const p = find(id)
        return {
          paymentId: p.id,
          vendorName: p.vendor.name,
          invoiceNumber: p.invoiceNumber,
          amount: p.amount,
        }
      })
      payments = payments.map((p) => (ids.includes(p.id) ? { ...p, lifecycle: 'settled' } : p))
      const txId = `0x${randomHex(64)}`
      const scheduled = new Date()
      scheduled.setDate(scheduled.getDate() + 1)
      scheduled.setHours(9, 0, 0, 0)
      const receipt: SettlementReceipt = {
        batchId: `batch-${randomHex(6)}`,
        txId,
        explorerUrl: `https://explorer.vouch.example/tx/${txId}`,
        settledAt: new Date().toISOString(),
        funding,
        scheduledFor: funding === 'scheduled' ? scheduled.toISOString() : undefined,
        totalAmount: lines.reduce((s, l) => s + l.amount, 0),
        lines,
        network: 'USDC · Base',
        feeUsd: 0,
      }
      return receipt
    },

    async getNetwork() {
      await wait(200)
      // Nudge latencies a little so the page feels live.
      const jitter = (n: number) => Math.max(1, Math.round(n * (0.9 + Math.random() * 0.2)))
      const hops = DEMO_NETWORK.hops.map((h) => ({ ...h, p50Ms: jitter(h.p50Ms), p95Ms: jitter(h.p95Ms) }))
      return {
        ...clone(DEMO_NETWORK),
        hops,
        p50Ms: hops.reduce((s, h) => s + h.p50Ms, 0),
        p95Ms: hops.reduce((s, h) => s + h.p95Ms, 0),
        updatedAt: new Date().toISOString(),
      }
    },

    async getRedTeam() {
      await wait(200)
      return clone(DEMO_REDTEAM)
    },

    async getFairness() {
      await wait(200)
      return clone(DEMO_FAIRNESS)
    },

    async getInfo() {
      await wait(80)
      return { model: DEMO_NETWORK.modelVersion, policyMode: 'default-deny', version: 'mock' }
    },

    async getHealth() {
      await wait(50)
      return { ok: true, version: 'mock', latencyMs: 0 }
    },
  }
}
