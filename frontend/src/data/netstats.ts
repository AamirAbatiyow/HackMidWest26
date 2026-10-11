import type { LatencyStats, TopologyData } from '@/api/types'

/** True once at least one run has been timed; before that the page shows a prompt instead of dashes. */
export function hasTimings(latency: LatencyStats): boolean {
  const counts = [
    ...Object.values(latency.pipelineSteps).map((s) => s.count),
    ...Object.values(latency.inference).map((s) => s.count),
    latency.decider.count,
  ]
  return counts.some((n) => n > 0)
}

/** The ten backend timers folded into the five steps an owner recognises. */
export const STEP_GROUPS: { step: string; members: string[] }[] = [
  { step: 'read', members: ['reader', 'sender_check', 'vendor_resolution'] },
  { step: 'checks', members: ['detector_amount', 'detector_bank', 'detector_duplicate', 'detector_ring'] },
  { step: 'score', members: ['scorer'] },
  { step: 'policy', members: ['policy'] },
  { step: 'write', members: ['writer'] },
]

/**
 * Compact per-step waterfall: the latest run when the backend has one, otherwise rolling p50s.
 * Groups with no sample are dropped rather than drawn as a dash.
 */
export function compactWaterfall(latency: LatencyStats): { runId: string | null; steps: { step: string; latencyMs: number }[] } {
  const latest = new Map(latency.lastRunWaterfall?.steps.map((s) => [s.step, s.latencyMs]) ?? [])
  const useLatest = [...latest.values()].some((v) => v != null)
  const source = (name: string): number | null => (useLatest ? (latest.get(name) ?? null) : (latency.pipelineSteps[name]?.p50Ms ?? null))
  const steps: { step: string; latencyMs: number }[] = []
  for (const g of STEP_GROUPS) {
    const samples = g.members.map(source).filter((v): v is number => v != null)
    if (samples.length > 0) steps.push({ step: g.step, latencyMs: samples.reduce((a, b) => a + b, 0) })
  }
  return { runId: useLatest ? (latency.lastRunWaterfall?.runId ?? null) : null, steps }
}

export const EMPTY_TIMINGS_TITLE = 'Send an invoice to see live timings'
export const EMPTY_TIMINGS_DESCRIPTION = 'No runs yet. Per-step, inference, Postgres, Object Storage and Decider timings appear here after the first invoice is processed.'

/** Running cost of the stack, set against one median small-business fraud case. */
export const COST_LINE = {
  before: 'The full Vouch stack runs for about $186/month ($2,232/year). A single median fraud case at organizations with fewer than 100 employees costs $141,000 (',
  linkText: 'ACFE 2024',
  linkHref: 'https://www.acfe.com/-/media/files/acfe/pdfs/rttn/2024/2024-report-to-the-nations.pdf',
  after: '). Stopping one case pays for more than 60 years of running Vouch ($141,000 ÷ $2,232 ≈ 63).',
} as const

export const DEMO_LATENCY: LatencyStats = {
  updatedAt: new Date().toISOString(),
  region: 'us-ord (Chicago)',
  pipelineSteps: {
    reader: { p50Ms: 12, p95Ms: 28, count: 156, latestMs: 14 },
    sender_check: { p50Ms: 8, p95Ms: 19, count: 156, latestMs: 7 },
    vendor_resolution: { p50Ms: 15, p95Ms: 42, count: 156, latestMs: 18 },
    detector_amount: { p50Ms: 2, p95Ms: 5, count: 156, latestMs: 2 },
    detector_bank: { p50Ms: 3, p95Ms: 8, count: 156, latestMs: 4 },
    detector_duplicate: { p50Ms: 6, p95Ms: 14, count: 156, latestMs: 5 },
    detector_ring: { p50Ms: 18, p95Ms: 45, count: 156, latestMs: 22 },
    scorer: { p50Ms: 85, p95Ms: 210, count: 156, latestMs: 92 },
    policy: { p50Ms: 4, p95Ms: 9, count: 156, latestMs: 3 },
    writer: { p50Ms: 11, p95Ms: 26, count: 156, latestMs: 13 },
  },
  inference: {
    'hackathon-chat': {
      model: 'hackathon-chat',
      baseUrl: 'https://ws.akamai-workshops.com/v1',
      live: true,
      p50Ms: 320,
      p95Ms: 890,
      count: 48,
      latestMs: 345,
    },
    'hackathon-embedding': {
      model: 'hackathon-embedding',
      baseUrl: 'https://ws.akamai-workshops.com/v1',
      live: true,
      p50Ms: 45,
      p95Ms: 120,
      count: 312,
      latestMs: 52,
    },
  },
  decider: {
    engine: 'local-torch',
    enginesAvailable: ['local-torch', 'inference-service', 'heuristic-fallback'],
    p50Ms: 85,
    p95Ms: 210,
    count: 156,
    latestMs: 92,
  },
  postgres: {
    configured: true,
    ok: true,
    latencyMs: 3,
    p50Ms: 2,
    p95Ms: 6,
  },
  objectStorage: {
    configured: true,
    ok: true,
    latencyMs: 18,
    p50Ms: 15,
    p95Ms: 42,
  },
  tiers: {
    ingress: {
      name: 'Ingress Tier',
      subnet: '10.0.1.0/24',
      products: ['Akamai NodeBalancer', 'Akamai Cloud Firewall'],
      description: 'TLS termination and DDoS protection',
      configured: true,
      healthy: true,
      rttMs: 3,
    },
    app: {
      name: 'Application Tier',
      subnet: '10.0.2.0/24',
      products: ['Dedicated-CPU Linode', 'Akamai VPC'],
      description: 'Vouch API servers',
      configured: true,
      healthy: true,
      rttMs: null,
    },
    model: {
      name: 'Model Tier',
      subnet: '10.0.3.0/24',
      products: ['Dedicated-CPU Linode', 'Akamai Cloud Inference'],
      description: 'Private model server and hosted inference',
      configured: true,
      healthy: null,
      rttMs: 85,
    },
    data: {
      name: 'Data Tier',
      subnet: '10.0.4.0/24',
      products: ['Akamai Managed Postgres (pgvector)', 'Akamai Object Storage'],
      description: 'Persistent storage for audit trail and attachments',
      configured: true,
      healthy: true,
      rttMs: 2,
    },
  },
  lastRunWaterfall: {
    runId: 'run-demo-001',
    steps: [
      { step: 'reader', latencyMs: 14 },
      { step: 'sender_check', latencyMs: 7 },
      { step: 'vendor_resolution', latencyMs: 18 },
      { step: 'detector_amount', latencyMs: 2 },
      { step: 'detector_bank', latencyMs: 4 },
      { step: 'detector_duplicate', latencyMs: 5 },
      { step: 'detector_ring', latencyMs: 22 },
      { step: 'scorer', latencyMs: 92 },
      { step: 'policy', latencyMs: 3 },
      { step: 'writer', latencyMs: 13 },
    ],
  },
}

export const DEMO_TOPOLOGY: TopologyData = {
  updatedAt: new Date().toISOString(),
  region: 'us-ord (Chicago)',
  vpc: {
    label: 'vouch-vpc-ord',
    configured: true,
  },
  firewall: {
    label: 'vouch-fw-ord',
    configured: true,
    rules: [
      { id: 'fw-1', direction: 'inbound', protocol: 'TCP', ports: '443', source: '0.0.0.0/0', action: 'ACCEPT', label: 'HTTPS from internet' },
      { id: 'fw-2', direction: 'inbound', protocol: 'TCP', ports: '80', source: '0.0.0.0/0', action: 'ACCEPT', label: 'HTTP redirect' },
      { id: 'fw-3', direction: 'inbound', protocol: 'TCP', ports: '22', source: '10.0.0.0/8', action: 'ACCEPT', label: 'SSH from VPC' },
      { id: 'fw-4', direction: 'outbound', protocol: 'TCP', ports: '5432', destination: '10.0.4.0/24', action: 'ACCEPT', label: 'Postgres' },
      { id: 'fw-5', direction: 'outbound', protocol: 'TCP', ports: '443', destination: '*.akamai-workshops.com', action: 'ACCEPT', label: 'Hosted inference' },
      { id: 'fw-6', direction: 'inbound', protocol: '*', ports: '*', source: '0.0.0.0/0', action: 'DROP', label: 'Default deny' },
    ],
  },
  nodebalancer: {
    configured: true,
  },
  tiers: {
    ingress: {
      name: 'Ingress Tier',
      subnet: '10.0.1.0/24',
      products: ['Akamai NodeBalancer', 'Akamai Cloud Firewall'],
      description: 'TLS termination and DDoS protection',
    },
    app: {
      name: 'Application Tier',
      subnet: '10.0.2.0/24',
      products: ['Dedicated-CPU Linode', 'Akamai VPC'],
      description: 'Vouch API servers',
    },
    model: {
      name: 'Model Tier',
      subnet: '10.0.3.0/24',
      products: ['Dedicated-CPU Linode', 'Akamai Cloud Inference'],
      description: 'Private model server and hosted inference',
    },
    data: {
      name: 'Data Tier',
      subnet: '10.0.4.0/24',
      products: ['Akamai Managed Postgres (pgvector)', 'Akamai Object Storage'],
      description: 'Persistent storage for audit trail and attachments',
    },
  },
  nodes: [
    { id: 'internet', label: 'Internet', tier: null, product: null, x: 50, y: 100, configured: true },
    { id: 'nodebalancer', label: 'NodeBalancer', tier: 'ingress', product: 'Akamai NodeBalancer', x: 200, y: 100, configured: true },
    { id: 'firewall', label: 'Cloud Firewall', tier: 'ingress', product: 'Akamai Cloud Firewall', x: 350, y: 100, configured: true },
    { id: 'api', label: 'Vouch API', tier: 'app', product: 'Dedicated-CPU Linode', x: 500, y: 100, configured: true },
    { id: 'model_server', label: 'Model Server', tier: 'model', product: 'Dedicated-CPU Linode', x: 650, y: 50, configured: true },
    { id: 'inference', label: 'Hosted Inference', tier: 'model', product: 'Akamai Cloud Inference', x: 650, y: 150, configured: true },
    { id: 'postgres', label: 'Managed Postgres', tier: 'data', product: 'Akamai Managed Database', x: 800, y: 50, configured: true },
    { id: 'object_storage', label: 'Object Storage', tier: 'data', product: 'Akamai Object Storage', x: 800, y: 150, configured: true },
  ],
  edges: [
    { id: 'e1', from: 'internet', to: 'nodebalancer', label: 'TLS 1.3', private: false },
    { id: 'e2', from: 'nodebalancer', to: 'firewall', label: '', private: true },
    { id: 'e3', from: 'firewall', to: 'api', label: '', private: true },
    { id: 'e4', from: 'api', to: 'model_server', label: 'gRPC', private: true },
    { id: 'e5', from: 'api', to: 'inference', label: 'HTTPS', private: false },
    { id: 'e6', from: 'api', to: 'postgres', label: 'pgvector', private: true },
    { id: 'e7', from: 'api', to: 'object_storage', label: 'S3 API', private: true },
  ],
}
