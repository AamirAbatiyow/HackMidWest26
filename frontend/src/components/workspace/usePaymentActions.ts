import { useCallback, useState } from 'react'
import { toast } from 'sonner'
import type { Payment } from '@/api/types'
import { usePayments } from '@/store/PaymentsProvider'

export type PaymentAction = 'approve' | 'verify' | 'hold' | 'appeal'

/** One action runner shared by the panel, the palette, bulk toolbar and shortcuts. */
export function usePaymentActions() {
  const { approve, hold, appeal } = usePayments()
  const [pending, setPending] = useState<PaymentAction | null>(null)

  const run = useCallback(
    async (payment: Payment, action: PaymentAction, note?: string, opts?: { quiet?: boolean }) => {
      setPending(action)
      const name = `${payment.vendor.name} ${payment.invoiceNumber}`
      try {
        if (action === 'approve' || action === 'verify') {
          await approve(payment.id, note)
          if (!opts?.quiet) toast(`${name} · ${action === 'verify' ? 'verified · in batch' : 'in batch'}`, { description: 'No payout until owner approval.' })
        } else if (action === 'hold') {
          await hold(payment.id, note)
          if (!opts?.quiet) toast(`${name} · held for a quick check`, { description: 'Vendor not notified.' })
        } else {
          await appeal(payment.id, note)
          if (!opts?.quiet) toast(`${name} · vouched by owner`, { description: 'Trust adjusted. Vendor not notified.' })
        }
      } catch (err) {
        toast.error('Action failed', { description: err instanceof Error ? err.message : 'State unchanged.' })
      } finally {
        setPending(null)
      }
    },
    [approve, hold, appeal],
  )

  return { run, pending }
}
