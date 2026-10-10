export interface AgentStep {
  id: string
  title: string
  detail: string
  /** Simulated duration in ms for the activity animation. */
  durationMs: number
  /** Whether this step uses the private model (vs deterministic code). */
  usesModel: boolean
}

export const AGENT_STEPS: AgentStep[] = [
  { id: 'read', title: 'Read invoice', detail: 'Extracted vendor, amount, due date, bank details', durationMs: 900, usesModel: true },
  { id: 'screen', title: 'Screen vendor', detail: 'Matched against your vendor list and history', durationMs: 700, usesModel: false },
  { id: 'check-bank', title: 'Check 1 · Bank details', detail: 'Compared account with the one on file', durationMs: 600, usesModel: false },
  { id: 'check-dup', title: 'Check 2 · Duplicates and splits', detail: 'Looked for repeated or split invoices', durationMs: 800, usesModel: false },
  { id: 'check-ring', title: 'Check 3 · Vendor network', detail: 'Looked for shared bank accounts, phones, addresses', durationMs: 1000, usesModel: false },
  { id: 'score', title: 'Score', detail: 'Combined the evidence into a trust meter', durationMs: 500, usesModel: false },
  { id: 'policy', title: 'Policy', detail: 'No fees, no rounding, no unverified bank changes', durationMs: 400, usesModel: false },
  { id: 'ready', title: 'Ready for approval', detail: 'Written up in plain English for you', durationMs: 700, usesModel: true },
]
