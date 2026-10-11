import { ChevronRight } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '@/api/ApiProvider'
import type { CedarRule, NotYetItem, PolicyHoldReason, SenderCheck, TrustData } from '@/api/types'
import { useAsync } from '@/api/useAsync'
import { ErrorState, LoadingRows } from '@/components/vouch/States'
import { DenseTable, PageFrame, Td, Th } from '@/components/vouch/Table'
import { type AgentOutcome, type RedTeamSummary, agentDecisions, DEFAULT_DENY, principalLabel, redTeamSummary, ruleActions, ruleCopy } from '@/data/cedar'
import { formatDate, formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'

const OUTCOME_LABEL: Record<AgentOutcome, string> = { allow: 'ALLOW', limited: 'LIMITED', deny: 'DENY' }
const OUTCOME_CLASS: Record<AgentOutcome, string> = {
  allow: 'border-green/50 bg-green-soft text-green',
  limited: 'border-amber/50 bg-amber-soft text-amber',
  deny: 'border-red/50 bg-red-soft text-red',
}

export function DecisionBadge({ outcome }: { outcome: AgentOutcome }) {
  return (
    <span
      data-outcome={outcome}
      className={cn('num inline-flex h-6 min-w-16 items-center justify-center rounded-xs border px-2 text-xs font-semibold tracking-[0.06em]', OUTCOME_CLASS[outcome])}
    >
      {OUTCOME_LABEL[outcome]}
    </span>
  )
}

function RuleId({ id, muted }: { id: string; muted?: boolean }) {
  return (
    <span className={cn('num inline-flex h-5 items-center rounded-xs border px-1.5 text-2xs', muted ? 'border-border text-muted-foreground' : 'border-border bg-surface-2 text-foreground')}>
      {id === DEFAULT_DENY ? 'no rule' : id}
    </span>
  )
}

function SectionTitle({ children, meta }: { children: ReactNode; meta?: ReactNode }) {
  return (
    <div className="flex h-8 items-center justify-between gap-2 border-y bg-surface-1 px-3">
      <h2 className="text-xs font-medium">{children}</h2>
      {meta && <span className="num text-2xs text-muted-foreground">{meta}</span>}
    </div>
  )
}

function AgentMatrix({ rules }: { rules: CedarRule[] }) {
  const rows = agentDecisions(rules)
  return (
    <DenseTable data-testid="agent-matrix">
      <thead>
        <tr>
          <Th width={300}>The agent wants to…</Th>
          <Th width={110}>Cedar says</Th>
          <Th width={90}>Rule</Th>
          <Th>Why</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.action} className="row-interactive" data-outcome={row.outcome}>
            <Td className="h-9 text-sm text-foreground">
              {row.label}
              <span className="num ml-2 text-2xs text-muted-foreground">{row.action}</span>
            </Td>
            <Td className="h-9">
              <DecisionBadge outcome={row.outcome} />
            </Td>
            <Td className="h-9">
              <RuleId id={row.ruleId} muted={row.outcome === 'deny'} />
            </Td>
            <Td muted className="h-9 truncate text-xs">
              {row.reason}
            </Td>
          </tr>
        ))}
      </tbody>
    </DenseTable>
  )
}

function RulesTable({ rules }: { rules: CedarRule[] }) {
  return (
    <DenseTable data-testid="cedar-rules">
      <thead>
        <tr>
          <Th width={150}>Rule</Th>
          <Th width={120}>Who</Th>
          <Th>What it says</Th>
          <Th>Protects against</Th>
        </tr>
      </thead>
      <tbody>
        {rules.map((rule) => {
          const copy = ruleCopy(rule)
          return (
            <tr key={rule.id} className="row-interactive">
              <Td className="h-auto py-2 align-top">
                <RuleId id={rule.id} />
                <div className="num mt-1 text-2xs text-muted-foreground whitespace-normal">{ruleActions(rule).join(', ') || '—'}</div>
              </Td>
              <Td className="h-auto py-2 align-top text-xs text-foreground whitespace-normal">{principalLabel(rule.principal)}</Td>
              <Td className="h-auto py-2 align-top text-xs text-foreground whitespace-normal">{copy.plain}</Td>
              <Td muted className="h-auto py-2 align-top text-xs whitespace-normal">
                {copy.protects}
              </Td>
            </tr>
          )
        })}
      </tbody>
    </DenseTable>
  )
}

function RedTeamTile({ summary, running, ranAt }: { summary: RedTeamSummary; running: boolean; ranAt?: string | null }) {
  const tone = summary.blocked == null ? 'pending' : summary.allBlocked ? 'green' : 'red'
  return (
    <Link
      to="/redteam"
      data-testid="redteam-result"
      className={cn(
        'flex min-w-60 flex-col justify-center gap-1 rounded-md border px-5 py-4 transition-colors hover:bg-surface-2',
        tone === 'green' && 'border-green/50 bg-green-soft',
        tone === 'red' && 'border-red/50 bg-red-soft',
        tone === 'pending' && 'border-border bg-surface-1',
      )}
    >
      <span className="label-caps text-muted-foreground">Red-team result</span>
      <span className={cn('num text-3xl font-semibold leading-none', tone === 'green' ? 'text-green' : tone === 'red' ? 'text-red' : 'text-foreground')}>
        {running ? `running ${summary.total}…` : summary.label}
      </span>
      <span className="text-2xs text-muted-foreground">
        adversarial attacks on the agent · {ranAt ? `ran ${formatDate(ranAt, { month: 'short', day: 'numeric' })}` : 'GET /v1/redteam'}
      </span>
    </Link>
  )
}

export interface CedarGuardrailsProps {
  trust: TrustData
  redTeam: RedTeamSummary
  redTeamRunning?: boolean
}

/** The whole Cedar story on one screen: headline, one-line explanation, red-team tile, agent matrix, the rules. */
export function CedarGuardrails({ trust, redTeam, redTeamRunning = false }: CedarGuardrailsProps) {
  const engine = trust.security_controls.policy_engine
  const suite = trust.security_controls.redteam_suite
  return (
    <section data-testid="cedar-guardrails" className="border-b">
      <div className="flex flex-wrap items-stretch gap-6 px-6 py-6">
        <div className="min-w-0 flex-1 basis-[32rem]">
          <p className="label-caps text-muted-foreground">Cedar policy · {engine.type}</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground">{engine.total_rules} Cedar rules, default-deny</h1>
          <p className="mt-2 max-w-3xl text-sm leading-relaxed text-muted-foreground">
            Cedar is the permission layer around the agent: every action starts out <span className="text-red">denied</span>, and the agent may only do what one of these{' '}
            {engine.total_rules} rules explicitly <span className="text-green">allows</span>. It can read, score and hold an invoice. It cannot approve, settle, change bank details or
            email a vendor without the owner.
          </p>
        </div>
        <RedTeamTile summary={redTeam} running={redTeamRunning} ranAt={suite.ran_at} />
      </div>

      <SectionTitle meta="System principal · the LLM (Model) holds no permit at all">What the agent may do</SectionTitle>
      <AgentMatrix rules={engine.rules} />

      <SectionTitle meta="policies/vouch.cedar · via GET /v1/trust">The {engine.total_rules} rules</SectionTitle>
      <RulesTable rules={engine.rules} />
    </section>
  )
}

function Collapsed({ title, meta, children }: { title: string; meta?: ReactNode; children: ReactNode }) {
  return (
    <details className="group border-b">
      <summary className="flex h-8 cursor-pointer list-none items-center justify-between gap-2 bg-surface-1 px-3 text-xs font-medium text-foreground/85 hover:bg-surface-2 [&::-webkit-details-marker]:hidden">
        <span className="flex items-center gap-2">
          <ChevronRight className="size-3 text-muted-foreground transition-transform group-open:rotate-90" aria-hidden="true" />
          {title}
        </span>
        {meta && <span className="num text-2xs text-muted-foreground">{meta}</span>}
      </summary>
      {children}
    </details>
  )
}

function SenderChecksTable({ checks }: { checks: SenderCheck[] }) {
  return (
    <DenseTable>
      <thead>
        <tr>
          <Th width={220}>Check</Th>
          <Th>Description</Th>
        </tr>
      </thead>
      <tbody>
        {checks.map((check) => (
          <tr key={check.check} className="row-interactive">
            <Td className="text-xs text-foreground">{check.check}</Td>
            <Td muted className="truncate text-xs">
              {check.description}
            </Td>
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
          <Th>Hold reason</Th>
          <Th>Resolution path</Th>
        </tr>
      </thead>
      <tbody>
        {reasons.map((r) => (
          <tr key={r.reason} className="row-interactive">
            <Td className="truncate text-xs text-foreground">{r.reason}</Td>
            <Td muted className="truncate text-xs">
              {r.resolution}
            </Td>
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
          <Th width={240}>Item</Th>
          <Th width={150}>Status</Th>
          <Th>Description</Th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.item} className="row-interactive">
            <Td className="text-xs text-foreground">{item.item}</Td>
            <Td>
              <span className="num inline-flex h-5 items-center rounded-xs border border-amber/50 bg-amber-soft px-1.5 text-2xs text-amber">{item.status.replace(/_/g, ' ')}</span>
            </Td>
            <Td muted className="truncate text-xs">
              {item.description}
            </Td>
          </tr>
        ))}
      </tbody>
    </DenseTable>
  )
}

function Fact({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-sm border bg-surface-1/50 p-3">
      <span className="label-caps text-muted-foreground">{label}</span>
      <span className="text-sm text-foreground">{value}</span>
      {detail && <span className="text-2xs text-muted-foreground">{detail}</span>}
    </div>
  )
}

function Tags({ items }: { items: string[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <span key={item} className="num rounded-xs border px-1.5 py-0.5 text-2xs text-muted-foreground">
          {item}
        </span>
      ))}
    </div>
  )
}

/** Everything that is not Cedar, collapsed so it does not compete with the policy block. */
function MoreControls({ trust }: { trust: TrustData }) {
  const sc = trust.security_controls
  const dh = trust.data_handling
  const infra = trust.infrastructure
  return (
    <>
      <SectionTitle meta="expand for detail">More security controls</SectionTitle>
      <Collapsed title="Sender verification" meta={`${sc.sender_verification.checks.length} deterministic checks before any LLM reads the invoice`}>
        <SenderChecksTable checks={sc.sender_verification.checks} />
      </Collapsed>
      <Collapsed title="Hold reasons and resolution paths" meta={`${sc.policy_hold_reasons.reasons.length} reasons · every hold has a way out`}>
        <HoldReasonsTable reasons={sc.policy_hold_reasons.reasons} />
      </Collapsed>
      <Collapsed title="Schema validation and prompt-injection defenses" meta={`${sc.pydantic_validation.validation_on.length} strict Pydantic schemas`}>
        <div className="space-y-3 p-4">
          <p className="text-xs text-muted-foreground">{sc.pydantic_validation.description}</p>
          <Tags items={sc.pydantic_validation.validation_on} />
          <p className="text-xs text-muted-foreground">{sc.prompt_injection_defenses.description}</p>
          <div className="rounded-sm border border-amber/40 bg-amber-soft px-3 py-2 text-xs text-amber">{sc.prompt_injection_defenses.hold_reason}</div>
        </div>
      </Collapsed>
      <Collapsed title="Data handling and infrastructure" meta={`${infra.deployment.provider} · ${infra.deployment.region}`}>
        <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <Fact label="Database" value={dh.storage.database.type} detail={dh.storage.database.description} />
          <Fact label="Object storage" value={dh.storage.object_storage.configured ? 'Configured' : 'Not configured'} detail={dh.storage.object_storage.region} />
          <Fact label="Settlement" value={infra.settlement.network} detail={infra.settlement.adapter} />
          <Fact label="Risk model" value={infra.model.name} detail={infra.model.description} />
          <Fact label="LLM" value={dh.llm_data_handling.hosted_inference.provider} detail={`mode ${dh.llm_data_handling.deterministic_path.llm_mode}`} />
          <Fact label="Decider" value={dh.llm_data_handling.deterministic_path.decider_active ? 'Active' : 'Inactive'} detail={dh.llm_data_handling.deterministic_path.description} />
          <Fact label="Firewall" value={dh.network_isolation.firewall.default_deny_inbound ? 'Default deny inbound' : 'Allow inbound'} detail={dh.network_isolation.firewall.allowed_inbound.join(' · ')} />
          <Fact label="Demo data" value="Synthetic" detail={dh.demo_data.description} />
        </div>
        <div className="space-y-1 border-t px-4 py-3">
          {Object.values(dh.network_isolation.vpc_private).map((line) => (
            <p key={line} className="text-xs text-muted-foreground">
              {line}
            </p>
          ))}
        </div>
        <div className="border-t px-4 py-3">
          <Tags items={infra.deployment.products} />
        </div>
      </Collapsed>
      <Collapsed title="Not yet implemented" meta={`${trust.not_yet_implemented.items.length} items · honest disclosure`}>
        <NotYetTable items={trust.not_yet_implemented.items} />
      </Collapsed>
    </>
  )
}

export function TrustPage() {
  const { api } = useApi()
  const { data: trust, error, loading, reload } = useAsync(() => api.getTrust(), [api])
  // The backend reports blocked_cases only once the suite has run this session; otherwise run it (scripted model, seconds).
  const needRedTeam = trust != null && trust.security_controls.redteam_suite.blocked_cases == null
  const redTeam = useAsync(() => (needRedTeam ? api.getRedTeam() : Promise.resolve(null)), [api, needRedTeam])

  if (error) return <ErrorState message={error.message} onRetry={reload} />
  if (loading || !trust) return <LoadingRows count={8} />

  const suite = trust.security_controls.redteam_suite
  const report = needRedTeam ? redTeam.data : null
  const summary = report
    ? redTeamSummary(report.cases.length, report.cases.filter((c) => c.blocked).length)
    : redTeamSummary(suite.total_cases, suite.blocked_cases)

  return (
    <PageFrame
      summary={`${trust.security_controls.policy_engine.total_rules} Cedar rules · default-deny · red team ${summary.label}`}
      aside={<span>generated {formatDateTime(trust.generated_at)}</span>}
    >
      <CedarGuardrails trust={trust} redTeam={summary} redTeamRunning={needRedTeam && redTeam.loading} />
      <MoreControls trust={trust} />
    </PageFrame>
  )
}
