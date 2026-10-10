import { HeartHandshake, Scale, ShieldCheck, Timer, Users } from 'lucide-react'
import type { ReactNode } from 'react'
import { useApi } from '@/api/ApiProvider'
import { useAsync } from '@/api/useAsync'
import { CountryFlag } from '@/components/vouch/CountryFlag'
import { Money } from '@/components/vouch/Money'
import { ErrorState, StatSkeleton } from '@/components/vouch/States'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatInt, formatPercent } from '@/lib/format'
import { cn } from '@/lib/utils'

function Kpi({ label, value, hint, icon }: { label: string; value: ReactNode; hint: string; icon: ReactNode }) {
  return (
    <div className="card-surface p-5">
      <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
        <span aria-hidden="true">{icon}</span>
        {label}
      </div>
      <p className="mt-2 text-3xl font-semibold tracking-[-0.02em] money">{value}</p>
      <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
    </div>
  )
}

export function FairnessPage() {
  const { api } = useApi()
  const { data, loading, error, reload } = useAsync(() => api.getFairness(), [api])

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-[1.75rem] font-semibold tracking-[-0.02em]">Fairness and harm</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          Catching fraud only counts if honest vendors are not caught with it. Both numbers live side by side so you can see the trade-off.
          {data && <> Period: {data.period}.</>}
        </p>
      </header>

      {error ? (
        <ErrorState message={error.message} onRetry={reload} />
      ) : loading || !data ? (
        <div className="grid gap-4 md:grid-cols-2">
          <StatSkeleton className="h-44" />
          <StatSkeleton className="h-44" />
        </div>
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            <section className="card-surface border-l-[3px] border-l-problem p-6" aria-labelledby="fraud-heading">
              <h2 id="fraud-heading" className="flex items-center gap-2 text-sm font-semibold text-muted-foreground">
                <ShieldCheck className="size-4 text-problem" aria-hidden="true" /> Fraud caught
              </h2>
              <p className="mt-3 text-4xl font-semibold tracking-[-0.03em] money">{data.fraudCaught.count}</p>
              <p className="mt-1 text-sm text-muted-foreground">
                <Money amount={data.fraudCaught.amount} className="font-medium text-foreground" /> kept where it belongs
              </p>
              <ul className="mt-4 flex flex-wrap gap-2">
                {data.fraudCaught.examples.map((e) => (
                  <li key={e} className="rounded-md bg-muted px-2 py-1 text-xs font-medium">
                    {e}
                  </li>
                ))}
              </ul>
            </section>

            <section className="card-surface border-l-[3px] border-l-vouched p-6" aria-labelledby="honest-heading">
              <h2 id="honest-heading" className="flex items-center gap-2 text-sm font-semibold text-muted-foreground">
                <HeartHandshake className="size-4 text-vouched" aria-hidden="true" /> Honest vendors affected
              </h2>
              <p className="mt-3 text-4xl font-semibold tracking-[-0.03em] money">{data.honestAffected.blocked}</p>
              <p className="mt-1 text-sm text-muted-foreground">wrongly blocked. Not one.</p>
              <p className="mt-4 text-sm text-foreground/85">
                {data.honestAffected.quickChecks} honest vendors were asked for a quick check. Each was cleared in about{' '}
                <span className="font-medium money">
                  {Math.floor(data.honestAffected.avgResolveMinutes / 60)}h {data.honestAffected.avgResolveMinutes % 60}m
                </span>
                , and none were told they had been flagged.
              </p>
            </section>
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <Kpi
              label="Share of payments held"
              value={formatPercent(data.heldShare)}
              hint="Held for a quick check or a call-back"
              icon={<Scale className="size-4" />}
            />
            <Kpi
              label="Average delay added"
              value={`${data.avgDelayDays.toFixed(1)} days`}
              hint="Across all payments, including the ones never held"
              icon={<Timer className="size-4" />}
            />
            <Kpi
              label="New small vendors paid on time"
              value={formatPercent(data.newSmallVendorsOnTime)}
              hint="First invoice under $5,000, paid by its due date"
              icon={<Users className="size-4" />}
            />
          </div>

          <section className="card-surface overflow-hidden" aria-labelledby="parity-heading">
            <div className="border-b px-6 py-4">
              <h2 id="parity-heading" className="text-sm font-semibold">
                Parity across countries
              </h2>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Country is never a risk factor. Hold rates should look alike, and they do.
              </p>
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-6">Country</TableHead>
                  <TableHead className="text-right">Payments</TableHead>
                  <TableHead className="text-right">Held for a check</TableHead>
                  <TableHead className="text-right">Avg. delay</TableHead>
                  <TableHead className="w-48 pr-6">Parity</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.parity.map((row) => {
                  const maxShare = Math.max(...data.parity.map((r) => r.heldShare))
                  return (
                    <TableRow key={row.country}>
                      <TableCell className="pl-6 font-medium">
                        <span className="flex items-center gap-2">
                          <CountryFlag country={row.country} /> {row.label}
                        </span>
                      </TableCell>
                      <TableCell className="text-right money">{formatInt(row.payments)}</TableCell>
                      <TableCell className="text-right money">{formatPercent(row.heldShare)}</TableCell>
                      <TableCell className="text-right money">{row.avgDelayDays.toFixed(1)} d</TableCell>
                      <TableCell className="pr-6">
                        <div className="h-2 w-full overflow-hidden rounded-full bg-foreground/[0.06]" aria-hidden="true">
                          <div
                            className={cn('h-full rounded-full bg-navy-400 dark:bg-navy-200')}
                            style={{ width: `${(row.heldShare / maxShare) * 100}%` }}
                          />
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </section>

          <p className="rounded-2xl border border-dashed px-5 py-4 text-sm text-muted-foreground">
            <span className="font-medium text-foreground">Vouch never auto-denies anyone.</span> Every hold is a question for you, not a verdict on the vendor. Honest vendors who get checked are paid in full with no fee, and the check is never visible to them.
          </p>
        </>
      )}
    </div>
  )
}
