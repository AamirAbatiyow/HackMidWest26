import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useApi } from '@/api/ApiProvider'
import type { FundingChoice, Payment, SettlementReceipt } from '@/api/types'

interface PaymentsContextValue {
  payments: Payment[]
  loading: boolean
  error: Error | null
  reload: () => Promise<void>
  getById: (id: string) => Payment | undefined
  approve: (id: string, note?: string) => Promise<Payment>
  hold: (id: string, note?: string) => Promise<Payment>
  appeal: (id: string, note?: string) => Promise<Payment>
  toggleChecklist: (paymentId: string, itemId: string) => void
  /** Payments that are ready to go into a batch (vouched and not yet settled/held). */
  batchReady: Payment[]
  settle: (ids: string[], funding: FundingChoice) => Promise<SettlementReceipt>
  receipts: Record<string, SettlementReceipt>
}

const PaymentsContext = createContext<PaymentsContextValue | null>(null)

export function PaymentsProvider({ children }: { children: ReactNode }) {
  const { api, mode } = useApi()
  const [payments, setPayments] = useState<Payment[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)
  const [receipts, setReceipts] = useState<Record<string, SettlementReceipt>>({})
  const requestId = useRef(0)

  const reload = useCallback(async () => {
    const id = ++requestId.current
    setLoading(true)
    setError(null)
    try {
      const list = await api.listPayments()
      if (id === requestId.current) setPayments(list)
    } catch (err) {
      if (id === requestId.current) setError(err instanceof Error ? err : new Error(String(err)))
    } finally {
      if (id === requestId.current) setLoading(false)
    }
  }, [api])

  useEffect(() => {
    void reload()
  }, [reload, mode])

  const replace = useCallback((next: Payment) => {
    setPayments((prev) => prev.map((p) => (p.id === next.id ? { ...next, checklist: next.checklist.length ? next.checklist : p.checklist } : p)))
  }, [])

  const approve = useCallback(
    async (id: string, note?: string) => {
      const next = await api.approvePayment(id, note)
      replace(next)
      return next
    },
    [api, replace],
  )

  const hold = useCallback(
    async (id: string, note?: string) => {
      const next = await api.holdPayment(id, note)
      replace(next)
      return next
    },
    [api, replace],
  )

  const appeal = useCallback(
    async (id: string, note?: string) => {
      const next = await api.appealPayment(id, note)
      replace(next)
      return next
    },
    [api, replace],
  )

  const toggleChecklist = useCallback((paymentId: string, itemId: string) => {
    setPayments((prev) =>
      prev.map((p) =>
        p.id === paymentId
          ? { ...p, checklist: p.checklist.map((c) => (c.id === itemId ? { ...c, done: !c.done } : c)) }
          : p,
      ),
    )
  }, [])

  const settle = useCallback(
    async (ids: string[], funding: FundingChoice) => {
      const receipt = await api.settleBatch(ids, funding)
      setReceipts((prev) => ({ ...prev, [receipt.batchId]: receipt }))
      setPayments((prev) => prev.map((p) => (ids.includes(p.id) ? { ...p, lifecycle: 'settled' } : p)))
      return receipt
    },
    [api],
  )

  const batchReady = useMemo(
    () => payments.filter((p) => p.status === 'vouched' && (p.lifecycle === 'pending' || p.lifecycle === 'approved' || p.lifecycle === 'appealed')),
    [payments],
  )

  const value = useMemo<PaymentsContextValue>(
    () => ({
      payments,
      loading,
      error,
      reload,
      getById: (id) => payments.find((p) => p.id === id),
      approve,
      hold,
      appeal,
      toggleChecklist,
      batchReady,
      settle,
      receipts,
    }),
    [payments, loading, error, reload, approve, hold, appeal, toggleChecklist, batchReady, settle, receipts],
  )

  return <PaymentsContext.Provider value={value}>{children}</PaymentsContext.Provider>
}

export function usePayments(): PaymentsContextValue {
  const ctx = useContext(PaymentsContext)
  if (!ctx) throw new Error('usePayments must be used inside <PaymentsProvider>')
  return ctx
}
