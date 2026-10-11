import { useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { DetailPanel } from '@/components/workspace/DetailPanel'
import { NextUpPanel } from '@/components/workspace/NextUpPanel'
import { PaymentsTable } from '@/components/workspace/PaymentsTable'
import { usePayments } from '@/store/PaymentsProvider'
import { useUi } from '@/store/UiProvider'
import { useVisibleRows } from '@/store/useVisibleRows'

export function WorkspacePage() {
  const { activeId, panelOpen, open, setPanelOpen } = useUi()
  const { payments, loading } = usePayments()
  const { order } = useVisibleRows()
  const [params, setParams] = useSearchParams()
  const seeded = useRef(false)
  const payment = payments.find((p) => p.id === activeId)

  // On first load: honor ?payment=, otherwise open the first flagged row. The panel is never empty.
  useEffect(() => {
    if (seeded.current || loading || payments.length === 0) return
    seeded.current = true
    const fromUrl = params.get('payment')
    if (fromUrl && payments.some((p) => p.id === fromUrl)) {
      open(fromUrl)
      return
    }
    const firstFlagged = order.map((id) => payments.find((p) => p.id === id)!).find((p) => p.status !== 'vouched' && p.lifecycle !== 'settled')
    if (firstFlagged) open(firstFlagged.id)
    else setPanelOpen(true)
  }, [loading, payments, params, order, open, setPanelOpen])

  // ?payment= mirrors the open row so a selection is shareable.
  useEffect(() => {
    if (!seeded.current) return
    const want = activeId && payment ? activeId : ''
    if ((params.get('payment') ?? '') !== want) {
      const next = new URLSearchParams(params)
      if (want) next.set('payment', want)
      else next.delete('payment')
      setParams(next, { replace: true })
    }
  }, [activeId, payment, params, setParams])

  return (
    <>
      <PaymentsTable />
      {panelOpen && (payment ? <DetailPanel payment={payment} className="w-panel shrink-0 border-l" /> : <NextUpPanel className="w-panel shrink-0 border-l" />)}
    </>
  )
}
