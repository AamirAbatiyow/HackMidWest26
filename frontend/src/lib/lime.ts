import type { EvidenceFactor, LimeFactor, ModelExplanation, Payment } from '@/api/types'

/**
 * Plain-English labels for VouchNet's numeric features. Binary features get a
 * "yes" and a "no" phrasing; count features interpolate the value.
 */
const BINARY: Record<string, [yes: string, no: string]> = {
  new_vendor: ['Vendor added less than 60 days ago', 'Vendor on file for more than 60 days'],
  bank_mismatch: ['Invoice bank account differs from the master file', 'Invoice bank account matches the master file'],
  bank_change_unconfirmed: ['Bank change not confirmed by call-back', 'No unconfirmed bank change'],
  bank_change_confirmed: ['Bank change confirmed by call-back', 'No confirmed bank change'],
  contact_change_recent: ['Contact details changed recently', 'Contact details unchanged'],
  remit_email_mismatch: ['Remit email domain differs from the vendor on file', 'Remit email matches the vendor on file'],
  foreign_bank: ['Bank country differs from vendor country', 'Bank is in the vendor’s country'],
  injection_text: ['Text contains instructions aimed at the payment system', 'No instructions aimed at the system'],
  has_po: ['Purchase order on file', 'No purchase order'],
  delivery_confirmed: ['Delivery confirmed', 'Delivery not confirmed'],
  duplicate_suspect: ['Possible duplicate invoice', 'Not a duplicate'],
  split_suspect: ['Possible split invoice under the approval limit', 'Not a split invoice'],
  near_approval_limit: ['Amount just under the approval limit', 'Amount not near the approval limit'],
  round_amount: ['Round-thousand amount', 'Amount is not a round thousand'],
  line_items_mismatch: ['Line items don’t add up to the total', 'Line items add up'],
  tax_id_invalid: ['Tax ID fails checksum', 'Tax ID passes checksum'],
  phone_voip: ['VOIP / toll-free phone number', 'Phone is a regular landline or mobile'],
  address_virtual: ['Virtual office / PO box address', 'Street address on file'],
  free_email: ['Free webmail provider', 'Company email domain'],
  oob_verified: ['Identity verified out-of-band', 'Identity not verified out-of-band'],
}

const SHARED: Record<string, string> = {
  shared_bank: 'Bank account',
  shared_tax_id: 'Tax ID',
  shared_phone: 'Phone number',
  shared_address: 'Address',
  shared_email_domain: 'Email domain',
}

const OTHER: Record<string, string> = {
  amount_log: 'Invoice amount',
  amount_vs_history: 'Amount vs. this vendor’s usual',
  amount_creep: 'Amounts creeping up over time',
  vendor_age_log: 'Vendor age',
  history_count_log: 'Length of payment history',
  urgency_terms: 'Urgency language',
  identity_suspicion: 'Identity red flags',
  component_size_log: 'Size of linked-vendor cluster',
  component_new_share: 'Share of new vendors in the cluster',
  neighbour_suspicion: 'Red flags among linked vendors',
}

const plural = (n: number, noun: string) => `${n} other ${noun}${n === 1 ? '' : 's'}`

/** Human label for a LIME feature. Falls back to the backend label with its "(rule)" suffix stripped. */
export function limeLabel(feature: string, value: number | null, fallback = ''): string {
  const bin = BINARY[feature]
  if (bin) {
    if (value == null) return bin[0]
    return value >= 0.5 ? bin[0] : bin[1]
  }
  const shared = SHARED[feature]
  if (shared) {
    const n = value == null ? 0 : Math.round(value)
    return n > 0 ? `${shared} shared with ${plural(n, 'vendor')}` : `${shared} not shared with other vendors`
  }
  if (feature === 'urgency_terms' && value != null) {
    const n = Math.round(value)
    return n > 0 ? `Urgency language (${n} term${n === 1 ? '' : 's'})` : 'No urgency language'
  }
  if (feature === 'amount_vs_history' && value != null && value > 0) {
    return `Amount is ${value.toFixed(1)}× this vendor’s usual`
  }
  if (OTHER[feature]) return OTHER[feature]
  const cleaned = fallback
    .replace(/\s*\([^)]*\)\s*$/, '')
    .replace(/:\s*(yes|no)\s*$/i, '')
    .trim()
  if (cleaned) return cleaned.charAt(0).toUpperCase() + cleaned.slice(1)
  return feature.replace(/_/g, ' ')
}

export const CLASS_LABELS: Record<string, string> = {
  ato_bec: 'account takeover / BEC',
  insider: 'insider abuse',
  fake_vendor: 'fake vendor',
  legitimacy: 'legitimacy',
  honest: 'legitimacy',
}

export function classLabel(cls: string | null | undefined): string | null {
  if (!cls) return null
  return CLASS_LABELS[cls] ?? cls.replace(/_/g, ' ')
}

/** Concern factors first, each group by descending magnitude. */
export function sortLime<T extends { weight: number; direction: 'concern' | 'reassuring' }>(factors: T[]): T[] {
  return [...factors].sort((a, b) => {
    if (a.direction !== b.direction) return a.direction === 'concern' ? -1 : 1
    return Math.abs(b.weight) - Math.abs(a.weight)
  })
}

/** Mock payloads carry only `evidence`; lift it into the LIME shape so the panel renders the same way. */
export function limeFromEvidence(evidence: EvidenceFactor[]): ModelExplanation {
  return {
    factors: evidence.map((e) => ({
      id: e.id,
      feature: e.id,
      label: e.label,
      rawLabel: e.label,
      weight: e.direction === 'concern' ? e.weight : -e.weight,
      value: null,
      direction: e.direction,
    })),
    targetClass: null,
    scorer: null,
    modelVersion: null,
  }
}

/** Factors the panel should render for a payment: real LIME rows when the backend sent them, else evidence. */
export function explanationFor(p: Payment): { model: ModelExplanation; fromLime: boolean } {
  if (p.model && p.model.factors.length > 0) return { model: p.model, fromLime: true }
  return { model: limeFromEvidence(p.evidence), fromLime: false }
}

/** Signed weight for display: concerns read "+", reassuring factors read "−". */
export function formatWeight(f: LimeFactor): string {
  const mag = Math.abs(f.weight)
  const text = mag >= 10 ? mag.toFixed(1) : mag.toFixed(2)
  return `${f.direction === 'concern' ? '+' : '−'}${text}`
}
