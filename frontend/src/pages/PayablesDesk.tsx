import { ArrowRight, CheckCircle2, Clock3, PhoneCall, Wallet } from 'lucide-react'
import { useMemo, useRef, type ReactNode } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import type { Payment } from '@/api/types'
import { Button } from '@/components/ui/button'
import { EvidenceDrawer } from '@/components/vouch/EvidenceDrawer'
import { Money } from '@/components/vouch/Money'
import { PaymentCard } from '@/components/vouch/PaymentCard'
import { EmptyState, ErrorState, LoadingList, StatSkeleton } from '@/components/vouch/States'
import { pluralize } from '@/lib/format'
import { cn } from '@/lib/utils'
import { usePayments } from '@/store/PaymentsProvider'
import { useUi } from '@/store/UiProvider'

function Stat({
  label,
  value,
  hint,
  icon,
  tone = 'default',
}: {
  label: string
  value: ReactNode
  hint?: string
  icon: ReactNode
  tone?: 'default' | 'vouched' | 'attention'
}) {
  return (
    <div className="card-surface flex items-start gap-4 p-5">
      <span
        className={cn(
          'flex size-10 shrink-0 items-center justify-center rounded-xl',
          tone === 'vouched' && 'bg-vouched-soft text-vouched',
          tone === 'attention' && 'bg-attention-soft text-attention',
          tone === 'default' && 'bg-accent text-foreground',
        )}
        aria-hidden="true"
      >
        {icon}
      </span>
      <div className="min-w-0">
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        <p className="mt-0.5 text-2xl font-semibold tracking-[-0.02em]">{value}</p>
        {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
      </div>
    </div>
  )
}

export function PayablesDesk() {
  const { payments, loading, error, reload, batchReady } = usePayments()
  const { openAgentPanel } = useUi()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const selectedId = params.get('payment')
  const selected = useMemo(() => payments.find((p) => p.id === selectedId) ?? null, [payments, selectedId])
  // Keep the last opened payment mounted while the sheet animates closed.
  const lastSelected = useRef<Payment | null>(null)
  if (selected) lastSelected.current = selected

  const open = (p: Payment) => {
    setParams({ payment: p.id }, { replace: false })
    openAgentPanel(`Screening ${p.vendor.name} · ${p.invoiceNumber}`)
  }

  const onDrawerChange = (next: boolean) => {
    if (!next) {
      const copy = new URLSearchParams(params)
      copy.delete('payment')
      setParams(copy, { replace: true })
    }
  }

  const active = payments.filter((p) => p.lifecycle !== 'settled')
  const totalDue = active.reduce((s, p) => s + p.amount, 0)
  const vouched = active.filter((p) => p.status === 'vouched' && p.lifecycle !== 'held')
  const quick = active.filter((p) => p.status === 'quick_check' || p.lifecycle === 'held')
  const verify = active.filter((p) => p.status === 'verify' && p.lifecycle !== 'held')
  const batchTotal = batchReady.reduce((s, p) => s + p.amount, 0)
  const batchVendors = new Set(batchReady.map((p) => p.vendor.id)).size

  const sorted = useMemo(() => {
    const rank = (p: Payment) => (p.lifecycle === 'settled' ? 3 : p.status === 'verify' ? 0 : p.status === 'quick_check' ? 1 : 2)
    return [...payments].sort((a, b) => rank(a) - rank(b) || new Date(a.dueDate).getTime() - new Date(b.dueDate).getTime())
  }, [payments])

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-muted-foreground">Good evening, Dana</p>
          <h1 className="mt-1 text-[1.75rem] font-semibold tracking-[-0.02em]">Payables desk</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Every payment below has been checked and explained. You decide what gets paid.
          </p>
        </div>
        <Button
          size="lg"
          className="h-11 px-5 text-[15px]"
          disabled={loading || batchReady.length === 0}
          onClick={() => navigate('/approve')}
        >
          Approve batch
          {batchReady.length > 0 && (
            <span className="ml-1 rounded-full bg-primary-foreground/15 px-2 py-0.5 text-xs font-semibold tabular-nums">
              {batchReady.length}
            </span>
          )}
          <ArrowRight data-icon="inline-end" aria-hidden="true" />
        </Button>
      </div>

      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <StatSkeleton key={i} />
          ))}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Stat
            label="Due this week"
            value={<Money amount={totalDue} />}
            hint={`${pluralize(active.length, 'payment')} · ${pluralize(new Set(active.map((p) => p.vendor.id)).size, 'vendor')}`}
            icon={<Wallet className="size-5" />}
          />
          <Stat
            label="Vouched"
            value={vouched.length}
            hint="Checked and explained. Ready when you are."
            icon={<CheckCircle2 className="size-5" />}
            tone="vouched"
          />
          <Stat
            label="Held for a quick check"
            value={quick.length}
            hint="Usually a one-minute question."
            icon={<Clock3 className="size-5" />}
            tone="attention"
          />
          <Stat
            label="Verify before release"
            value={verify.length}
            hint="A short call clears these."
            icon={<PhoneCall className="size-5" />}
            tone="attention"
          />
        </div>
      )}

      <section aria-labelledby="payments-heading" className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 id="payments-heading" className="text-base font-semibold">
            This week’s payments
          </h2>
          {!loading && batchReady.length > 0 && (
            <p className="text-sm text-muted-foreground">
              Batch so far: <Money amount={batchTotal} className="font-medium text-foreground" /> to {pluralize(batchVendors, 'vendor')}
            </p>
          )}
        </div>

        {error ? (
          <ErrorState message={error.message} onRetry={() => void reload()} />
        ) : loading ? (
          <LoadingList count={4} />
        ) : sorted.length === 0 ? (
          <EmptyState
            title="Nothing due this week"
            description="When invoices arrive, they show up here with a plain-English check."
          />
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">
            {sorted.map((p) => (
              <PaymentCard key={p.id} payment={p} onOpen={open} selected={p.id === selectedId} />
            ))}
          </div>
        )}
      </section>

      <EvidenceDrawer payment={selected ?? lastSelected.current} open={selected !== null} onOpenChange={onDrawerChange} />
    </div>
  )
}
