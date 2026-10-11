import { Check, Minus, TriangleAlert } from 'lucide-react'
import type { Payment } from '@/api/types'
import { cn } from '@/lib/utils'

type Result = 'pass' | 'flag' | 'na'

interface MatrixRow {
  check: string
  result: Result
  weight: number
  action: string
}

/** Which checks fired, their weight, and what clears them. */
export function buildMatrix(p: Payment): MatrixRow[] {
  const concern = (match: RegExp) => p.evidence.find((e) => e.direction === 'concern' && match.test(e.label))
  const weight = (f?: { weight: number }) => (f ? Math.round(f.weight * 100) : 0)

  const bank = concern(/bank|account/i)
  const dup = concern(/invoice|duplicate|split|limit|pairs/i)
  const ring = concern(/shared|same bank|same phone|other vendors|virtual office/i)
  const history = p.vendor.paymentsCompleted === 0

  return [
    {
      check: 'Bank account',
      result: p.risk === 'changed_bank' ? 'flag' : 'pass',
      weight: p.risk === 'changed_bank' ? weight(bank) : 0,
      action: p.risk === 'changed_bank' ? 'Call the vendor on a number you already have' : '—',
    },
    {
      check: 'Duplicate or split bill',
      result: p.risk === 'duplicate_or_split' ? 'flag' : 'pass',
      weight: p.risk === 'duplicate_or_split' ? weight(dup) : 0,
      action: p.risk === 'duplicate_or_split' ? 'Ask the vendor if this is a new order' : '—',
    },
    {
      check: 'Links to other vendors',
      result: p.ring ? 'flag' : 'pass',
      weight: p.ring ? weight(ring) : 0,
      action: p.ring ? 'Check the tax ID and who owns the bank account' : '—',
    },
    {
      check: 'Amount matches the invoice',
      result: 'pass',
      weight: 0,
      action: '—',
    },
    {
      check: 'Payment history',
      result: history ? (p.status === 'vouched' ? 'na' : 'flag') : 'pass',
      weight: history ? weight(concern(/history|registered|first/i)) : 0,
      action: history ? (p.status === 'vouched' ? 'Small first payment, under the limit' : 'Your sign-off') : '—',
    },
  ]
}

const resultMeta: Record<Result, { label: string; icon: typeof Check; className: string }> = {
  pass: { label: 'pass', icon: Check, className: 'text-green' },
  flag: { label: 'flag', icon: TriangleAlert, className: 'text-amber' },
  na: { label: 'n/a', icon: Minus, className: 'text-muted-foreground' },
}

export function DecisionMatrix({ payment }: { payment: Payment }) {
  const rows = buildMatrix(payment)
  const flags = rows.filter((r) => r.result === 'flag').length
  const recommendation =
    payment.status === 'vouched' ? 'Clear to pay' : payment.status === 'verify' ? 'Call the vendor before paying' : 'Quick check first'

  return (
    <div className="overflow-hidden rounded-sm border">
      <table className="w-full text-xs">
        <thead>
          <tr className="label-caps border-b bg-surface-2 text-left">
            <th className="px-2 py-1 font-semibold">Check</th>
            <th className="px-2 py-1 font-semibold">Result</th>
            <th className="num px-2 py-1 text-right font-semibold">W</th>
            <th className="px-2 py-1 font-semibold">How to clear it</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const m = resultMeta[r.result]
            const Icon = m.icon
            return (
              <tr key={r.check} className="border-b last:border-b-0">
                <td className="px-2 py-1">{r.check}</td>
                <td className={cn('px-2 py-1', m.className)}>
                  <span className="inline-flex items-center gap-1">
                    <Icon className="size-3" aria-hidden="true" />
                    <span className="num">{m.label}</span>
                  </span>
                </td>
                <td className={cn('num px-2 py-1 text-right', r.weight === 0 ? 'text-muted-foreground' : 'text-amber')}>{r.weight || '·'}</td>
                <td className="px-2 py-1 text-muted-foreground">{r.action}</td>
              </tr>
            )
          })}
        </tbody>
        <tfoot>
          <tr className="bg-surface-2">
            <td colSpan={2} className="px-2 py-1 text-muted-foreground">
              {flags} flag{flags === 1 ? '' : 's'} · trust <span className="num">{payment.trustScore}</span>
            </td>
            <td colSpan={2} className={cn('px-2 py-1 text-right font-medium', payment.status === 'vouched' ? 'text-green' : 'text-amber')}>
              {recommendation}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  )
}
