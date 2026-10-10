import { toast } from 'sonner'
import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { EvidenceBar } from '@/components/vouch/EvidenceBar'
import { FastPayBadge, PaymentCard } from '@/components/vouch/PaymentCard'
import { RiskTag } from '@/components/vouch/RiskTag'
import { SlideToApprove } from '@/components/vouch/SlideToApprove'
import { StatusChip } from '@/components/vouch/StatusChip'
import { EmptyState, ErrorState, PaymentCardSkeleton } from '@/components/vouch/States'
import { TrustMeter } from '@/components/vouch/TrustMeter'
import { VendorTimelineRow } from '@/components/vouch/VendorTimelineRow'
import { DEMO_PAYMENTS } from '@/data/payments'
import {
  COLOR_TOKENS,
  MOTION_TOKENS,
  RADIUS_TOKENS,
  SHADOW_TOKENS,
  SPACING_TOKENS,
  TYPE_TOKENS,
} from '@/data/tokens'
import { cn } from '@/lib/utils'

function Section({ title, description, children, id }: { title: string; description?: string; children: ReactNode; id: string }) {
  return (
    <section aria-labelledby={`${id}-heading`} className="space-y-4">
      <div>
        <h2 id={`${id}-heading`} className="text-lg font-semibold tracking-[-0.01em]">
          {title}
        </h2>
        {description && <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>}
      </div>
      {children}
    </section>
  )
}

function Specimen({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn('card-surface p-5', className)}>
      <p className="mb-3 text-xs font-medium text-muted-foreground">{label}</p>
      {children}
    </div>
  )
}

export function TokensPage() {
  const sample = DEMO_PAYMENTS[1]!
  const vouched = DEMO_PAYMENTS[0]!

  return (
    <div className="space-y-12">
      <header>
        <h1 className="text-[1.75rem] font-semibold tracking-[-0.02em]">Design tokens and components</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          Everything below is driven by CSS variables in <code className="font-mono text-xs">src/index.css</code> and exposed to Tailwind through{' '}
          <code className="font-mono text-xs">@theme</code>. Flip the theme toggle to see the dark variants.
        </p>
      </header>

      <Section id="colors" title="Color" description="Navy and off-white carry the brand. Amber asks for your eyes, green says vouched, red is reserved for confirmed problems.">
        <div className="grid gap-4 lg:grid-cols-3">
          {COLOR_TOKENS.map((group) => (
            <div key={group.group} className="card-surface p-5">
              <h3 className="text-sm font-semibold">{group.group}</h3>
              <ul className="mt-3 space-y-2.5">
                {group.tokens.map((t) => (
                  <li key={t.cssVar} className="flex items-center gap-3">
                    <span className="size-9 shrink-0 rounded-lg ring-1 ring-foreground/10 ring-inset" style={{ background: `var(${t.cssVar})` }} aria-hidden="true" />
                    <div className="min-w-0">
                      <p className="text-sm font-medium">
                        {t.name} <code className="ml-1 font-mono text-[11px] text-muted-foreground">{t.cssVar}</code>
                      </p>
                      <p className="truncate text-xs text-muted-foreground">
                        {t.role} · <code className="font-mono">{t.tailwind}</code>
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </Section>

      <Section id="type" title="Type" description="Inter Variable with tabular, lining numerals for every amount (.money).">
        <div className="card-surface divide-y">
          {TYPE_TOKENS.map((t) => (
            <div key={t.name} className="grid items-baseline gap-2 px-5 py-4 sm:grid-cols-[10rem_1fr_10rem]">
              <p className="text-xs font-medium text-muted-foreground">{t.name}</p>
              <p className={cn('truncate', t.className)}>{t.sample}</p>
              <p className="text-xs text-muted-foreground sm:text-right">{t.note}</p>
            </div>
          ))}
        </div>
      </Section>

      <div className="grid gap-8 lg:grid-cols-2">
        <Section id="spacing" title="Spacing" description="A 4px grid. Cards use 20px padding; sections use 32px.">
          <div className="card-surface space-y-2.5 p-5">
            {SPACING_TOKENS.map((s) => (
              <div key={s.name} className="flex items-center gap-3">
                <code className="w-20 font-mono text-xs text-muted-foreground">{s.name}</code>
                <span className="h-4 rounded-sm bg-navy-400 dark:bg-navy-200" style={{ width: s.px }} aria-hidden="true" />
                <span className="text-xs tabular-nums">{s.px}px</span>
              </div>
            ))}
          </div>
        </Section>

        <Section id="radius" title="Radius, shadow, motion">
          <div className="card-surface space-y-5 p-5">
            <div className="flex flex-wrap gap-3">
              {RADIUS_TOKENS.map((r) => (
                <div key={r.name} className="flex flex-col items-center gap-1.5">
                  <span className="size-14 bg-navy-100 ring-1 ring-foreground/10 dark:bg-navy-800" style={{ borderRadius: r.cssVar === '—' ? 9999 : `var(${r.cssVar})` }} aria-hidden="true" />
                  <code className="font-mono text-[10px] text-muted-foreground">{r.name}</code>
                  <span className="text-[10px] text-muted-foreground">{r.px}</span>
                </div>
              ))}
            </div>
            <div className="flex flex-wrap gap-4">
              {SHADOW_TOKENS.map((s) => (
                <div key={s.name} className="flex flex-col items-center gap-1.5">
                  <span className="size-16 rounded-xl bg-card" style={{ boxShadow: `var(${s.cssVar})` }} aria-hidden="true" />
                  <code className="font-mono text-[10px] text-muted-foreground">{s.name}</code>
                </div>
              ))}
            </div>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
              {MOTION_TOKENS.map((m) => (
                <div key={m.name} className="contents">
                  <dt>
                    <code className="font-mono text-muted-foreground">{m.name}</code>
                  </dt>
                  <dd>
                    <span className="font-medium">{m.value}</span> <span className="text-muted-foreground">· {m.use}</span>
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        </Section>
      </div>

      <Section id="components" title="Components" description="Each piece reads correctly without color: icon plus text on every status.">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <Specimen label="Status chip">
            <div className="flex flex-wrap gap-2">
              <StatusChip status="vouched" />
              <StatusChip status="quick_check" />
              <StatusChip status="verify" />
              <StatusChip status="vouched" size="sm" />
            </div>
          </Specimen>
          <Specimen label="Risk tag">
            <div className="flex flex-wrap gap-2">
              <RiskTag risk="changed_bank" />
              <RiskTag risk="duplicate_or_split" />
              <RiskTag risk="unrecognized_vendor" />
              <RiskTag risk="none" showNone />
            </div>
          </Specimen>
          <Specimen label="Trust meter and fast-pay badge">
            <div className="space-y-3">
              <TrustMeter score={94} />
              <TrustMeter score={68} />
              <TrustMeter score={18} />
              <FastPayBadge />
            </div>
          </Specimen>
          <Specimen label="Evidence bars">
            <div className="space-y-4">
              {sample.evidence.slice(0, 3).map((f) => (
                <EvidenceBar key={f.id} factor={f} />
              ))}
            </div>
          </Specimen>
          <Specimen label="Vendor timeline rows">
            <ol>
              {sample.timeline.slice(0, 3).map((ev, i) => (
                <VendorTimelineRow key={ev.id} event={ev} isLast={i === 2} />
              ))}
            </ol>
          </Specimen>
          <Specimen label="Toast">
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onClick={() => toast.success('Reyes Packaging marked as verified', { description: 'Added to your batch.' })}>
                Success toast
              </Button>
              <Button variant="outline" size="sm" onClick={() => toast('Held for a quick check', { description: 'The vendor is not notified.' })}>
                Neutral toast
              </Button>
              <Button variant="outline" size="sm" onClick={() => toast.error("That didn't go through", { description: 'Nothing was paid.' })}>
                Error toast
              </Button>
            </div>
          </Specimen>
          <Specimen label="Slide to approve" className="md:col-span-2 xl:col-span-1">
            <SlideToApprove
              onConfirm={() => {
                toast.success('Approved (demo)')
              }}
            />
          </Specimen>
          <Specimen label="Loading skeleton" className="md:col-span-2">
            <PaymentCardSkeleton />
          </Specimen>
          <Specimen label="Empty state">
            <EmptyState title="Nothing due this week" description="When invoices arrive, they show up here." className="py-8" />
          </Specimen>
          <Specimen label="Error state">
            <ErrorState message="The API at localhost:8101 did not answer." onRetry={() => toast('Retrying…')} className="py-8" />
          </Specimen>
          <Specimen label="Payment card (vouched)" className="md:col-span-2 xl:col-span-3">
            <div className="grid gap-3 lg:grid-cols-2">
              <PaymentCard payment={vouched} onOpen={() => toast('Opens the evidence drawer on the desk')} />
              <PaymentCard payment={sample} onOpen={() => toast('Opens the evidence drawer on the desk')} />
            </div>
          </Specimen>
        </div>
      </Section>
    </div>
  )
}
