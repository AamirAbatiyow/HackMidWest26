import { useState } from 'react'
import { useApi } from '@/api/ApiProvider'
import { useAsync } from '@/api/useAsync'
import { ErrorState, LoadingRows } from '@/components/vouch/States'
import { Block, DenseTable, PageFrame, Td, Th } from '@/components/vouch/Table'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'

export function RedTeamPage() {
  const { api } = useApi()
  const { data, error, loading, reload } = useAsync(() => api.getRedTeam(), [api])
  const [openId, setOpenId] = useState<number | null>(null)

  if (error) return <ErrorState message={error.message} onRetry={reload} />
  if (loading || !data) return <LoadingRows count={10} />

  const blocked = data.cases.filter((c) => c.blocked).length
  const rules = new Map<string, number>()
  for (const c of data.cases) rules.set(c.rule, (rules.get(c.rule) ?? 0) + 1)

  return (
    <PageFrame summary={`${blocked}/${data.cases.length} blocked · ${rules.size} rules fired · ${data.modelVersion}`} aside={<span>run {formatDateTime(data.runAt)}</span>}>
      <Block title="Cases" meta="click a row for the full prompt">
        <DenseTable>
          <thead>
            <tr>
              <Th width={40}>#</Th>
              <Th width={176}>Category</Th>
              <Th>Prompt</Th>
              <Th width={88}>Result</Th>
              <Th width={300}>Rule</Th>
            </tr>
          </thead>
          <tbody>
            {data.cases.map((c) => {
              const open = openId === c.id
              return (
                <tr key={c.id} className="row-interactive cursor-default" data-active={open} onClick={() => setOpenId(open ? null : c.id)}>
                  <Td num muted className="text-xs">
                    {String(c.id).padStart(2, '0')}
                  </Td>
                  <Td className="text-foreground">{c.category}</Td>
                  <Td num className={cn('text-xs text-foreground/85', open ? 'h-auto py-1.5 whitespace-pre-wrap break-words' : 'truncate')}>
                    {c.prompt}
                  </Td>
                  <Td>
                    <span className={cn('num inline-flex h-[18px] items-center rounded-xs border px-1 text-2xs tracking-[0.04em]', c.blocked ? 'border-border text-foreground/85' : 'border-red/50 text-red')}>{c.blocked ? 'BLOCKED' : 'PASSED'}</span>
                  </Td>
                  <Td num muted className="truncate text-xs">
                    {c.rule}
                  </Td>
                </tr>
              )
            })}
          </tbody>
        </DenseTable>
      </Block>

      <Block title="Rules fired" meta={`${rules.size} distinct`}>
        <DenseTable>
          <thead>
            <tr>
              <Th width={64}>Rule</Th>
              <Th>Statement</Th>
              <Th width={96} right>
                Cases
              </Th>
            </tr>
          </thead>
          <tbody>
            {Array.from(rules.entries())
              .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
              .map(([rule, n]) => {
                const [code, text] = rule.split(' · ')
                return (
                  <tr key={rule} className="row-interactive">
                    <Td num className="text-xs text-foreground">
                      {code}
                    </Td>
                    <Td>{text}</Td>
                    <Td num right>
                      {n}
                    </Td>
                  </tr>
                )
              })}
          </tbody>
        </DenseTable>
      </Block>

      <Block title="Boundary" meta="what the model can and cannot do">
        <DenseTable>
          <thead>
            <tr>
              <Th width={200}>Capability</Th>
              <Th width={120}>Model</Th>
              <Th>Enforced by</Th>
            </tr>
          </thead>
          <tbody>
            {[
              ['Read invoice text and records', 'yes', 'read-only context · PII masked'],
              ['Write plain-English explanations', 'yes', 'output is text only'],
              ['Compute amounts', 'no', 'verified calculation service'],
              ['Approve, hold or move money', 'no', 'owner action + signed approval'],
              ['Change bank details or trust', 'no', 'call-back and evidence pipeline'],
            ].map(([k, v, note]) => (
              <tr key={k} className="row-interactive">
                <Td className="text-foreground">{k}</Td>
                <Td num className={cn('text-xs', v === 'no' ? 'text-muted-foreground' : 'text-foreground')}>
                  {v}
                </Td>
                <Td muted className="text-xs">
                  {note}
                </Td>
              </tr>
            ))}
          </tbody>
        </DenseTable>
      </Block>
    </PageFrame>
  )
}
