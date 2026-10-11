import type { OrchestratorStep, StepKind, StepScope, StepStatus } from '@/api/types'

/**
 * Mock orchestrator timelines. Mirrors the backend `steps[]` shape (vouch/steps.py): one entry per step
 * the graph ran for an invoice, naming the tool or model, whether it was code / LLM / model / owner, the
 * per-invoice duration and a one-line result. Live mode replaces all of this with real run data.
 */

type Partial = {
  ms?: number | null
  scope?: StepScope
  detail?: string[]
  at?: string
} & Pick<OrchestratorStep, 'engine' | 'confidence' | 'modelCalls' | 'llmCalls' | 'tokens' | 'lane' | 'match' | 'flags' | 'txId' | 'explorerUrl'>

const LABELS: Record<string, string> = {
  intake: 'Intake',
  format: 'Format',
  read: 'Read',
  screen: 'Screen',
  check: 'Check',
  score: 'Score',
  investigate: 'Investigate',
  policy: 'Policy',
  writer: 'Writer',
  approval: 'Owner approval',
  settlement: 'Settlement',
}

const NODES: Record<string, string> = {
  format: 'intake',
  read: 'intake',
  screen: 'resolve',
  check: 'kernel',
  score: 'score',
  investigate: 'investigate',
  policy: 'policy',
  writer: 'explain',
  settlement: 'settle',
}

function step(id: string, tool: string, kind: StepKind, status: StepStatus, summary: string, extra: Partial = {}): OrchestratorStep {
  const { ms = null, scope, detail = [], at, ...rest } = extra
  return {
    id,
    seq: 0,
    label: LABELS[id] ?? id,
    tool,
    kind,
    node: NODES[id],
    durationMs: ms,
    durationScope: ms == null ? null : (scope ?? 'card'),
    status,
    summary,
    detail,
    at,
    ...rest,
  }
}

function sequence(steps: OrchestratorStep[]): OrchestratorStep[] {
  return steps.map((s, i) => ({ ...s, seq: i + 1 }))
}

const KERNEL = 'kernel regex parser (plain code)'
const PDF = `PDF text parser (pypdf + pdfplumber) + ${KERNEL}`
const XLSX = `Excel parser (openpyxl) + ${KERNEL}`
const RESOLVER = 'vendor resolver (tax id, domain, fuzzy name, bank account)'
const CHECKS = 'sender check · amount kernel · bank change · duplicate / split · ring graph (plain code)'
const VOUCHNET = 'VouchNet (PyTorch, inference service) v20261010-210128'
const CEDAR = 'Cedar default-deny (cedarpy)'
const EXPLAINER = 'explainer agent (hackathon-chat; provenance-checked)'
const ROUTE = 'deterministic route (MIME type / extension / magic bytes)'
const OWNER = 'owner (human in the loop)'

const routeDetail = (fmt: string, tool: string, extractor: string) => [
  'engine deterministic · INTAKE_CLASSIFIER=auto (the Decider is only asked when the route is ambiguous)',
  `extractor used: ${extractor}`,
  'decided before extraction; the tool decision chose the extractor',
  `format: ${fmt} (deterministic)`,
  `tool: ${tool} (deterministic)`,
]

const cedarDetail = (reasons: string[], hold = false) => [
  ...reasons.map((r) => `reason: ${r}`),
  'System hold → P-03',
  'Model settle → DEFAULT-DENY · Model approve → DEFAULT-DENY',
  ...(hold ? ['re-evaluated 1x (owner actions re-run the policy)'] : []),
]

const policySummary = (lane: string, reason?: string) =>
  `lane ${lane}${reason ? ` · ${reason}` : ''} · hold permitted for the system · approve/settle denied for the agent`

/** Per-invoice mock timelines, keyed by demo payment id. */
export const DEMO_STEPS: Record<string, OrchestratorStep[]> = {
  'pay-001': sequence([
    step('intake', 'email intake (IMAP / .eml)', 'deterministic', 'ok', 'email received, 1 file', {
      detail: ['files: RP-10482.pdf', 'from: ar@reyespackaging.mx', 'submitted by ap-inbox'],
    }),
    step('format', ROUTE, 'deterministic', 'ok', 'pdf_attachment → pdf_text · confidence 1.00 · 0 model calls · route was obvious, so no model was asked', {
      ms: 0.4,
      engine: 'deterministic',
      confidence: 1,
      modelCalls: 0,
      tokens: 0,
      detail: routeDetail('pdf_attachment', 'pdf_text', 'pypdf+pdfplumber'),
    }),
    step('read', PDF, 'deterministic', 'ok', '$6,400.00 · Reyes Packaging · RP-10482', {
      ms: 38,
      llmCalls: 0,
      detail: ['amount origin: source', 'PO 7731', 'bank on invoice ****2210', '0 LLM calls in this step'],
    }),
    step('screen', RESOLVER, 'deterministic', 'ok', 'known vendor Reyes Packaging · resolved by tax id, domain · confidence 0.99', {
      ms: 1.2,
      match: 'known',
      confidence: 0.99,
    }),
    step('check', CHECKS, 'deterministic', 'ok', 'clean · 5 checks passed', {
      ms: 1.8,
      flags: [],
      detail: ['sender: SPF/DKIM/DMARC pass', 'amount: 1.0x the usual $6,150.00 over 41 payments', 'bank: matches the master file', 'duplicate / split: none', 'ring: no shared bank, phone or address'],
    }),
    step('score', VOUCHNET, 'model', 'ok', 'honest 0.97 · legitimacy 98% · LIME: same bank account since Feb 2023', {
      ms: 212,
      scope: 'run',
      detail: ['honest 0.97 · ato_bec 0.01 · insider 0.01 · fake_vendor 0.01', 'anomaly percentile 12%', 'LIME 1: same bank account since Feb 2023', 'LIME 2: amount matches PO #7731 exactly', 'scored in one batch of 8 card(s)'],
    }),
    step('policy', CEDAR, 'deterministic', 'ok', policySummary('fast pay'), { ms: 0.6, lane: 'fast_pay', detail: cedarDetail(['verified vendor under the fast-pay limit']) }),
    step('writer', EXPLAINER, 'llm', 'ok', 'Same bank account for 3 years. Amount matches the purchase order.', {
      ms: 1340,
      scope: 'run',
      llmCalls: 1,
      tokens: 412,
      detail: ['source: llm', 'every amount in the text was found in the kernel fact sheet'],
    }),
    step('approval', OWNER, 'human', 'pending', 'waiting for the owner · graph paused at the approval interrupt'),
  ]),
  'pay-002': sequence([
    step('intake', 'email intake (IMAP / .eml)', 'deterministic', 'ok', 'email received, 1 file', {
      detail: ['files: WS-2026-0917.pdf', 'from: finance.ws@warsawsteel-eu.com', 'submitted by ap-inbox'],
    }),
    step('format', ROUTE, 'deterministic', 'ok', 'pdf_attachment → pdf_text · confidence 1.00 · 0 model calls · route was obvious, so no model was asked', {
      ms: 0.3,
      engine: 'deterministic',
      confidence: 1,
      modelCalls: 0,
      detail: routeDetail('pdf_attachment', 'pdf_text', 'pypdf+pdfplumber'),
    }),
    step('read', PDF, 'deterministic', 'ok', '$12,000.00 · Warsaw Steel Sp. z o.o. · WS-2026-0917', {
      ms: 44,
      llmCalls: 0,
      detail: ['amount origin: source', 'bank on invoice ****8812 (new)', '0 LLM calls in this step'],
    }),
    step('screen', RESOLVER, 'deterministic', 'ok', 'known vendor Warsaw Steel Sp. z o.o. · resolved by tax id · confidence 0.98', { ms: 0.9, match: 'known', confidence: 0.98 }),
    step('check', CHECKS, 'deterministic', 'flagged', 'bank details on invoice differ from vendor master · flagged · 2 more', {
      ms: 2.1,
      flags: ['sender: new sender for known vendor', 'bank details on invoice differ from vendor master', 'vendor bank details changed recently without out-of-band confirmation'],
      detail: ['sender: SPF/DKIM/DMARC pass · new_sender_for_known_vendor', 'amount: 1.0x the usual $11,850.00 over 58 payments', 'bank: account on the invoice differs from the master file', 'duplicate / split: none', 'ring: no shared bank, phone or address'],
    }),
    step('score', VOUCHNET, 'model', 'flagged', 'ato_bec 0.81 · legitimacy 22% · LIME: bank account changed 2 days ago', {
      ms: 212,
      scope: 'run',
      detail: ['ato_bec 0.81 · honest 0.15 · insider 0.03 · fake_vendor 0.01', 'anomaly percentile 71%', 'LIME 1: bank account changed 2 days ago', 'LIME 2: change request came from a new email address', 'scored in one batch of 8 card(s)'],
    }),
    step('investigate', 'ato_bec investigator agent (hackathon-chat)', 'llm', 'flagged', 'Bank details changed two days ago from a new sender; the new account is in a different country.', {
      ms: 2210,
      llmCalls: 1,
      tokens: 1180,
      detail: ['recommended action: verify bank by callback', 'Call Marta Kowalski at the number on file: did you change your bank details?'],
    }),
    step('policy', CEDAR, 'deterministic', 'hold', policySummary('hold', 'bank details changed without out-of-band confirmation'), {
      ms: 0.5,
      lane: 'hold',
      detail: cedarDetail(['bank details changed without out-of-band confirmation'], true),
    }),
    step('writer', EXPLAINER, 'llm', 'ok', 'Bank details changed 2 days ago. A quick call to your usual contact clears this.', { ms: 1340, scope: 'run', llmCalls: 1, tokens: 388, detail: ['source: llm'] }),
    step('approval', OWNER, 'human', 'hold', 'waiting: on hold until confirm the new account by calling the number on file'),
  ]),
  'pay-003': sequence([
    step('intake', 'email intake (IMAP / .eml)', 'deterministic', 'ok', 'email received, 1 file', { detail: ['files: MP-5521.pdf', 'from: billing@midwestpallets.com'] }),
    step('format', ROUTE, 'deterministic', 'ok', 'pdf_attachment → pdf_text · confidence 1.00 · 0 model calls · route was obvious, so no model was asked', {
      ms: 0.3,
      engine: 'deterministic',
      confidence: 1,
      modelCalls: 0,
      detail: routeDetail('pdf_attachment', 'pdf_text', 'pypdf+pdfplumber'),
    }),
    step('read', PDF, 'deterministic', 'ok', '$4,950.00 · Midwest Pallets · MP-5521', { ms: 31, llmCalls: 0, detail: ['amount origin: source', '0 LLM calls in this step'] }),
    step('screen', RESOLVER, 'deterministic', 'ok', 'known vendor Midwest Pallets · resolved by tax id, bank account · confidence 1.00', { ms: 0.8, match: 'known', confidence: 1 }),
    step('check', CHECKS, 'deterministic', 'ok', 'clean · 5 checks passed', { ms: 1.4, flags: [], detail: ['sender: SPF/DKIM/DMARC pass', 'amount: 1.0x the usual $4,950.00 over 73 payments', 'bank: matches the master file', 'duplicate / split: none', 'ring: no shared bank, phone or address'] }),
    step('score', VOUCHNET, 'model', 'ok', 'honest 0.98 · legitimacy 99% · LIME: matches the usual monthly amount', { ms: 212, scope: 'run', detail: ['honest 0.98 · insider 0.01 · ato_bec 0.01 · fake_vendor 0.00', 'anomaly percentile 8%', 'scored in one batch of 8 card(s)'] }),
    step('policy', CEDAR, 'deterministic', 'ok', policySummary('standard'), { ms: 0.4, lane: 'standard', detail: cedarDetail(['all checks passed; owner approval required']) }),
    step('writer', EXPLAINER, 'llm', 'ok', 'Regular monthly pallet order. Everything matches.', { ms: 1340, scope: 'run', llmCalls: 1, tokens: 300, detail: ['source: llm'] }),
    step('approval', OWNER, 'human', 'pending', 'waiting for the owner · graph paused at the approval interrupt'),
  ]),
  'pay-004': sequence([
    step('intake', 'email intake (IMAP / .eml)', 'deterministic', 'ok', 'email received, 1 file', { detail: ['files: MP-5521.pdf (same sha256 as the first copy)', 'from: billing@midwestpallets.com'] }),
    step('format', ROUTE, 'deterministic', 'ok', 'pdf_attachment → pdf_text · confidence 1.00 · 0 model calls · route was obvious, so no model was asked', {
      ms: 0.3,
      engine: 'deterministic',
      confidence: 1,
      modelCalls: 0,
      detail: routeDetail('pdf_attachment', 'pdf_text', 'pypdf+pdfplumber'),
    }),
    step('read', PDF, 'deterministic', 'ok', '$4,950.00 · Midwest Pallets · MP-5521', { ms: 29, llmCalls: 0, detail: ['amount origin: source', '0 LLM calls in this step'] }),
    step('screen', RESOLVER, 'deterministic', 'ok', 'known vendor Midwest Pallets · resolved by tax id, bank account · confidence 1.00', { ms: 0.7, match: 'known', confidence: 1 }),
    step('check', CHECKS, 'deterministic', 'flagged', 'possible duplicate of invoice MP-5521 in this batch · flagged', {
      ms: 1.6,
      flags: ['possible duplicate of invoice MP-5521 in this batch'],
      detail: ['sender: SPF/DKIM/DMARC pass', 'amount: 1.0x the usual $4,950.00 over 73 payments', 'bank: matches the master file', 'duplicate: invoice MP-5521 in this batch, 40 minutes earlier', 'ring: no shared bank, phone or address'],
    }),
    step('score', VOUCHNET, 'model', 'flagged', 'insider 0.62 · legitimacy 41% · LIME: same invoice number as MP-5521 above', { ms: 212, scope: 'run', detail: ['insider 0.62 · honest 0.36 · ato_bec 0.01 · fake_vendor 0.01', 'anomaly percentile 55%', 'scored in one batch of 8 card(s)'] }),
    step('investigate', 'insider template', 'deterministic', 'flagged', 'Possible duplicate of invoice MP-5521 in this batch.', {
      ms: 0.2,
      detail: ['recommended action: confirm not duplicate', 'Is this a separate purchase from the earlier invoice? Please send the PO and delivery note.'],
    }),
    step('policy', CEDAR, 'deterministic', 'hold', policySummary('hold', 'possible duplicate invoice'), { ms: 0.4, lane: 'hold', detail: cedarDetail(['possible duplicate invoice'], true) }),
    step('writer', EXPLAINER, 'llm', 'ok', 'Same invoice number and amount as one already in this batch. Likely sent twice.', { ms: 1340, scope: 'run', llmCalls: 1, tokens: 352, detail: ['source: llm'] }),
    step('approval', OWNER, 'human', 'hold', 'waiting: on hold until owner confirms this is not a duplicate payment'),
  ]),
  'pay-005': sequence([
    step('intake', 'email intake (IMAP / .eml)', 'deterministic', 'ok', 'email received, 1 file', { detail: ['files: BL-3307.pdf', 'from: ap@brightlinesupply.com'] }),
    step('format', ROUTE, 'deterministic', 'ok', 'pdf_attachment → pdf_text · confidence 1.00 · 0 model calls · route was obvious, so no model was asked', {
      ms: 0.3,
      engine: 'deterministic',
      confidence: 1,
      modelCalls: 0,
      detail: routeDetail('pdf_attachment', 'pdf_text', 'pypdf+pdfplumber'),
    }),
    step('read', PDF, 'deterministic', 'ok', '$4,900.00 · Brightline Supply · BL-3307', { ms: 35, llmCalls: 0, detail: ['amount origin: source', '0 LLM calls in this step'] }),
    step('screen', RESOLVER, 'deterministic', 'ok', 'known vendor Brightline Supply · resolved by domain, bank account · confidence 0.97', { ms: 0.9, match: 'known', confidence: 0.97 }),
    step('check', CHECKS, 'deterministic', 'flagged', 'possible split invoices under the approval limit · flagged', {
      ms: 1.9,
      flags: ['possible split invoices under the approval limit'],
      detail: ['sender: SPF/DKIM/DMARC pass', 'amount: 0.5x the usual $9,500.00 over 9 payments · just under the approval limit', 'bank: matches the master file', 'split: 2 invoices total $9,800.00', 'ring: no shared bank, phone or address'],
    }),
    step('score', VOUCHNET, 'model', 'flagged', 'insider 0.58 · legitimacy 44% · LIME: two invoices sent 4 minutes apart', { ms: 212, scope: 'run', detail: ['insider 0.58 · honest 0.39 · fake_vendor 0.02 · ato_bec 0.01', 'anomaly percentile 63%', 'scored in one batch of 8 card(s)'] }),
    step('investigate', 'insider investigator agent (hackathon-chat)', 'llm', 'flagged', 'Two invoices of $4,900 four minutes apart, each just under the $5,000 approval limit; usual order is about $9,500.', {
      ms: 1980,
      llmCalls: 1,
      tokens: 1044,
      detail: ['recommended action: request po and delivery', 'Was this one order split in two? Please send the PO.'],
    }),
    step('policy', CEDAR, 'deterministic', 'hold', policySummary('hold', 'possible split invoices under the approval limit'), { ms: 0.4, lane: 'hold', detail: cedarDetail(['possible split invoices under the approval limit'], true) }),
    step('writer', EXPLAINER, 'llm', 'ok', 'One of two invoices just under your $5,000 approval limit, sent 4 minutes apart.', { ms: 1340, scope: 'run', llmCalls: 1, tokens: 360, detail: ['source: llm'] }),
    step('approval', OWNER, 'human', 'hold', 'waiting: on hold until owner confirms the invoices are separate purchases'),
  ]),
  'pay-006': sequence([
    step('intake', 'email intake (IMAP / .eml)', 'deterministic', 'ok', 'email received, 1 file', { detail: ['files: BL-3308.pdf', 'from: ap@brightlinesupply.com'] }),
    step('format', ROUTE, 'deterministic', 'ok', 'pdf_attachment → pdf_text · confidence 1.00 · 0 model calls · route was obvious, so no model was asked', {
      ms: 0.3,
      engine: 'deterministic',
      confidence: 1,
      modelCalls: 0,
      detail: routeDetail('pdf_attachment', 'pdf_text', 'pypdf+pdfplumber'),
    }),
    step('read', PDF, 'deterministic', 'ok', '$4,900.00 · Brightline Supply · BL-3308', { ms: 33, llmCalls: 0, detail: ['amount origin: source', '0 LLM calls in this step'] }),
    step('screen', RESOLVER, 'deterministic', 'ok', 'known vendor Brightline Supply · resolved by domain, bank account · confidence 0.97', { ms: 0.8, match: 'known', confidence: 0.97 }),
    step('check', CHECKS, 'deterministic', 'flagged', 'possible split invoices under the approval limit · flagged', {
      ms: 1.7,
      flags: ['possible split invoices under the approval limit'],
      detail: ['sender: SPF/DKIM/DMARC pass', 'amount: 0.5x the usual $9,500.00 over 9 payments · just under the approval limit', 'bank: matches the master file', 'split: 2 invoices total $9,800.00', 'ring: no shared bank, phone or address'],
    }),
    step('score', VOUCHNET, 'model', 'flagged', 'insider 0.57 · legitimacy 45% · LIME: pairs with BL-3307', { ms: 212, scope: 'run', detail: ['insider 0.57 · honest 0.40 · fake_vendor 0.02 · ato_bec 0.01', 'anomaly percentile 61%', 'scored in one batch of 8 card(s)'] }),
    step('investigate', 'insider template', 'deterministic', 'flagged', 'Possible split invoices under the approval limit.', { ms: 0.2, detail: ['recommended action: request po and delivery'] }),
    step('policy', CEDAR, 'deterministic', 'hold', policySummary('hold', 'possible split invoices under the approval limit'), { ms: 0.4, lane: 'hold', detail: cedarDetail(['possible split invoices under the approval limit'], true) }),
    step('writer', EXPLAINER, 'llm', 'ok', 'Second of two invoices just under your $5,000 approval limit.', { ms: 1340, scope: 'run', llmCalls: 1, tokens: 290, detail: ['source: llm'] }),
    step('approval', OWNER, 'human', 'hold', 'waiting: on hold until review together with BL-3307'),
  ]),
  'pay-007': sequence([
    step('intake', 'file upload', 'deterministic', 'ok', 'upload received, 2 files', { detail: ['files: NT-0001.xlsx, terms.pdf', 'submitted by ap-clerk'] }),
    step('format', 'Strands Decider 2B (strands-decider-2b)', 'model', 'ok', 'excel_attachment → excel_reader · confidence 0.87 · 2 model calls, 212 ms, 96 tokens', {
      ms: 212,
      engine: 'decider',
      confidence: 0.87,
      modelCalls: 2,
      tokens: 96,
      detail: [
        'engine decider · INTAKE_CLASSIFIER=auto (the Decider is only asked when the route is ambiguous)',
        'ambiguous: multiple_candidates (PDF and Excel attachments; which one is the invoice?)',
        'deterministic route was pdf_attachment → pdf_text',
        'extractor used: openpyxl',
        'decided before extraction; the tool decision chose the extractor',
        'format: excel_attachment (decider, 104 ms, 0.87)',
        'tool: excel_reader (decider, 108 ms, 0.91)',
      ],
    }),
    step('read', XLSX, 'deterministic', 'ok', '$7,200.00 · Nova Trade LLC · NT-0001', { ms: 52, llmCalls: 0, detail: ['amount origin: source', 'no purchase order', 'bank on invoice ****4471', '0 LLM calls in this step'] }),
    step('screen', 'vendor resolver + pgvector / hackathon-embedding re-rank', 'model', 'flagged', 'Nova Trade LLC: not on the master file (new vendor)', {
      ms: 61,
      match: 'new',
      confidence: 0.31,
      detail: ['candidate Nova Trading Co. · name embedding 0.31', 'no tax id, domain or bank account match'],
    }),
    step('check', CHECKS, 'deterministic', 'flagged', 'bank shared by 3 vendors · flagged · 2 more', {
      ms: 2.4,
      flags: ['bank shared by 3 vendors', 'phone shared by 2 vendors', 'no purchase order and no delivery confirmation'],
      detail: ['amount: no payment history to compare against', 'bank: no vendor on file', 'duplicate / split: none', 'ring: bank shared with 2 other vendor(s)', 'ring: phone shared with 1 other vendor(s)', 'ring: address shared with 1 other vendor(s)'],
    }),
    step('score', VOUCHNET, 'model', 'flagged', 'fake_vendor 0.99 · legitimacy 1% · LIME: bank account shared with other vendors', {
      ms: 212,
      scope: 'run',
      detail: ['fake_vendor 0.99 · insider 0.01 · ato_bec 0.00 · honest 0.00', 'anomaly percentile 97% · ring score 0.82', 'LIME 1: bank account shared with other vendors', 'LIME 2: same phone number as Apex Supply Co.', 'LIME 3: registered 6 days ago, first invoice', 'scored in one batch of 8 card(s)'],
    }),
    step('investigate', 'fake_vendor investigator agent (hackathon-chat)', 'llm', 'flagged', 'New vendor sharing a bank account with two other vendors and a phone with one; virtual-office address.', {
      ms: 2480,
      llmCalls: 1,
      tokens: 1312,
      detail: ['recommended action: verify identity', 'Please provide a W-9 and a bank letter on letterhead.'],
    }),
    step('policy', CEDAR, 'deterministic', 'hold', policySummary('hold', 'vendor shares bank account or tax id with other vendors'), {
      ms: 0.5,
      lane: 'hold',
      detail: cedarDetail(['vendor shares bank account or tax id with other vendors', 'vendor not on master file'], true),
    }),
    step('writer', EXPLAINER, 'llm', 'ok', 'New vendor whose bank account is also used by two other vendors. Worth a call before paying.', { ms: 1340, scope: 'run', llmCalls: 1, tokens: 402, detail: ['source: llm'] }),
    step('approval', OWNER, 'human', 'hold', 'waiting: on hold until verify vendor identity out-of-band (tax id match, call-back, onboarding documents)'),
  ]),
  'pay-008': sequence([
    step('intake', 'file upload', 'deterministic', 'ok', 'upload received, 1 file', { detail: ['files: CSR-0001.pdf', 'submitted by ap-clerk'] }),
    step('format', ROUTE, 'deterministic', 'ok', 'pdf_attachment → pdf_text · confidence 1.00 · 0 model calls · route was obvious, so no model was asked', {
      ms: 0.3,
      engine: 'deterministic',
      confidence: 1,
      modelCalls: 0,
      detail: routeDetail('pdf_attachment', 'pdf_text', 'pypdf+pdfplumber'),
    }),
    step('read', PDF, 'deterministic', 'ok', '$1,850.00 · Café Santa Rita · CSR-0001', { ms: 41, llmCalls: 0, detail: ['amount origin: source', '0 LLM calls in this step'] }),
    step('screen', RESOLVER, 'deterministic', 'ok', 'known vendor Café Santa Rita · resolved by tax id · confidence 0.98', { ms: 1.1, match: 'known', confidence: 0.98, detail: ['CNPJ registration matched the master file'] }),
    step('check', CHECKS, 'deterministic', 'ok', 'clean · 4 checks passed', { ms: 1.5, flags: [], detail: ['amount: no payment history to compare against', 'bank: matches the master file · confirmed out-of-band on day one', 'duplicate / split: none', 'ring: no shared bank, phone or address'] }),
    step('score', VOUCHNET, 'model', 'ok', 'honest 0.74 · legitimacy 72% · LIME: bank account verified by call-back', { ms: 212, scope: 'run', detail: ['honest 0.74 · fake_vendor 0.18 · insider 0.05 · ato_bec 0.03', 'anomaly percentile 44%', 'LIME 1: business registration matches the bank account name', 'LIME 2: no history yet', 'scored in one batch of 8 card(s)'] }),
    step('policy', CEDAR, 'deterministic', 'ok', policySummary('fast pay'), { ms: 0.5, lane: 'fast_pay', detail: cedarDetail(['verified new vendor under the fast-pay limit']) }),
    step('writer', EXPLAINER, 'llm', 'ok', 'New small vendor. Registration, bank name, and invoice all match. Good to pay today.', { ms: 1340, scope: 'run', llmCalls: 1, tokens: 376, detail: ['source: llm'] }),
    step('approval', OWNER, 'human', 'pending', 'waiting for the owner · graph paused at the approval interrupt'),
  ]),
}

export function demoSteps(paymentId: string): OrchestratorStep[] {
  return DEMO_STEPS[paymentId] ?? []
}

/** Owner approval recorded (mock approve / appeal). */
export function withApproval(steps: OrchestratorStep[], author: string, note?: string): OrchestratorStep[] {
  const line = `approved by ${author}${note ? ` · ${note}` : ''}`
  return steps.map((s) =>
    s.id === 'approval'
      ? { ...s, status: 'ok', summary: `approved by ${author}`, at: new Date().toISOString(), detail: [...s.detail, line] }
      : s.id === 'policy' && s.status === 'hold'
        ? { ...s, status: 'ok', summary: policySummary('standard'), lane: 'standard', detail: [...s.detail, `re-evaluated after ${author}'s action: hold resolved`] }
        : s,
  )
}

/** Owner hold recorded (mock hold). */
export function withHold(steps: OrchestratorStep[], author: string, note?: string): OrchestratorStep[] {
  const line = `held by ${author}${note ? ` · ${note}` : ''}`
  return steps.map((s) => (s.id === 'approval' ? { ...s, status: 'hold', summary: 'waiting: owner hold', at: new Date().toISOString(), detail: [...s.detail, line] } : s))
}

/** Settlement appended (mock batch settle). */
export function withSettlement(steps: OrchestratorStep[], amount: string, txId: string, explorerUrl: string, scheduled = false): OrchestratorStep[] {
  const base = steps.filter((s) => s.id !== 'settlement')
  const settlement = scheduled
    ? step('settlement', 'XRPL testnet (simulated)', 'deterministic', 'pending', 'scheduled for the next business day')
    : step('settlement', 'XRPL testnet (simulated)', 'deterministic', 'ok', `tx ${txId.slice(0, 12)}… · ${amount}`, {
        ms: 1480,
        scope: 'batch',
        txId,
        explorerUrl,
        at: new Date().toISOString(),
        detail: ['lane standard', `explorer ${explorerUrl}`],
      })
  return sequence([...base, settlement])
}
