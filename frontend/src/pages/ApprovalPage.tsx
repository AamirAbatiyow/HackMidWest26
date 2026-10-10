import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import type { FundingChoice } from '@/api/types'
import { SlideToApprove } from '@/components/vouch/SlideToApprove'
import { RiskTag } from '@/components/vouch/RiskTag'
import { StatusChip } from '@/components/vouch/StatusChip'
import { DenseTable, PageFrame, Td, Th } from '@/components/vouch/Table'
import { TrustMeter } from '@/components/vouch/TrustMeter'
import { APPROVAL_LIMIT } from '@/data/payments'
import { formatDate, formatMoney } from '@/lib/format'
import { cn } from '@/lib/utils'
import { usePayments } from '@/store/PaymentsProvider'
import { useUi } from '@/store/UiProvider'

const ROW = 'flex h-6 items-center justify-between gap-2 border-b text-xs last:border-b-0'

export function ApprovalPage() {
  const { batchReady, settle, payments } = usePayments()
  const { setLastSettlementId } = useUi()
  const navigate = useNavigate()
  const [funding, setFunding] = useState<FundingChoice>('now')
  const [excluded, setExcluded] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)

  const lines = batchReady.filter((p) => !excluded.has(p.id))
  const total = lines.reduce((s, p) => s + p.amount, 0)
  const overLimit = lines.filter((p) => p.amount > APPROVAL_LIMIT)
  const verified = lines.filter((p) => p.status !== 'vouched')
  const heldCount = payments.filter((p) => p.lifecycle === 'held').length

  const confirm = async () => {
    if (lines.length === 0) return
    setBusy(true)
    try {
      const receipt = await settle(
        lines.map((p) => p.id),
        funding,
      )
      setLastSettlementId(receipt.batchId)
      navigate(`/receipt/${encodeURIComponent(receipt.batchId)}`)
    } catch (err) {
      toast.error('Settlement failed', { description: err instanceof Error ? err.message : 'No payment was sent.' })
      setBusy(false)
    }
  }

  return (
    <PageFrame
      summary={`batch · ${lines.length} payments · ${formatMoney(total)} · ${verified.length} verified by you · ${heldCount} on hold (not in batch)`}
      aside={<span>policy default-deny · nothing moves without this step</span>}
    >
      <div className="flex min-h-full">
        <div className="min-w-0 flex-1">
          <DenseTable>
            <thead>
              <tr>
                <Th width={32}>
                  <span className="sr-only">Include</span>
                </Th>
                <Th>Vendor</Th>
                <Th width={100}>Invoice</Th>
                <Th width={88} right>
                  Amount
                </Th>
                <Th width={72}>Due</Th>
                <Th width={84}>Risk</Th>
                <Th width={80}>Trust</Th>
                <Th width={116}>Status</Th>
                <Th width={80} right>
                  Limit
                </Th>
              </tr>
            </thead>
            <tbody>
              {batchReady.length === 0 && (
                <tr>
                  <td colSpan={9} className="h-16 px-3 text-center text-xs text-muted-foreground">
                    Nothing in the batch. Approve vouched rows or mark verified ones on the Payments view.
                  </td>
                </tr>
              )}
              {batchReady.map((p) => {
                const out = excluded.has(p.id)
                return (
                  <tr key={p.id} className={cn('row-interactive', out && 'text-muted-foreground')}>
                    <Td className="border-l-2 border-l-transparent">
                      <input
                        type="checkbox"
                        aria-label={`Include ${p.vendor.name} ${p.invoiceNumber}`}
                        checked={!out}
                        onChange={() =>
                          setExcluded((prev) => {
                            const next = new Set(prev)
                            if (next.has(p.id)) next.delete(p.id)
                            else next.add(p.id)
                            return next
                          })
                        }
                        className="size-3.5 accent-[var(--accent-cool)]"
                      />
                    </Td>
                    <Td>
                      <span className={cn('block truncate font-medium', !out && 'text-foreground')}>{p.vendor.name}</span>
                    </Td>
                    <Td num className="text-xs">
                      {p.invoiceNumber}
                    </Td>
                    <Td num right className={cn(!out && 'text-foreground')}>
                      {formatMoney(p.amount)}
                    </Td>
                    <Td num className="text-xs">
                      {formatDate(p.dueDate)}
                    </Td>
                    <Td>
                      <RiskTag risk={p.risk} />
                    </Td>
                    <Td>
                      <TrustMeter score={p.trustScore} />
                    </Td>
                    <Td>
                      <StatusChip status={p.status} lifecycle={p.lifecycle} />
                    </Td>
                    <Td num right className={cn('text-xs', p.amount > APPROVAL_LIMIT ? 'text-amber' : 'text-muted-foreground')}>
                      {p.amount > APPROVAL_LIMIT ? `> ${formatMoney(APPROVAL_LIMIT)}` : 'within'}
                    </Td>
                  </tr>
                )
              })}
            </tbody>
            {lines.length > 0 && (
              <tfoot>
                <tr className="bg-surface-1">
                  <Td colSpan={3} className="text-xs text-muted-foreground">
                    {lines.length} included · {excluded.size} excluded
                  </Td>
                  <Td num right className="text-foreground">
                    {formatMoney(total)}
                  </Td>
                  <Td colSpan={5} className="text-xs text-muted-foreground">
                    {overLimit.length > 0 ? `${overLimit.length} above the ${formatMoney(APPROVAL_LIMIT)} single-payment limit · owner sign-off is this step` : `all within the ${formatMoney(APPROVAL_LIMIT)} limit`}
                  </Td>
                </tr>
              </tfoot>
            )}
          </DenseTable>
        </div>

        <aside className="flex w-panel shrink-0 flex-col border-l" aria-label="Approve batch">
          <div className="flex h-8 items-center justify-between border-b px-3">
            <h2 className="text-sm font-medium">Owner approval</h2>
            <span className="num text-2xs text-muted-foreground">Dana K. · KC Wholesale</span>
          </div>
          <div className="px-3 py-1">
            <div className={ROW}>
              <span className="text-muted-foreground">Payments</span>
              <span className="num">{lines.length}</span>
            </div>
            <div className={ROW}>
              <span className="text-muted-foreground">Total</span>
              <span className="num text-foreground">{formatMoney(total)}</span>
            </div>
            <div className={ROW}>
              <span className="text-muted-foreground">Network fee</span>
              <span className="num">none · absorbed by Vouch</span>
            </div>
            <div className={ROW}>
              <span className="text-muted-foreground">Rail</span>
              <span className="num">USDC · Base · stable settlement</span>
            </div>
            <div className={ROW}>
              <span className="text-muted-foreground">Interest or fees added</span>
              <span className="num">none · P-02</span>
            </div>
          </div>

          <div className="border-t px-3 py-2">
            <p className="label-caps pb-1">Funding</p>
            <div className="grid grid-cols-2 gap-1" role="radiogroup" aria-label="Funding">
              {(
                [
                  ['now', 'Fund now', 'settles in ~2 min'],
                  ['scheduled', 'Schedule', 'morning of each due date'],
                ] as const
              ).map(([id, label, hint]) => (
                <button
                  key={id}
                  type="button"
                  role="radio"
                  aria-checked={funding === id}
                  onClick={() => setFunding(id)}
                  className={cn('flex h-9 flex-col items-start justify-center rounded-xs border px-2 text-left outline-none focus-visible:ring-1 focus-visible:ring-ring', funding === id ? 'border-accent-cool/60 bg-accent-cool-soft' : 'hover:bg-surface-2')}
                >
                  <span className="text-xs">{label}</span>
                  <span className="num text-2xs text-muted-foreground">{hint}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="border-t px-3 py-2">
            <p className="label-caps pb-1">Checks before release</p>
            <ul className="text-xs">
              {[
                ['amounts from verified calculation', 'pass'],
                ['no bank change without call-back', verified.length ? `${verified.length} verified by owner` : 'pass'],
                ['duplicate / split detection', 'pass'],
                ['model output cannot move money', 'enforced'],
              ].map(([k, v]) => (
                <li key={k} className={ROW}>
                  <span className="text-foreground/85">{k}</span>
                  <span className="num text-muted-foreground">{v}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="mt-auto border-t p-2">
            <SlideToApprove
              label={lines.length ? `Slide to approve ${lines.length} · ${formatMoney(total)}` : 'Nothing to approve'}
              confirmedLabel="Approved · settling"
              onConfirm={confirm}
              disabled={lines.length === 0}
              busy={busy}
            />
            <p className="num pt-1.5 text-2xs text-muted-foreground">End or Enter approves from the keyboard · esc returns</p>
          </div>
        </aside>
      </div>
    </PageFrame>
  )
}
