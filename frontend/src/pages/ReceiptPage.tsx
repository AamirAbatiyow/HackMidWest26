import { ArrowLeft, Check, Copy, ExternalLink, Layers } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import type { SettlementReceipt } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Money } from '@/components/vouch/Money'
import { EmptyState } from '@/components/vouch/States'
import { formatDateTime, pluralize, truncateMiddle } from '@/lib/format'
import { cn } from '@/lib/utils'
import { usePayments } from '@/store/PaymentsProvider'

const STAGES = [
  { id: 'policy', label: 'Policy check', ms: 700 },
  { id: 'sign', label: 'Signing on your device', ms: 900 },
  { id: 'broadcast', label: 'Sending the batch', ms: 1200 },
  { id: 'settle', label: 'Confirmed on-chain', ms: 800 },
]

function useSettlementProgress(enabled: boolean) {
  const [stage, setStage] = useState(0)
  useEffect(() => {
    if (!enabled) return
    let i = 0
    let t: ReturnType<typeof setTimeout>
    const next = () => {
      i += 1
      setStage(i)
      if (i < STAGES.length) t = setTimeout(next, STAGES[i]?.ms ?? 600)
    }
    t = setTimeout(next, STAGES[0]?.ms ?? 600)
    return () => clearTimeout(t)
  }, [enabled])
  return stage
}

export function ReceiptPage() {
  const { batchId = '' } = useParams()
  const location = useLocation()
  const { receipts } = usePayments()
  const receipt: SettlementReceipt | undefined =
    (location.state as { receipt?: SettlementReceipt } | null)?.receipt ?? receipts[batchId]
  const skipAnimation = new URLSearchParams(location.search).get('instant') === '1'
  const stage = useSettlementProgress(Boolean(receipt) && !skipAnimation)
  const done = skipAnimation || stage >= STAGES.length
  const [copied, setCopied] = useState(false)

  if (!receipt) {
    return (
      <div className="mx-auto max-w-md">
        <EmptyState
          title="No receipt here"
          description="This batch may have been settled in another session."
          action={
            <Button asChild variant="outline">
              <Link to="/">Back to desk</Link>
            </Button>
          }
        />
      </div>
    )
  }

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(receipt.txId)
      setCopied(true)
      toast.success('Transaction ID copied')
      setTimeout(() => setCopied(false), 1500)
    } catch {
      toast.error("Couldn't copy. Select the ID to copy it by hand.")
    }
  }

  return (
    <div className="mx-auto w-full max-w-md">
      <Link to="/" className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground">
        <ArrowLeft className="size-4" aria-hidden="true" /> Back to desk
      </Link>

      <section aria-live="polite" className="card-surface overflow-hidden rounded-3xl shadow-sheet">
        <header className={cn('px-6 pt-8 pb-7 text-center transition-colors duration-500', done ? 'bg-vouched text-white dark:text-navy-950' : 'bg-primary text-primary-foreground')}>
          <span className="mx-auto flex size-16 items-center justify-center rounded-full bg-white/15 ring-1 ring-white/30">
            {done ? (
              <svg viewBox="0 0 32 32" className="size-9 animate-pop" aria-hidden="true">
                <path d="M9 16.5 14 21.5 23.5 11" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" className="animate-draw" />
              </svg>
            ) : (
              <Layers className="size-7 animate-[vouch-pulse_1.4s_ease-in-out_infinite]" aria-hidden="true" />
            )}
          </span>
          <h1 className="mt-4 text-2xl font-semibold tracking-[-0.02em]">
            {done ? (receipt.funding === 'scheduled' ? 'Scheduled' : 'Settled') : 'Sending your batch'}
          </h1>
          <p className="mt-1 text-sm opacity-80">
            {done
              ? `${pluralize(receipt.lines.length, 'payment')} · settled in one batch`
              : STAGES[Math.min(stage, STAGES.length - 1)]?.label}
          </p>
          <Money amount={receipt.totalAmount} className="mt-4 block text-4xl font-semibold tracking-[-0.03em]" />
        </header>

        <div className="px-5 py-5">
          <ol className="grid grid-cols-4 gap-2" aria-label="Settlement progress">
            {STAGES.map((s, i) => {
              const state = done || i < stage ? 'done' : i === stage ? 'running' : 'pending'
              return (
                <li key={s.id} className="space-y-1.5">
                  <div className="h-1.5 overflow-hidden rounded-full bg-foreground/10">
                    <div
                      className={cn(
                        'h-full rounded-full bg-vouched transition-[width] duration-500 ease-[var(--ease-vouch)]',
                        state === 'done' ? 'w-full' : state === 'running' ? 'w-1/2 animate-[vouch-pulse_1s_ease-in-out_infinite]' : 'w-0',
                      )}
                    />
                  </div>
                  <p className={cn('text-[10px] leading-tight', state === 'pending' ? 'text-muted-foreground/70' : 'text-muted-foreground')}>
                    <span className="sr-only">{state === 'done' ? 'Done: ' : state === 'running' ? 'In progress: ' : 'Pending: '}</span>
                    {s.label}
                  </p>
                </li>
              )
            })}
          </ol>

          <div className={cn('mt-6 space-y-5 transition-opacity duration-300', done ? 'opacity-100' : 'opacity-40')} aria-hidden={!done}>
            <div className="rounded-2xl border bg-muted/40 p-4">
              <p className="text-xs font-medium text-muted-foreground">Transaction ID</p>
              <div className="mt-1.5 flex items-center gap-2">
                <code className="min-w-0 flex-1 truncate font-mono text-[13px] text-foreground" title={receipt.txId}>
                  {truncateMiddle(receipt.txId, 14, 10)}
                </code>
                <Button variant="outline" size="icon-sm" onClick={copy} aria-label="Copy transaction ID" disabled={!done}>
                  {copied ? <Check className="text-vouched" aria-hidden="true" /> : <Copy aria-hidden="true" />}
                </Button>
              </div>
              <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                <dt className="text-muted-foreground">Network</dt>
                <dd className="text-right font-medium">{receipt.network}</dd>
                <dt className="text-muted-foreground">Fees added</dt>
                <dd className="text-right font-medium money">{receipt.feeUsd === 0 ? 'None' : `$${receipt.feeUsd.toFixed(2)}`}</dd>
                <dt className="text-muted-foreground">{receipt.funding === 'scheduled' ? 'Scheduled for' : 'Settled at'}</dt>
                <dd className="text-right font-medium">{formatDateTime(receipt.scheduledFor ?? receipt.settledAt)}</dd>
              </dl>
            </div>

            <ul className="divide-y rounded-2xl border" aria-label="Per-vendor lines">
              {receipt.lines.map((l) => (
                <li key={l.paymentId} className="flex items-center gap-3 px-4 py-3">
                  <span className="flex size-6 items-center justify-center rounded-full bg-vouched-soft text-vouched" aria-hidden="true">
                    <Check className="size-3.5" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{l.vendorName}</p>
                    <p className="text-xs text-muted-foreground tabular-nums">Invoice {l.invoiceNumber}</p>
                  </div>
                  <Money amount={l.amount} className="text-sm font-semibold" />
                </li>
              ))}
            </ul>

            <div className="flex flex-col gap-2 sm:flex-row">
              <Button asChild variant="outline" className="h-10 flex-1">
                <a href={receipt.explorerUrl} target="_blank" rel="noreferrer">
                  <ExternalLink data-icon="inline-start" aria-hidden="true" />
                  View on explorer
                </a>
              </Button>
              <Button asChild className="h-10 flex-1">
                <Link to="/">Back to desk</Link>
              </Button>
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}
