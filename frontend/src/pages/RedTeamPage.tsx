import { ShieldCheck, ShieldOff } from 'lucide-react'
import { useApi } from '@/api/ApiProvider'
import { useAsync } from '@/api/useAsync'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ErrorState } from '@/components/vouch/States'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'

export function RedTeamPage() {
  const { api } = useApi()
  const { data, loading, error, reload } = useAsync(() => api.getRedTeam(), [api])
  const blocked = data?.cases.filter((c) => c.blocked).length ?? 0
  const total = data?.cases.length ?? 0
  const allBlocked = total > 0 && blocked === total

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[1.75rem] font-semibold tracking-[-0.02em]">Red-team results</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            We tried to talk the system into misbehaving. Each attempt below was stopped by a written policy rule, not by luck.
            {data && <> Last run {formatDateTime(data.runAt)} on {data.modelVersion}.</>}
          </p>
        </div>
        {data && (
          <span
            className={cn(
              'inline-flex h-9 items-center gap-2 rounded-full px-4 text-sm font-semibold ring-1 ring-inset',
              allBlocked ? 'bg-vouched-soft text-vouched ring-vouched-ring' : 'bg-attention-soft text-attention ring-attention-ring',
            )}
            role="status"
          >
            {allBlocked ? <ShieldCheck className="size-4" aria-hidden="true" /> : <ShieldOff className="size-4" aria-hidden="true" />}
            {blocked} of {total} blocked
          </span>
        )}
      </header>

      {error ? (
        <ErrorState message={error.message} onRetry={reload} />
      ) : loading || !data ? (
        <div className="card-surface space-y-3 p-6" aria-busy="true">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : (
        <section className="card-surface overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-12 pl-6">#</TableHead>
                <TableHead>Adversarial prompt</TableHead>
                <TableHead className="w-44">Category</TableHead>
                <TableHead className="w-28">Result</TableHead>
                <TableHead className="w-80 pr-6">Policy rule that stopped it</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.cases.map((c) => (
                <TableRow key={c.id}>
                  <TableCell className="pl-6 text-muted-foreground money">{c.id}</TableCell>
                  <TableCell className="max-w-md">
                    <p className="font-mono text-[12.5px] leading-relaxed break-words whitespace-normal text-foreground/90">“{c.prompt}”</p>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">{c.category}</TableCell>
                  <TableCell>
                    <span
                      className={cn(
                        'inline-flex h-6 items-center gap-1 rounded-full px-2 text-xs font-medium ring-1 ring-inset',
                        c.blocked ? 'bg-vouched-soft text-vouched ring-vouched-ring' : 'bg-problem-soft text-problem ring-problem-ring',
                      )}
                    >
                      {c.blocked ? <ShieldCheck className="size-3.5" aria-hidden="true" /> : <ShieldOff className="size-3.5" aria-hidden="true" />}
                      {c.blocked ? 'Blocked' : 'Got through'}
                    </span>
                  </TableCell>
                  <TableCell className="pr-6 text-sm whitespace-normal">
                    <span className="font-medium text-foreground">{c.rule.split(' · ')[0]}</span>
                    {c.rule.includes(' · ') && <span className="text-muted-foreground"> · {c.rule.split(' · ').slice(1).join(' · ')}</span>}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </section>
      )}
    </div>
  )
}
