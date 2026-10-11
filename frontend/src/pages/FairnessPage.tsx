import { useApi } from '@/api/ApiProvider'
import { useAsync } from '@/api/useAsync'
import { Sparkline } from '@/components/vouch/Sparkline'
import { ErrorState, LoadingRows } from '@/components/vouch/States'
import { Block, DenseTable, PageFrame, Td, Th } from '@/components/vouch/Table'
import { series } from '@/data/series'
import { formatInt, formatMoney, formatPercent } from '@/lib/format'
import { cn } from '@/lib/utils'

export function FairnessPage() {
  const { api } = useApi()
  const { data, error, loading, reload } = useAsync(() => api.getFairness(), [api])

  if (error) return <ErrorState message={error.message} onRetry={reload} />
  if (loading || !data) return <LoadingRows count={8} />

  const totalPayments = data.parity.reduce((s, c) => s + c.payments, 0)
  const spread = Math.max(...data.parity.map((c) => c.heldShare)) - Math.min(...data.parity.map((c) => c.heldShare))

  return (
    <PageFrame
      summary={`${data.period.toLowerCase()} · ${formatInt(totalPayments)} payments · ${data.fraudCaught.count} fraud caught (${formatMoney(data.fraudCaught.amount)}) · ${data.honestAffected.blocked} honest blocked · ${data.honestAffected.quickChecks} quick checks`}
      aside={<span>country is never a risk factor · no auto-deny</span>}
    >
      <Block title="Harm ledger" meta="caught vs. honest vendors affected">
        <DenseTable>
          <thead>
            <tr>
              <Th>Measure</Th>
              <Th width={96} right>
                Value
              </Th>
              <Th width={120}>12 wk</Th>
              <Th>Note</Th>
            </tr>
          </thead>
          <tbody>
            <tr className="row-interactive">
              <Td>Fraud caught</Td>
              <Td num right className="text-foreground">
                {data.fraudCaught.count}
              </Td>
              <Td>
                <Sparkline values={series('fraud', 12, 1, 2)} kind="bars" tone="amber" label="Fraud caught per week" />
              </Td>
              <Td muted className="text-xs">
                {formatMoney(data.fraudCaught.amount)} · {data.fraudCaught.examples.join(' · ')}
              </Td>
            </tr>
            <tr className="row-interactive">
              <Td>Honest vendors blocked</Td>
              <Td num right className="text-foreground">
                {data.honestAffected.blocked}
              </Td>
              <Td>
                <Sparkline values={series('blocked', 12, 0, 0)} kind="bars" label="Honest vendors blocked per week" />
              </Td>
              <Td muted className="text-xs">
                Vouch never auto-denies; every flag waits for an owner decision.
              </Td>
            </tr>
            <tr className="row-interactive">
              <Td>Honest vendors held for a quick check</Td>
              <Td num right className="text-foreground">
                {data.honestAffected.quickChecks}
              </Td>
              <Td>
                <Sparkline values={series('quick', 12, 2, 3)} kind="bars" label="Quick checks per week" />
              </Td>
              <Td muted className="text-xs">
                median resolve {data.honestAffected.avgResolveMinutes} min · vendor not notified
              </Td>
            </tr>
            <tr className="row-interactive">
              <Td>Share of payments held</Td>
              <Td num right className="text-foreground">
                {formatPercent(data.heldShare)}
              </Td>
              <Td>
                <Sparkline values={series('held', 12, data.heldShare, 0.04)} label="Held share trend" reference={data.heldShare} />
              </Td>
              <Td muted className="text-xs">
                avg delay {data.avgDelayDays.toFixed(1)} d
              </Td>
            </tr>
            <tr className="row-interactive">
              <Td>New small vendors paid on time</Td>
              <Td num right className="text-foreground">
                {formatPercent(data.newSmallVendorsOnTime)}
              </Td>
              <Td>
                <Sparkline values={series('ontime', 12, data.newSmallVendorsOnTime, 0.04)} label="On-time share trend" tone="accent" />
              </Td>
              <Td muted className="text-xs">
                first payments under the limit go through without history
              </Td>
            </tr>
          </tbody>
        </DenseTable>
      </Block>

      <Block title="Parity by country" meta={`held-share spread ${formatPercent(spread, 1)} · target < 2.0%`}>
        <DenseTable>
          <thead>
            <tr>
              <Th width={56}>Code</Th>
              <Th>Country</Th>
              <Th width={96} right>
                Payments
              </Th>
              <Th width={96} right>
                Held
              </Th>
              <Th width={120}>12 wk</Th>
              <Th width={96} right>
                Avg delay
              </Th>
              <Th width={120}>12 wk</Th>
              <Th width={120}>vs. mean</Th>
            </tr>
          </thead>
          <tbody>
            {data.parity.map((c) => {
              const diff = c.heldShare - data.heldShare
              return (
                <tr key={c.country} className="row-interactive">
                  <Td num className="text-xs">
                    {c.country}
                  </Td>
                  <Td className="text-foreground">{c.label}</Td>
                  <Td num right>
                    {formatInt(c.payments)}
                  </Td>
                  <Td num right className="text-foreground">
                    {formatPercent(c.heldShare)}
                  </Td>
                  <Td>
                    <Sparkline values={series(`held-${c.country}`, 12, c.heldShare, 0.05)} reference={data.heldShare} label={`${c.label} held share trend`} />
                  </Td>
                  <Td num right>
                    {c.avgDelayDays.toFixed(1)} d
                  </Td>
                  <Td>
                    <Sparkline values={series(`delay-${c.country}`, 12, c.avgDelayDays, 0.3)} label={`${c.label} delay trend`} />
                  </Td>
                  <Td num className={cn('text-xs', Math.abs(diff) >= 0.02 ? 'text-amber' : 'text-muted-foreground')}>
                    {diff >= 0 ? '+' : ''}
                    {(diff * 100).toFixed(1)} pt
                  </Td>
                </tr>
              )
            })}
          </tbody>
        </DenseTable>
      </Block>

      <Block title="Rules that bound harm" meta="code-enforced">
        <DenseTable>
          <thead>
            <tr>
              <Th width={64}>Rule</Th>
              <Th>Statement</Th>
              <Th width={120}>Check</Th>
            </tr>
          </thead>
          <tbody>
            {[
              ['P-10', 'Country, language and vendor size are never risk factors.', 'parity table'],
              ['P-13', 'No payment is auto-denied. Flags hold for a human decision.', 'blocked = 0'],
              ['P-14', 'Quick checks resolve the same day or escalate to the owner.', 'median resolve'],
              ['P-15', 'Vendors are never notified of a hold; outreach is the owner’s call.', 'audit log'],
            ].map(([rule, text, check]) => (
              <tr key={rule} className="row-interactive">
                <Td num className="text-xs text-foreground">
                  {rule}
                </Td>
                <Td className="whitespace-normal">{text}</Td>
                <Td num muted className="text-xs">
                  {check}
                </Td>
              </tr>
            ))}
          </tbody>
        </DenseTable>
      </Block>
    </PageFrame>
  )
}
