import { useMemo } from 'react'
import type { Payment, VouchStatus } from '@/api/types'
import { usePayments } from './PaymentsProvider'
import { useUi, type LaneFilter } from './UiProvider'

export const LANES: VouchStatus[] = ['vouched', 'quick_check', 'verify']

export function matchesFilter(p: Payment, filter: LaneFilter): boolean {
  switch (filter) {
    case 'all':
      return true
    case 'held':
      return p.lifecycle === 'held'
    case 'settled':
      return p.lifecycle === 'settled'
    case 'fastpay':
      return p.fastPayEligible
    default:
      return p.status === filter
  }
}

export function matchesSearch(p: Payment, q: string): boolean {
  if (!q) return true
  const hay = `${p.vendor.name} ${p.invoiceNumber} ${p.vendor.city} ${p.amount} ${p.risk} ${p.status}`.toLowerCase()
  return q
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((t) => hay.includes(t))
}

export interface Lane {
  status: VouchStatus
  rows: Payment[]
  total: number
  collapsed: boolean
}

/** Filtered, searched, lane-grouped rows plus the flat keyboard order. */
export function useVisibleRows() {
  const { payments } = usePayments()
  const { filter, search, collapsed } = useUi()

  return useMemo(() => {
    const filtered = payments.filter((p) => matchesFilter(p, filter) && matchesSearch(p, search))
    const lanes: Lane[] = LANES.map((status) => {
      const rows = filtered.filter((p) => p.status === status).sort((a, b) => +new Date(a.dueDate) - +new Date(b.dueDate))
      return { status, rows, total: rows.reduce((s, p) => s + p.amount, 0), collapsed: collapsed.has(status) }
    })
    const order = lanes.flatMap((l) => (l.collapsed ? [] : l.rows.map((p) => p.id)))
    return { filtered, lanes, order }
  }, [payments, filter, search, collapsed])
}
