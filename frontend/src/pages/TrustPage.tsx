import { useApi } from '@/api/ApiProvider'
import type { CedarRule, NotYetItem, PolicyHoldReason, SenderCheck, TrustData } from '@/api/types'
import { useAsync } from '@/api/useAsync'
import { ErrorState, LoadingRows } from '@/components/vouch/States'
import { Block, DenseTable, PageFrame, Td, Th } from '@/components/vouch/Table'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    not_started: 'bg-amber-500/20 text-amber-400',
    not_implemented: 'bg-amber-500/20 text-amber-400',
    testnet_only: 'bg-purple-500/20 text-purple-400',
    provider_managed: 'bg-accent-cool/20 text-accent-cool',
  }
  return (
    <span className={cn('rounded-xs px-2 py-0.5 text-2xs font-medium uppercase', colors[status] ?? 'bg-muted text-muted-foreground')}>
      {status.replace(/_/g, ' ')}
    </span>
  )
}

function RuleTypeBadge({ type }: { type: 'permit' | 'forbid' }) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-xs px-1.5 py-0.5 text-2xs font-medium uppercase',
        type === 'permit' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400',
      )}
    >
      {type}
    </span>
  )
}

function PrincipalBadge({ principal }: { principal: string }) {
  const colors: Record<string, string> = {
    Owner: 'bg-accent-cool/20 text-accent-cool',
    System: 'bg-purple-500/20 text-purple-400',
    Model: 'bg-amber-500/20 text-amber-400',
    any: 'bg-muted text-muted-foreground',
  }
  return (
    <span className={cn('inline-flex items-center rounded-xs px-1.5 py-0.5 text-2xs font-medium', colors[principal] ?? 'bg-muted text-muted-foreground')}>
      {principal}
    </span>
  )
}

function CedarRulesTable({ rules }: { rules: CedarRule[] }) {
  return (
    <DenseTable>
      <thead>
        <tr>
          <Th width={60}>ID</Th>
          <Th width={80}>Type</Th>
          <Th width={80}>Principal</Th>
          <Th>Action</Th>
          <Th>Description</Th>
        </tr>
      </thead>
      <tbody>
        {rules.map((rule) => (
          <tr key={rule.id} className="row-interactive">
            <Td className="num text-foreground">{rule.id}</Td>
            <Td><RuleTypeBadge type={rule.type} /></Td>
            <Td><PrincipalBadge principal={rule.principal} /></Td>
            <Td className="text-xs text-foreground">{rule.action ?? '—'}</Td>
            <Td muted className="text-xs">{rule.description ?? '—'}</Td>
          </tr>
        ))}
      </tbody>
    </DenseTable>
  )
}

function SenderChecksTable({ checks }: { checks: SenderCheck[] }) {
  return (
    <DenseTable>
      <thead>
        <tr>
          <Th width={200}>Check</Th>
          <Th>Description</Th>
        </tr>
      </thead>
      <tbody>
        {checks.map((check) => (
          <tr key={check.check} className="row-interactive">
            <Td className="text-foreground">{check.check}</Td>
            <Td muted className="text-xs">{check.description}</Td>
          </tr>
        ))}
      </tbody>
    </DenseTable>
  )
}

function HoldReasonsTable({ reasons }: { reasons: PolicyHoldReason[] }) {
  return (
    <DenseTable>
      <thead>
        <tr>
          <Th>Hold Reason</Th>
          <Th>Resolution Path</Th>
        </tr>
      </thead>
      <tbody>
        {reasons.map((r, i) => (
          <tr key={i} className="row-interactive">
            <Td className="text-xs text-foreground">{r.reason}</Td>
            <Td muted className="text-xs">{r.resolution}</Td>
          </tr>
        ))}
      </tbody>
    </DenseTable>
  )
}

function NotYetTable({ items }: { items: NotYetItem[] }) {
  return (
    <DenseTable>
      <thead>
        <tr>
          <Th>Item</Th>
          <Th width={140}>Status</Th>
          <Th>Description</Th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.item} className="row-interactive">
            <Td className="text-foreground">{item.item}</Td>
            <Td><StatusBadge status={item.status} /></Td>
            <Td muted className="text-xs">{item.description}</Td>
          </tr>
        ))}
      </tbody>
    </DenseTable>
  )
}

function InfoCard({ label, value, description }: { label: string; value: string; description?: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-sm border bg-surface-1/50 p-3">
      <span className="text-2xs uppercase tracking-wider text-muted-foreground">{label}</span>
      <span className="text-sm font-medium text-foreground">{value}</span>
      {description && <span className="text-2xs text-muted-foreground">{description}</span>}
    </div>
  )
}

function StatCard({ label, value, tone = 'neutral' }: { label: string; value: number | string; tone?: 'neutral' | 'accent' | 'amber' }) {
  return (
    <div className="flex flex-col gap-1 rounded-sm border bg-surface-1/50 p-3">
      <span className="text-2xs uppercase tracking-wider text-muted-foreground">{label}</span>
      <span className={cn('num text-lg font-medium', tone === 'accent' ? 'text-accent-cool' : tone === 'amber' ? 'text-amber' : 'text-foreground')}>
        {value}
      </span>
    </div>
  )
}

function TagList({ items, color = 'default' }: { items: string[]; color?: 'default' | 'accent' | 'amber' }) {
  const colorClass = color === 'accent' ? 'bg-accent-cool/20 text-accent-cool' : color === 'amber' ? 'bg-amber-500/20 text-amber-400' : 'bg-muted text-muted-foreground'
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <span key={item} className={cn('rounded-xs px-2 py-0.5 text-2xs font-medium', colorClass)}>
          {item}
        </span>
      ))}
    </div>
  )
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return <h3 className="mb-2 text-sm font-medium text-foreground">{children}</h3>
}

function SectionDescription({ children }: { children: React.ReactNode }) {
  return <p className="mb-4 text-xs text-muted-foreground">{children}</p>
}

export function TrustPage() {
  const { api } = useApi()
  const { data, error, loading, reload } = useAsync(() => api.getTrust(), [api])

  if (error) return <ErrorState message={error.message} onRetry={reload} />
  if (loading || !data) return <LoadingRows count={8} />

  const trust: TrustData = data
  const sc = trust.security_controls
  const dh = trust.data_handling
  const infra = trust.infrastructure

  return (
    <PageFrame
      summary={`${sc.policy_engine.type} · ${sc.policy_engine.total_rules} Cedar rules · ${sc.redteam_suite.total_cases} red-team cases · ${trust.not_yet_implemented.items.length} items not yet`}
      aside={<span>generated {formatDateTime(trust.generated_at)}</span>}
    >
      {/* Overview Stats */}
      <Block title="Security Overview" meta="high-level security posture">
        <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-3 lg:grid-cols-6">
          <StatCard label="Cedar Policy Rules" value={sc.policy_engine.total_rules} tone="accent" />
          <StatCard label="Red-team Cases" value={sc.redteam_suite.total_cases} tone="accent" />
          <StatCard label="Sender Checks" value={sc.sender_verification.checks.length} />
          <StatCard label="Hold Reasons" value={sc.policy_hold_reasons.reasons.length} />
          <StatCard label="Pydantic Schemas" value={sc.pydantic_validation.validation_on.length} />
          <StatCard label="Not Yet Items" value={trust.not_yet_implemented.items.length} tone="amber" />
        </div>
      </Block>

      {/* Cedar Policy Engine */}
      <Block title="Cedar Policy Engine" meta={sc.policy_engine.type}>
        <div className="px-4 py-2">
          <SectionDescription>{sc.policy_engine.description}</SectionDescription>
        </div>
        <CedarRulesTable rules={sc.policy_engine.rules} />
      </Block>

      {/* Model Restrictions */}
      <Block title="Model Restrictions" meta="what the ML model cannot do">
        <div className="space-y-4 p-4">
          <SectionDescription>{sc.model_restrictions.description}</SectionDescription>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <SectionHeading>Permitted Actions</SectionHeading>
              <TagList items={sc.model_restrictions.permitted_actions} color="accent" />
            </div>
            <div>
              <SectionHeading>Forbidden Actions</SectionHeading>
              <TagList items={sc.model_restrictions.forbidden_actions} color="amber" />
            </div>
          </div>
        </div>
      </Block>

      {/* Sender Verification */}
      <Block title="Sender Verification" meta="deterministic email checks">
        <div className="px-4 py-2">
          <SectionDescription>{sc.sender_verification.description}</SectionDescription>
        </div>
        <SenderChecksTable checks={sc.sender_verification.checks} />
      </Block>

      {/* Red-team Suite */}
      <Block title="Red-team Suite" meta={sc.redteam_suite.endpoint}>
        <div className="space-y-4 p-4">
          <SectionDescription>{sc.redteam_suite.description}</SectionDescription>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <SectionHeading>Total Test Cases</SectionHeading>
              <span className="num text-2xl font-bold text-accent-cool">{sc.redteam_suite.total_cases}</span>
            </div>
            <div>
              <SectionHeading>Attack Categories</SectionHeading>
              <TagList items={sc.redteam_suite.categories} />
            </div>
          </div>
        </div>
      </Block>

      {/* Prompt Injection Defenses */}
      <Block title="Prompt Injection Defenses" meta="deterministic protection">
        <div className="space-y-3 p-4">
          <SectionDescription>{sc.prompt_injection_defenses.description}</SectionDescription>
          <div className="rounded-sm border border-amber-500/30 bg-amber-500/10 p-3">
            <span className="text-xs text-amber-400">{sc.prompt_injection_defenses.hold_reason}</span>
          </div>
        </div>
      </Block>

      {/* Pydantic Validation */}
      <Block title="Strict Schema Validation" meta="Pydantic models">
        <div className="space-y-4 p-4">
          <SectionDescription>{sc.pydantic_validation.description}</SectionDescription>
          <div>
            <SectionHeading>Validated Schemas</SectionHeading>
            <TagList items={sc.pydantic_validation.validation_on} color="accent" />
          </div>
        </div>
      </Block>

      {/* Policy Hold Reasons */}
      <Block title="Policy Hold Reasons" meta="every hold has a resolution">
        <div className="px-4 py-2">
          <SectionDescription>{sc.policy_hold_reasons.description}</SectionDescription>
        </div>
        <HoldReasonsTable reasons={sc.policy_hold_reasons.reasons} />
      </Block>

      {/* Data Handling */}
      <Block title="Data Handling" meta="storage and network isolation">
        <div className="grid gap-4 p-4 sm:grid-cols-2 lg:grid-cols-3">
          <InfoCard label="Database" value={dh.storage.database.type} description={dh.storage.database.description} />
          <InfoCard label="Database Location" value={dh.storage.database.location} />
          <InfoCard label="Object Storage" value={dh.storage.object_storage.configured ? 'Configured' : 'Not configured'} description={dh.storage.object_storage.region} />
        </div>
        <div className="border-t px-4 py-4">
          <SectionHeading>VPC Network Isolation</SectionHeading>
          <div className="mt-2 grid gap-2">
            {Object.entries(dh.network_isolation.vpc_private).map(([key, value]) => (
              <div key={key} className="flex items-start gap-2">
                <span className="inline-block h-1.5 w-1.5 mt-1.5 rounded-full bg-emerald-500" />
                <span className="text-xs text-muted-foreground">{value}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="border-t px-4 py-4">
          <SectionHeading>Cloud Firewall</SectionHeading>
          <div className="mt-2 flex items-center gap-2">
            <span className={cn('h-2 w-2 rounded-full', dh.network_isolation.firewall.default_deny_inbound ? 'bg-emerald-500' : 'bg-amber-500')} />
            <span className="text-xs text-foreground">
              {dh.network_isolation.firewall.default_deny_inbound ? 'Default deny inbound' : 'Allow inbound'}
            </span>
          </div>
          <div className="mt-2">
            <TagList items={dh.network_isolation.firewall.allowed_inbound} />
          </div>
        </div>
      </Block>

      {/* LLM Data Handling */}
      <Block title="LLM Data Handling" meta="where invoice data goes">
        <div className="grid gap-4 p-4 sm:grid-cols-2">
          <div className="rounded-sm border bg-surface-1/50 p-3">
            <span className="text-2xs uppercase tracking-wider text-muted-foreground">Deterministic Path</span>
            <p className="mt-1 text-xs text-muted-foreground">{dh.llm_data_handling.deterministic_path.description}</p>
            <div className="mt-2 flex items-center gap-2">
              <span className={cn('h-2 w-2 rounded-full', dh.llm_data_handling.deterministic_path.decider_active ? 'bg-emerald-500' : 'bg-muted-foreground')} />
              <span className="text-xs text-foreground">Decider: {dh.llm_data_handling.deterministic_path.decider_active ? 'Active' : 'Inactive'}</span>
            </div>
            <div className="mt-1 flex items-center gap-2">
              <span className="text-2xs text-muted-foreground">LLM Mode: {dh.llm_data_handling.deterministic_path.llm_mode}</span>
            </div>
          </div>
          <div className="rounded-sm border bg-surface-1/50 p-3">
            <span className="text-2xs uppercase tracking-wider text-muted-foreground">Hosted Inference</span>
            <p className="mt-1 text-xs text-muted-foreground">{dh.llm_data_handling.hosted_inference.description}</p>
            <div className="mt-2 text-xs">
              <span className="text-muted-foreground">Provider: </span>
              <span className="text-foreground">{dh.llm_data_handling.hosted_inference.provider}</span>
            </div>
          </div>
        </div>
      </Block>

      {/* Infrastructure */}
      <Block title="Infrastructure" meta={infra.deployment.region}>
        <div className="grid gap-4 p-4 sm:grid-cols-2 lg:grid-cols-3">
          <InfoCard label="Provider" value={infra.deployment.provider} />
          <InfoCard label="Region" value={infra.deployment.region} />
          <InfoCard label="Settlement" value={infra.settlement.network} description={infra.settlement.adapter} />
          <InfoCard label="Model" value={infra.model.name} description={infra.model.description} />
          <InfoCard label="Scorer" value={infra.model.scorer} />
        </div>
        <div className="border-t px-4 py-4">
          <SectionHeading>Akamai Products</SectionHeading>
          <div className="mt-2">
            <TagList items={infra.deployment.products} color="accent" />
          </div>
        </div>
      </Block>

      {/* What is NOT yet implemented */}
      <Block title="What is NOT Yet Implemented" meta="honest disclosure">
        <div className="px-4 py-2">
          <SectionDescription>{trust.not_yet_implemented.description}</SectionDescription>
        </div>
        <NotYetTable items={trust.not_yet_implemented.items} />
      </Block>
    </PageFrame>
  )
}
