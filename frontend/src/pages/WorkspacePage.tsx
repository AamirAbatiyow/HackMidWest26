import { useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { DetailPanel } from '@/components/workspace/DetailPanel'
import { PaymentsTable } from '@/components/workspace/PaymentsTable'
import { usePayments } from '@/store/PaymentsProvider'
import { useUi } from '@/store/UiProvider'

export function WorkspacePage() {
  const { activeId, panelOpen, open } = useUi()
  const { payments } = usePayments()
  const [params, setParams] = useSearchParams()
  const payment = panelOpen ? payments.find((p) => p.id === activeId) : undefined

  // ?payment= mirrors the open panel so a selection is shareable.
  useEffect(() => {
    const fromUrl = params.get('payment')
    if (fromUrl && !panelOpen && activeId === null) {
      open(fromUrl)
      return
    }
    const want = panelOpen && activeId ? activeId : ''
    if ((fromUrl ?? '') !== want) {
      const next = new URLSearchParams(params)
      if (want) next.set('payment', want)
      else next.delete('payment')
      setParams(next, { replace: true })
    }
  }, [activeId, panelOpen, params, open, setParams])

  return (
    <>
      <PaymentsTable />
      {payment && <DetailPanel payment={payment} className="w-panel shrink-0 border-l" />}
    </>
  )
}
