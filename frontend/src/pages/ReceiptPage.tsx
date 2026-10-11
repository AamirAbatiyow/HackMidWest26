import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { MoreDetails } from '@/components/vouch/MoreDetails'
import { EmptyState } from '@/components/vouch/States'
import { DenseTable, PageFrame, Td, Th } from '@/components/vouch/Table'
import { formatDateTime, formatMoney, truncateMiddle } from '@/lib/format'
import { usePayments } from '@/store/PaymentsProvider'

const ROW = 'flex h-6 items-center justify-between gap-2 border-b text-xs last:border-b-0'

export function ReceiptPage() {
  const { id = '' } = useParams()
  const { receipts } = usePayments()
  const receipt = receipts[id]
  const [copied, setCopied] = useState<string | null>(null)

  if (!receipt) {
    return (
      <PageFrame summary="Receipt not found">
        <EmptyState title="No receipt here" description="Pay a batch to get a receipt." action={<Link to="/approve" className="text-xs underline-offset-2 hover:underline">Approval</Link>} />
      </PageFrame>
    )
  }

  const copy = async (label: string, value: string) => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(label)
      setTimeout(() => setCopied(null), 1200)
    } catch {
      setCopied(null)
    }
  }

  return (
    <PageFrame summary={`Paid · ${receipt.lines.length} payments · ${formatMoney(receipt.totalAmount)}`} aside={<span>{formatDateTime(receipt.settledAt)}</span>}>
      <div className="flex min-h-full">
        <div className="min-w-0 flex-1">
          <DenseTable>
            <thead>
              <tr>
                <Th>Vendor</Th>
                <Th width={128}>Invoice</Th>
                <Th width={112} right>
                  Amount
                </Th>
                <Th width={96}>Status</Th>
              </tr>
            </thead>
            <tbody>
              {receipt.lines.map((l) => (
                <tr key={l.paymentId} className="row-interactive">
                  <Td className="font-medium text-foreground">{l.vendorName}</Td>
                  <Td num className="text-xs">
                    {l.invoiceNumber}
                  </Td>
                  <Td num right className="text-foreground">
                    {formatMoney(l.amount)}
                  </Td>
                  <Td className="text-xs">
                    <span className="inline-flex h-[18px] items-center rounded-xs border border-green/50 px-1 text-xs text-green">Paid</span>
                  </Td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="bg-surface-1">
                <Td colSpan={2} className="text-xs text-muted-foreground">
                  Total
                </Td>
                <Td num right className="text-foreground">
                  {formatMoney(receipt.totalAmount)}
                </Td>
                <Td />
              </tr>
            </tfoot>
          </DenseTable>
        </div>

        <aside className="flex w-panel shrink-0 flex-col border-l" aria-label="Settlement receipt">
          <div className="flex h-8 items-center justify-between border-b px-3">
            <h2 className="text-sm font-medium">Receipt</h2>
            <span className="num text-2xs text-muted-foreground">{receipt.funding === 'now' ? 'paid now' : `scheduled · ${receipt.scheduledFor ? formatDateTime(receipt.scheduledFor) : ''}`}</span>
          </div>
          <div className="px-3 py-1">
            <div className={ROW}>
              <span className="text-muted-foreground">Total</span>
              <span className="num text-foreground">{formatMoney(receipt.totalAmount)}</span>
            </div>
            <div className={ROW}>
              <span className="text-muted-foreground">Transaction</span>
              <span className="num flex items-center gap-2 text-foreground/90">
                {truncateMiddle(receipt.txId, 10, 8)}
                <button type="button" className="h-4 rounded-xs border px-1 text-2xs text-muted-foreground hover:text-foreground" onClick={() => void copy('Transaction', receipt.txId)}>
                  {copied === 'Transaction' ? 'copied' : 'copy'}
                </button>
              </span>
            </div>
          </div>
          <div className="border-t px-3 py-2">
            <a href={receipt.explorerUrl} target="_blank" rel="noreferrer" className="text-xs text-accent-cool underline-offset-2 hover:underline">
              View on XRPL ↗
            </a>
            <p className="pt-1 text-xs text-muted-foreground">Public proof of payment.</p>
          </div>
          <MoreDetails>
            {(
              [
                ['Batch ID', receipt.batchId, receipt.batchId],
                ['Transaction', truncateMiddle(receipt.txId, 12, 10), receipt.txId],
                ['Network', receipt.network, undefined],
                ['Paid at', formatDateTime(receipt.settledAt), undefined],
                ['Network fee', receipt.feeUsd > 0 ? formatMoney(receipt.feeUsd, { cents: true }) : 'none · absorbed by Vouch', undefined],
                ['Approved by', 'Dana K. · slide-to-approve', undefined],
              ] as const
            ).map(([k, v, raw]) => (
              <div key={k} className={ROW}>
                <span className="text-muted-foreground">{k}</span>
                <span className="num flex items-center gap-2 text-foreground/90">
                  {v}
                  {raw && (
                    <button type="button" className="h-4 rounded-xs border px-1 text-2xs text-muted-foreground hover:text-foreground" onClick={() => void copy(`${k} details`, raw)}>
                      {copied === `${k} details` ? 'copied' : 'copy'}
                    </button>
                  )}
                </span>
              </div>
            ))}
            <a href={receipt.explorerUrl} target="_blank" rel="noreferrer" className="num block truncate pt-1 text-2xs text-muted-foreground underline-offset-2 hover:underline">
              {receipt.explorerUrl}
            </a>
          </MoreDetails>
          <div className="mt-auto flex gap-1 border-t p-2">
            <Link to="/" className="flex h-7 flex-1 items-center justify-center rounded-xs border text-xs hover:bg-surface-2">
              Back to payments
            </Link>
            <button type="button" className="flex h-7 flex-1 items-center justify-center rounded-xs border text-xs hover:bg-surface-2" onClick={() => window.print()}>
              Print
            </button>
          </div>
        </aside>
      </div>
    </PageFrame>
  )
}
