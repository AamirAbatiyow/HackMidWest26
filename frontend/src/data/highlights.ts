import type { InvoiceHighlight, LimeFactor, ModelExplanation, Payment } from '@/api/types'
import { limeLabel } from '@/lib/lime'

type Sev = InvoiceHighlight['severity']

const f = (field: string, label: string, value: string, severity: Sev = 'ok', ...reasons: string[]): InvoiceHighlight => ({ field, label, value, severity, reasons })

const lime = (targetClass: string, rows: [feature: string, weight: number, value: number | null][]): ModelExplanation => {
  const towardLegit = targetClass === 'legitimacy'
  const factors: LimeFactor[] = rows.map(([feature, weight, value], i) => ({
    id: `l-${i}`,
    feature,
    label: limeLabel(feature, value),
    rawLabel: feature,
    weight,
    value,
    direction: (towardLegit ? weight < 0 : weight > 0) ? 'concern' : 'reassuring',
  }))
  return { factors, targetClass, scorer: 'local-torch', modelVersion: 'vouch-risk-demo' }
}

/** Invoice documents for the built-in demo payments, mirroring what the backend's `highlights` emits. */
export const DEMO_HIGHLIGHTS: Record<string, InvoiceHighlight[]> = {
  'pay-001': [
    f('vendor_name', 'Vendor', 'Reyes Packaging'),
    f('invoice_number', 'Invoice no.', 'RP-10482'),
    f('issue_date', 'Invoice date', '2026-10-08'),
    f('due_date', 'Due date', '2026-10-14'),
    f('po_number', 'Purchase order', 'PO-7731'),
    f('amount', 'Amount due', '$6,400.00'),
    f('bank_account', 'Bank account', 'MX12 0180 0001 2345 6789 01'),
    f('tax_id', 'Tax ID', 'RPA-230214-K7'),
    f('address', 'Address', 'Av. Insurgentes Sur 1602, Mexico City'),
    f('phone', 'Phone', '+52-55-555-0184'),
    f('sender_email', 'Sender', 'ar@reyespackaging.mx'),
    f('remit_email', 'Remit email', 'ar@reyespackaging.mx'),
  ],
  'pay-002': [
    f('vendor_name', 'Vendor', 'Warsaw Steel Sp. z o.o.'),
    f('invoice_number', 'Invoice no.', 'WS-2026-0917'),
    f('issue_date', 'Invoice date', '2026-10-09'),
    f('due_date', 'Due date', '2026-10-15'),
    f('po_number', 'Purchase order', 'PO-7744'),
    f('amount', 'Amount due', '$12,000.00', 'high', 'round-thousand amount'),
    f('bank_account', 'Bank account', 'DE91 1000 0000 0123 4567 89', 'high', 'changed 2 days ago without call-back confirmation', 'differs from the account on file (···0118)', 'account in DE, vendor in PL'),
    f('tax_id', 'Tax ID', 'PL-5262-8831-04'),
    f('address', 'Address', 'ul. Stalowa 12, Warsaw'),
    f('phone', 'Phone', '+48-22-555-0118'),
    f('sender_email', 'Sender', 'finance.ws@warsawsteel-eu.com', 'high', 'lookalike of warsawsteel.pl', 'address never used by this vendor before'),
    f('remit_email', 'Remit email', 'finance.ws@warsawsteel-eu.com', 'high', 'domain differs from vendor email on file (@warsawsteel.pl)'),
  ],
  'pay-003': [
    f('vendor_name', 'Vendor', 'Midwest Pallets'),
    f('invoice_number', 'Invoice no.', 'MP-5521'),
    f('issue_date', 'Invoice date', '2026-10-07'),
    f('due_date', 'Due date', '2026-10-13'),
    f('po_number', 'Purchase order', 'PO-7719'),
    f('amount', 'Amount due', '$4,950.00'),
    f('bank_account', 'Bank account', 'US101000012205'),
    f('tax_id', 'Tax ID', '43-5566771'),
    f('address', 'Address', '455 Southwest Blvd, Kansas City, MO'),
    f('phone', 'Phone', '+1-816-555-0177'),
    f('sender_email', 'Sender', 'billing@midwestpallets.com'),
    f('remit_email', 'Remit email', 'billing@midwestpallets.com'),
  ],
  'pay-004': [
    f('vendor_name', 'Vendor', 'Midwest Pallets'),
    f('invoice_number', 'Invoice no.', 'MP-5521', 'high', 'possible duplicate of invoice MP-5521 in this batch'),
    f('issue_date', 'Invoice date', '2026-10-07'),
    f('due_date', 'Due date', '2026-10-13'),
    f('po_number', 'Purchase order', 'PO-7719'),
    f('amount', 'Amount due', '$4,950.00'),
    f('bank_account', 'Bank account', 'US101000012205'),
    f('tax_id', 'Tax ID', '43-5566771'),
    f('address', 'Address', '455 Southwest Blvd, Kansas City, MO'),
    f('phone', 'Phone', '+1-816-555-0177'),
    f('sender_email', 'Sender', 'billing@midwestpallets.com'),
    f('remit_email', 'Remit email', 'billing@midwestpallets.com'),
  ],
  'pay-005': [
    f('vendor_name', 'Vendor', 'Brightline Supply'),
    f('invoice_number', 'Invoice no.', 'BL-3307', 'high', 'possible split invoice under the approval limit'),
    f('issue_date', 'Invoice date', '2026-10-09'),
    f('due_date', 'Due date', '2026-10-16'),
    f('po_number', 'Purchase order', 'none', 'warn', 'no purchase order and no delivery confirmation'),
    f('amount', 'Amount due', '$4,900.00', 'high', 'just under the approval limit · part of a split'),
    f('bank_account', 'Bank account', 'US044000037712'),
    f('tax_id', 'Tax ID', '48-7709912'),
    f('address', 'Address', '7300 W 110th St, Overland Park, KS'),
    f('phone', 'Phone', '+1-913-555-0160'),
    f('sender_email', 'Sender', 'ap@brightlinesupply.com'),
  ],
  'pay-006': [
    f('vendor_name', 'Vendor', 'Brightline Supply'),
    f('invoice_number', 'Invoice no.', 'BL-3308', 'high', 'possible split invoice under the approval limit'),
    f('issue_date', 'Invoice date', '2026-10-09'),
    f('due_date', 'Due date', '2026-10-16'),
    f('po_number', 'Purchase order', 'none', 'warn', 'no purchase order and no delivery confirmation'),
    f('amount', 'Amount due', '$4,900.00', 'high', 'just under the approval limit · part of a split'),
    f('bank_account', 'Bank account', 'US044000037712'),
    f('tax_id', 'Tax ID', '48-7709912'),
    f('address', 'Address', '7300 W 110th St, Overland Park, KS'),
    f('phone', 'Phone', '+1-913-555-0160'),
    f('sender_email', 'Sender', 'ap@brightlinesupply.com'),
  ],
  'pay-007': [
    f('vendor_name', 'Vendor', 'Nova Trade LLC', 'warn', 'vendor added 6 days ago, no payments yet'),
    f('invoice_number', 'Invoice no.', 'NT-0001'),
    f('issue_date', 'Invoice date', '2026-10-10'),
    f('due_date', 'Due date', '2026-10-17'),
    f('po_number', 'Purchase order', 'none', 'warn', 'no purchase order and no delivery confirmation'),
    f('amount', 'Amount due', '$7,200.00'),
    f('bank_account', 'Bank account', 'US071000014471', 'high', 'bank account shared with 2 other vendors (Apex Supply Co., Delta Freight LLC)'),
    f('tax_id', 'Tax ID', '88-2210934', 'high', 'tax ID fails checksum'),
    f('address', 'Address', '1201 N Orange St, Wilmington, DE', 'high', 'virtual office / PO box address', 'address shared with 1 other vendor (Delta Freight LLC)'),
    f('phone', 'Phone', '+1-816-555-0192', 'high', 'phone number shared with 1 other vendor (Apex Supply Co.)'),
    f('sender_email', 'Sender', 'uploaded by ap-clerk-3 · no email envelope'),
    f('remit_email', 'Remit email', 'novatrade.billing@gmail.com', 'warn', 'free webmail provider'),
  ],
  'pay-008': [
    f('vendor_name', 'Vendor', 'Café Santa Rita'),
    f('invoice_number', 'Invoice no.', 'CSR-0001'),
    f('issue_date', 'Invoice date', '2026-10-10'),
    f('due_date', 'Due date', '2026-10-11'),
    f('po_number', 'Purchase order', 'PO-7750'),
    f('amount', 'Amount due', '$1,850.00'),
    f('bank_account', 'Bank account', 'BR18 0036 0305 0000 1000 9795 493C 1'),
    f('tax_id', 'Tax ID', '12.345.678/0001-95'),
    f('address', 'Address', 'Rua da Bahia 1148, Belo Horizonte'),
    f('phone', 'Phone', '+55-31-555-0133'),
    f('sender_email', 'Sender', 'uploaded by ap-clerk-2 · no email envelope'),
    f('remit_email', 'Remit email', 'financeiro@cafesantarita.com.br'),
  ],
}

/** LIME factors for the demo cards whose story is model-driven; the rest fall back to `evidence`. */
export const DEMO_MODEL: Record<string, ModelExplanation> = {
  'pay-002': lime('ato_bec', [
    ['bank_change_unconfirmed', 2.5, 1],
    ['remit_email_mismatch', 1.2, 1],
    ['contact_change_recent', 1.0, 1],
    ['foreign_bank', 0.8, 1],
    ['history_count_log', -0.9, 4.08],
    ['amount_vs_history', -0.4, 1.02],
  ]),
  'pay-007': lime('fake_vendor', [
    ['shared_bank', 3.0, 2],
    ['neighbour_suspicion', 1.3, 0.88],
    ['tax_id_invalid', 1.5, 1],
    ['shared_phone', 0.8, 1],
    ['address_virtual', 0.8, 1],
    ['new_vendor', 0.6, 1],
    ['line_items_mismatch', -0.3, 0],
  ]),
}

/** Attach the demo invoice document and LIME factors to a mock payment. */
export function withDemoDetail(p: Payment): Payment {
  return {
    ...p,
    highlights: p.highlights ?? DEMO_HIGHLIGHTS[p.id],
    model: p.model ?? DEMO_MODEL[p.id],
  }
}
