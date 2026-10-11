import { RiskTag } from '@/components/vouch/RiskTag'
import { StatusChip } from '@/components/vouch/StatusChip'
import { Block, DenseTable, PageFrame, Td, Th } from '@/components/vouch/Table'
import { TrustMeter } from '@/components/vouch/TrustMeter'
import { COLOR_TOKENS, ELEVATION_TOKENS, FONT_TOKENS, MOTION_TOKENS, RADIUS_TOKENS, SPACING_TOKENS, TYPE_TOKENS } from '@/data/tokens'
import { cn } from '@/lib/utils'

function KV({ rows, head }: { rows: { name: string; value: string; use: string }[]; head: [string, string, string] }) {
  return (
    <DenseTable>
      <thead>
        <tr>
          <Th width={220}>{head[0]}</Th>
          <Th width={240}>{head[1]}</Th>
          <Th>{head[2]}</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.name} className="row-interactive">
            <Td num className="text-xs text-foreground">
              {r.name}
            </Td>
            <Td num className="text-xs">
              {r.value}
            </Td>
            <Td muted className="text-xs">
              {r.use}
            </Td>
          </tr>
        ))}
      </tbody>
    </DenseTable>
  )
}

export function TokensPage() {
  const colorCount = COLOR_TOKENS.reduce((s, g) => s + g.tokens.length, 0)
  return (
    <PageFrame summary={`tokens · ${colorCount} colors · ${TYPE_TOKENS.length} type styles · ${RADIUS_TOKENS.length} radii · 4px grid · defined once in src/index.css`} aside={<span>dark is the design target · light remaps the same names</span>}>
      <Block title="Color" meta="semantic names only · no raw hex in components">
        <DenseTable>
          <thead>
            <tr>
              <Th width={40}>
                <span className="sr-only">Swatch</span>
              </Th>
              <Th width={160}>Token</Th>
              <Th width={200}>Tailwind</Th>
              <Th width={168}>Dark</Th>
              <Th width={168}>Light</Th>
              <Th>Role</Th>
            </tr>
          </thead>
          {COLOR_TOKENS.map((g) => (
            <tbody key={g.group}>
              <tr className="bg-surface-1">
                <td colSpan={6} className="h-7 border-y px-2 py-0 align-middle text-xs font-medium">
                  {g.group}
                </td>
              </tr>
              {g.tokens.map((t) => (
                <tr key={t.name} className="row-interactive">
                  <Td>
                    <span className="block size-3.5 rounded-xs border" style={{ background: `var(${t.cssVar})` }} aria-hidden="true" />
                  </Td>
                  <Td num className="text-xs text-foreground">
                    {t.cssVar}
                  </Td>
                  <Td num className="text-xs">
                    {t.tailwind}
                  </Td>
                  <Td num className="text-xs">
                    {t.dark}
                  </Td>
                  <Td num className="text-xs">
                    {t.light}
                  </Td>
                  <Td muted className="text-xs">
                    {t.role}
                  </Td>
                </tr>
              ))}
            </tbody>
          ))}
        </DenseTable>
      </Block>

      <Block title="Type" meta="Geist for labels · JetBrains Mono for numbers and IDs">
        <DenseTable>
          <thead>
            <tr>
              <Th width={160}>Style</Th>
              <Th width={96}>px / lh</Th>
              <Th>Sample</Th>
              <Th>Use</Th>
            </tr>
          </thead>
          <tbody>
            {TYPE_TOKENS.map((t) => (
              <tr key={t.name} className="row-interactive">
                <Td num className="text-xs text-foreground">
                  {t.name}
                </Td>
                <Td num className="text-xs">
                  {t.px}
                </Td>
                <Td>
                  <span className={cn(t.className, t.className.includes('label') || t.className.includes('2xs') ? '' : 'text-foreground')}>{t.sample}</span>
                </Td>
                <Td muted className="text-xs">
                  {t.note}
                </Td>
              </tr>
            ))}
          </tbody>
        </DenseTable>
        <KV head={['Font', 'Family', 'Use']} rows={FONT_TOKENS} />
      </Block>

      <Block title="Components" meta="status tags, risk codes, trust meter">
        <DenseTable>
          <thead>
            <tr>
              <Th width={220}>Primitive</Th>
              <Th>Rendering</Th>
              <Th>Rule</Th>
            </tr>
          </thead>
          <tbody>
            <tr className="row-interactive">
              <Td className="text-foreground">StatusChip</Td>
              <Td>
                <span className="flex items-center gap-1.5">
                  <StatusChip status="vouched" />
                  <StatusChip status="quick_check" />
                  <StatusChip status="verify" />
                  <StatusChip status="vouched" lifecycle="approved" />
                  <StatusChip status="quick_check" lifecycle="held" />
                  <StatusChip status="vouched" lifecycle="settled" />
                </span>
              </Td>
              <Td muted className="text-xs">
                square tag + 2px row border · never color alone · never “reject” or “denied”
              </Td>
            </tr>
            <tr className="row-interactive">
              <Td className="text-foreground">RiskTag</Td>
              <Td>
                <span className="flex items-center gap-1.5">
                  <RiskTag risk="none" />
                  <RiskTag risk="changed_bank" />
                  <RiskTag risk="duplicate_or_split" />
                  <RiskTag risk="unrecognized_vendor" />
                </span>
              </Td>
              <Td muted className="text-xs">
                mono codes · amber for bank / split · red only for a confirmed ring
              </Td>
            </tr>
            <tr className="row-interactive">
              <Td className="text-foreground">TrustMeter</Td>
              <Td>
                <span className="flex items-center gap-4">
                  <TrustMeter score={96} showLabel />
                  <TrustMeter score={71} showLabel />
                  <TrustMeter score={18} showLabel />
                </span>
              </Td>
              <Td muted className="text-xs">
                3px inline bar + number · bands strong ≥ 85 · building ≥ 55 · new
              </Td>
            </tr>
          </tbody>
        </DenseTable>
      </Block>

      <Block title="Spacing and rows" meta="4px grid">
        <KV head={['Token', 'Value', 'Use']} rows={SPACING_TOKENS} />
      </Block>
      <Block title="Radii" meta="2–4px · no pills">
        <KV head={['Token', 'Value', 'Use']} rows={RADIUS_TOKENS} />
      </Block>
      <Block title="Elevation" meta="flat">
        <KV head={['Token', 'Value', 'Use']} rows={ELEVATION_TOKENS} />
      </Block>
      <Block title="Motion" meta="reduced-motion respected" className="border-b-0">
        <KV head={['Token', 'Value', 'Use']} rows={MOTION_TOKENS} />
      </Block>
    </PageFrame>
  )
}
