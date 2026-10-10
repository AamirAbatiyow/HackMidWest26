import { ArrowLeft, CalendarClock, Check, Lock, Zap } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import type { FundingChoice } from '@/api/types'
import { Button } from '@/components/ui/button'
import { CountryFlag } from '@/components/vouch/CountryFlag'
import { Money } from '@/components/vouch/Money'
import { SlideToApprove } from '@/components/vouch/SlideToApprove'
import { EmptyState, LoadingList } from '@/components/vouch/States'
import { pluralize } from '@/lib/format'
import { cn } from '@/lib/utils'
import { usePayments } from '@/store/PaymentsProvider'

const POLICY_LINES = [
  'No interest or fees added.',
  'Amounts match your invoices.',
  'No unverified bank changes.',
]

export function ApprovalPage() {
  const { batchReady, loading, settle } = usePayments()
  const navigate = useNavigate()
  const [funding, setFunding] = useState<FundingChoice>('now')
  const [busy, setBusy] = useState(false)

  const total = useMemo(() => batchReady.reduce((s, p) => s + p.amount, 0), [batchReady])
  const vendors = useMemo(() => new Set(batchReady.map((p) => p.vendor.id)).size, [batchReady])

  const confirm = async () => {
    setBusy(true)
    try {
      const receipt = await settle(
        batchReady.map((p) => p.id),
        funding,
      )
      navigate(`/receipt/${receipt.batchId}`, { state: { receipt } })
    } catch (err) {
      setBusy(false)
      toast.error("The batch didn't send", {
        description: err instanceof Error ? err.message : 'Nothing was paid. Please try again.',
      })
      throw err
    }
  }

  return (
    <div className="mx-auto w-full max-w-md">
      <Link
        to="/"
        className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden="true" /> Back to desk
      </Link>

      <section
        aria-labelledby="approve-heading"
        className="card-surface overflow-hidden rounded-3xl shadow-sheet"
      >
        <header className="bg-primary px-6 pt-7 pb-6 text-primary-foreground">
          <p className="text-xs font-medium tracking-wide text-primary-foreground/70 uppercase">Owner approval</p>
          <h1 id="approve-heading" className="mt-2 text-2xl font-semibold tracking-[-0.02em]">
            {loading ? 'Loading…' : `Pay ${pluralize(vendors, 'vendor')}, `}
            {!loading && <Money amount={total} />}
            {!loading && ' total'}
          </h1>
          <p className="mt-1 text-sm text-primary-foreground/75">
            {pluralize(batchReady.length, 'payment')} · settled in one batch · USDC
          </p>
        </header>

        <div className="space-y-6 px-5 py-5">
          {loading ? (
            <LoadingList count={2} />
          ) : batchReady.length === 0 ? (
            <EmptyState
              title="Nothing in the batch yet"
              description="Vouched payments and anything you mark as verified show up here."
              action={
                <Button asChild variant="outline">
                  <Link to="/">Back to desk</Link>
                </Button>
              }
            />
          ) : (
            <>
              <ul className="divide-y rounded-2xl border bg-card" aria-label="Payments in this batch">
                {batchReady.map((p) => (
                  <li key={p.id} className="flex items-center gap-3 px-4 py-3">
                    <CountryFlag country={p.vendor.country} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{p.vendor.name}</p>
                      <p className="text-xs text-muted-foreground tabular-nums">Invoice {p.invoiceNumber}</p>
                    </div>
                    <Money amount={p.amount} className="text-sm font-semibold" />
                  </li>
                ))}
              </ul>

              <div className="rounded-2xl bg-vouched-soft/70 p-4 ring-1 ring-vouched-ring ring-inset">
                <p className="flex items-center gap-2 text-sm font-semibold text-vouched">
                  <Check className="size-4" aria-hidden="true" /> Policy check passed
                </p>
                <ul className="mt-2 space-y-1">
                  {POLICY_LINES.map((line) => (
                    <li key={line} className="flex items-start gap-2 text-sm text-foreground/85">
                      <Check className="mt-0.5 size-3.5 shrink-0 text-vouched" aria-hidden="true" />
                      {line}
                    </li>
                  ))}
                </ul>
              </div>

              <fieldset>
                <legend className="text-sm font-semibold">Funding</legend>
                <div className="mt-2 grid grid-cols-2 gap-2" role="radiogroup" aria-label="Funding choice">
                  {(
                    [
                      { value: 'now', label: 'Pay now', hint: 'Settles in about a minute', icon: Zap },
                      { value: 'scheduled', label: 'Schedule', hint: 'Tomorrow, 9:00 am', icon: CalendarClock },
                    ] as const
                  ).map((opt) => {
                    const Icon = opt.icon
                    const active = funding === opt.value
                    return (
                      <button
                        key={opt.value}
                        type="button"
                        role="radio"
                        aria-checked={active}
                        onClick={() => setFunding(opt.value)}
                        className={cn(
                          'flex flex-col items-start gap-1 rounded-xl border p-3 text-left transition-colors duration-150 outline-none focus-visible:ring-3 focus-visible:ring-ring/50',
                          active ? 'border-primary bg-accent' : 'border-border hover:bg-accent/50',
                        )}
                      >
                        <span className="flex items-center gap-2 text-sm font-medium">
                          <Icon className="size-4" aria-hidden="true" />
                          {opt.label}
                          {active && <Check className="ml-auto size-4 text-vouched" aria-hidden="true" />}
                        </span>
                        <span className="text-xs text-muted-foreground">{opt.hint}</span>
                      </button>
                    )
                  })}
                </div>
              </fieldset>

              <div className="space-y-3 pt-1">
                <SlideToApprove
                  label={`Slide to approve ${pluralize(vendors, 'vendor')}`}
                  confirmedLabel="Approved"
                  busy={busy}
                  onConfirm={confirm}
                />
                <p className="flex items-center justify-center gap-1.5 text-center text-[11px] text-muted-foreground">
                  <Lock className="size-3" aria-hidden="true" />
                  Signed on your device. Checked and explained, every line.
                </p>
              </div>
            </>
          )}
        </div>
      </section>
    </div>
  )
}
