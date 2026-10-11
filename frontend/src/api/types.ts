export type CountryCode = 'US' | 'MX' | 'PL' | 'BR'

/** What Vouch concluded after its checks. */
export type VouchStatus = 'vouched' | 'quick_check' | 'verify'

/** Where the payment is in the owner's workflow. */
export type Lifecycle = 'pending' | 'approved' | 'held' | 'appealed' | 'settled'

export type RiskType = 'changed_bank' | 'duplicate_or_split' | 'unrecognized_vendor' | 'none'

export interface Vendor {
  id: string
  name: string
  city: string
  country: CountryCode
  since: string // ISO date of first payment
  paymentsCompleted: number
}

export interface EvidenceFactor {
  id: string
  /** Plain-English contribution, e.g. "Bank account changed 2 days ago". */
  label: string
  /** 0..1 magnitude of the contribution. */
  weight: number
  /** "concern" renders amber, "reassuring" renders green. */
  direction: 'concern' | 'reassuring'
}

/** One LIME contribution from the VouchNet risk model, as returned on the payment's `lime` list. */
export interface LimeFactor {
  id: string
  /** Raw feature name, e.g. "shared_bank". */
  feature: string
  /** Plain-English label derived from the feature and its value. */
  label: string
  /** Backend label, kept to de-duplicate against `evidence`. */
  rawLabel: string
  /** Signed LIME weight toward the explained class (the sign is kept for display). */
  weight: number
  /** Feature value for this invoice, when known. */
  value: number | null
  direction: 'concern' | 'reassuring'
}

/** Which model head LIME explained and which scorer produced it. */
export interface ModelExplanation {
  factors: LimeFactor[]
  /** "ato_bec" | "insider" | "fake_vendor" | "legitimacy" | null */
  targetClass: string | null
  scorer: string | null
  modelVersion: string | null
}

export type HighlightSeverity = 'ok' | 'warn' | 'high'

/** One field of the invoice document with a severity and short reason tags. */
export interface InvoiceHighlight {
  field: string
  label: string
  value: string
  severity: HighlightSeverity
  reasons: string[]
}

export interface TimelineEvent {
  id: string
  date: string
  title: string
  detail?: string
  kind: 'payment' | 'change' | 'onboard' | 'check' | 'note'
}

export interface ChecklistItem {
  id: string
  text: string
  done: boolean
}

export interface RingNode {
  id: string
  label: string
  kind: 'vendor' | 'bank' | 'phone' | 'address'
  focus?: boolean
}

export interface RingEdge {
  from: string
  to: string
}

export interface RingGraph {
  nodes: RingNode[]
  edges: RingEdge[]
}

export interface AuditNote {
  id: string
  at: string
  text: string
  author: string
}

export interface PaymentRelation {
  kind: 'duplicate_of' | 'split_with'
  paymentId: string
}

export interface Payment {
  id: string
  vendor: Vendor
  invoiceNumber: string
  amount: number
  currency: 'USD'
  dueDate: string
  status: VouchStatus
  lifecycle: Lifecycle
  risk: RiskType
  /** 0..100 */
  trustScore: number
  reason: string
  fastPayEligible: boolean
  /** How the invoice arrived. */
  source: 'email' | 'upload'
  /** When the invoice was received. */
  receivedAt: string
  /** Link to another payment: a duplicate of it, or one half of a split. */
  relation?: PaymentRelation
  evidence: EvidenceFactor[]
  timeline: TimelineEvent[]
  checklist: ChecklistItem[]
  ring?: RingGraph
  auditNotes: AuditNote[]
  /** LIME factors from the risk model; absent when the backend did not score the card. */
  model?: ModelExplanation
  /** The invoice as document fields with suspicious ones flagged; absent in older payloads. */
  highlights?: InvoiceHighlight[]
}

export type FundingChoice = 'now' | 'scheduled'

export interface SettlementLine {
  paymentId: string
  vendorName: string
  invoiceNumber: string
  amount: number
}

export interface SettlementReceipt {
  batchId: string
  txId: string
  explorerUrl: string
  settledAt: string
  funding: FundingChoice
  scheduledFor?: string
  totalAmount: number
  lines: SettlementLine[]
  network: string
  feeUsd: number
}

export interface NetworkHop {
  id: string
  from: string
  to: string
  p50Ms: number
  p95Ms: number
  isPrivate: boolean
}

export interface NetworkStatus {
  hops: NetworkHop[]
  /** End-to-end latency; null when the backend did not report it. */
  p50Ms: number | null
  p95Ms: number | null
  modelVersion: string
  tokens: { promptToday: number; completionToday: number; perPaymentAvg: number }
  policyChecks: { passed: number; total: number }
  region: string
  updatedAt: string
}

export interface RedTeamCase {
  id: number
  prompt: string
  category: string
  blocked: boolean
  rule: string
}

export interface RedTeamReport {
  cases: RedTeamCase[]
  modelVersion: string
  runAt: string
}

export interface ApiInfo {
  model: string | null
  policyMode: string | null
  version?: string
  settlementAdapter?: string
  settlementNetwork?: string
  llmMode?: string
  scorer?: string
  runs?: number
  vendors?: number
}

export interface HealthStatus {
  ok: boolean
  version?: string
  latencyMs?: number
  /** Why the API is unreachable, for the status tag. */
  reason?: string
}

// Netstats page types
export interface PipelineStepStats {
  p50Ms: number | null
  p95Ms: number | null
  count: number
  latestMs: number | null
}

export interface InferenceEndpointStats {
  model: string
  baseUrl: string
  live: boolean
  p50Ms: number | null
  p95Ms: number | null
  count: number
  latestMs: number | null
}

export interface DeciderStats {
  engine: string
  enginesAvailable: string[]
  p50Ms: number | null
  p95Ms: number | null
  count: number
  latestMs: number | null
}

export interface StorageStats {
  configured: boolean
  ok: boolean | null
  latencyMs: number | null
  p50Ms: number | null
  p95Ms: number | null
}

export interface TierStats {
  name: string
  subnet: string
  products: string[]
  description: string
  configured: boolean
  healthy: boolean | null
  rttMs: number | null
}

export interface WaterfallStep {
  step: string
  latencyMs: number | null
}

export interface LatencyStats {
  updatedAt: string
  region: string
  pipelineSteps: Record<string, PipelineStepStats>
  inference: Record<string, InferenceEndpointStats>
  decider: DeciderStats
  postgres: StorageStats
  objectStorage: StorageStats
  tiers: Record<string, TierStats>
  lastRunWaterfall: {
    runId: string
    steps: WaterfallStep[]
  } | null
}

export interface FirewallRule {
  id: string
  direction: string
  protocol: string
  ports: string
  source?: string
  destination?: string
  action: string
  label: string
}

export interface TopologyNode {
  id: string
  label: string
  tier: string | null
  product: string | null
  x: number
  y: number
  configured?: boolean
}

export interface TopologyEdge {
  id: string
  from: string
  to: string
  label: string
  private: boolean
}

export interface TierInfo {
  name: string
  subnet: string
  products: string[]
  description: string
}

export interface TopologyData {
  updatedAt: string
  region: string
  vpc: { label: string; configured: boolean }
  firewall: { label: string; configured: boolean; rules: FirewallRule[] }
  nodebalancer: { configured: boolean }
  tiers: Record<string, TierInfo>
  nodes: TopologyNode[]
  edges: TopologyEdge[]
}

// Run events for live feed
export interface RunEvent {
  seq: number
  type: string
  at: string
  cardId?: string
  data?: Record<string, unknown>
}

export interface RunInfo {
  id: string
  label: string
  status: 'running' | 'awaiting_approval' | 'completed' | 'failed'
  createdAt: string
  pendingApproval: boolean
  cardIds: string[]
}

// Trust Center types
export interface CedarRule {
  id: string
  type: 'permit' | 'forbid'
  principal: string
  action: string | null
  resource: string | null
  description: string | null
}

export interface PolicyHoldReason {
  reason: string
  resolution: string
}

export interface SenderCheck {
  check: string
  description: string
}

export interface NotYetItem {
  item: string
  status: string
  description: string
}

export interface TrustData {
  generated_at: string
  version: string
  security_controls: {
    policy_engine: {
      type: string
      description: string
      total_rules: number
      rules: CedarRule[]
    }
    owner_approval_required: {
      description: string
      owner_permitted_actions: { rule_id: string; action: string | null; description: string | null }[]
    }
    model_restrictions: {
      description: string
      model_rules: CedarRule[]
      permitted_actions: string[]
      forbidden_actions: string[]
    }
    kickback_email_controls: {
      description: string
      rules: string[]
    }
    prompt_injection_defenses: {
      description: string
      hold_reason: string
    }
    redteam_suite: {
      description: string
      total_cases: number
      blocked_cases?: number | null
      all_blocked?: boolean | null
      ran_at?: string | null
      categories: string[]
      endpoint: string
    }
    sender_verification: {
      description: string
      checks: SenderCheck[]
    }
    pydantic_validation: {
      description: string
      validation_on: string[]
    }
    policy_hold_reasons: {
      description: string
      reasons: PolicyHoldReason[]
    }
  }
  data_handling: {
    storage: {
      database: { type: string; location: string; description: string }
      object_storage: { configured: boolean; region: string; description: string }
    }
    network_isolation: {
      vpc_private: Record<string, string>
      firewall: { default_deny_inbound: boolean; allowed_inbound: string[]; description: string }
    }
    llm_data_handling: {
      deterministic_path: { description: string; decider_active: boolean; llm_mode: string }
      hosted_inference: { provider: string; base_url: string; description: string }
    }
    demo_data: { description: string; synthetic_vendors: boolean; synthetic_invoices: boolean }
  }
  infrastructure: {
    deployment: { provider: string; region: string; products: string[] }
    settlement: { adapter: string; network: string; description: string }
    model: { name: string; scorer: string; description: string }
  }
  not_yet_implemented: {
    description: string
    items: NotYetItem[]
  }
}

export interface VouchApi {
  readonly mode: 'mock' | 'live'
  listPayments(): Promise<Payment[]>
  getPayment(id: string): Promise<Payment>
  approvePayment(id: string, note?: string): Promise<Payment>
  holdPayment(id: string, note?: string): Promise<Payment>
  appealPayment(id: string, note?: string): Promise<Payment>
  settleBatch(paymentIds: string[], funding: FundingChoice): Promise<SettlementReceipt>
  getNetwork(): Promise<NetworkStatus>
  getRedTeam(): Promise<RedTeamReport>
  getHealth(): Promise<HealthStatus>
  getInfo(): Promise<ApiInfo>
  getLatency(): Promise<LatencyStats>
  getTopology(): Promise<TopologyData>
  getTrust(): Promise<TrustData>
  listRuns(): Promise<RunInfo[]>
  getRunEvents(runId: string, after?: number): Promise<{ status: string; events: RunEvent[] }>
}
