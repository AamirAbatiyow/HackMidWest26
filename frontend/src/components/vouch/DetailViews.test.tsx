import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { Payment } from '@/api/types'
import { DEMO_PAYMENTS } from '@/data/payments'
import { withDemoDetail } from '@/data/highlights'
import { countFlagged } from '@/lib/highlights'
import { explanationFor } from '@/lib/lime'
import { HighlightedInvoice } from './HighlightedInvoice'
import { LimeExplanation } from './LimeExplanation'

const demo = (id: string): Payment => withDemoDetail(DEMO_PAYMENTS.find((p) => p.id === id)!)
const nova = demo('pay-007') // fake vendor: shared bank, bad tax id, PO box
const reyes = demo('pay-001') // clean, long-standing vendor

describe('LimeExplanation', () => {
  it('headlines why VouchNet flagged a held card and names LIME', () => {
    const html = renderToStaticMarkup(<LimeExplanation payment={nova} />)
    expect(html).toContain('Why it is held')
    expect(html).toContain('VouchNet flagged this')
    expect(html).toContain('LIME')
    expect(html).toContain('open-source Python explainability library')
    expect(html).toContain('fake vendor')
  })

  it('sorts concerns first by weight, red for concerns and green for reassuring, with numeric weights', () => {
    const html = renderToStaticMarkup(<LimeExplanation payment={nova} />)
    const rows = [...html.matchAll(/data-direction="(concern|reassuring)"/g)].map((m) => m[1])
    expect(rows.slice(0, 6).every((d) => d === 'concern')).toBe(true)
    expect(rows.at(-1)).toBe('reassuring')
    const first = html.indexOf('Bank account shared with 2 other vendors')
    const second = html.indexOf('Tax ID fails checksum')
    expect(first).toBeGreaterThan(-1)
    expect(second).toBeGreaterThan(first)
    expect(html).toContain('+3.00')
    expect(html).toContain('−0.30')
    expect(html).toContain('bg-red')
    expect(html).toContain('bg-green')
  })

  it('falls back to evidence (and says so) when a card has no LIME rows', () => {
    const { model, fromLime } = explanationFor(reyes)
    expect(fromLime).toBe(false)
    expect(model.factors).toHaveLength(reyes.evidence.length)
    const html = renderToStaticMarkup(<LimeExplanation payment={reyes} />)
    expect(html).toContain('Why it is clear to pay')
    expect(html).toContain('Same bank account since Feb 2023')
  })
})

describe('HighlightedInvoice', () => {
  it('renders the fraud invoice as a document with red fields and reason tags', () => {
    const html = renderToStaticMarkup(<HighlightedInvoice payment={nova} />)
    expect(countFlagged(nova.highlights!)).toEqual({ high: 4, warn: 3 })
    expect(html).toContain('data-high="4"')
    for (const field of ['bank_account', 'tax_id', 'address', 'phone']) {
      expect(html).toContain(`data-field="${field}" data-severity="high"`)
    }
    expect(html).toContain('bank account shared with 2 other vendors')
    expect(html).toContain('tax ID fails checksum')
    expect(html).toContain('virtual office / PO box address')
    expect(html).toContain('Nova Trade LLC')
    expect(html).toContain('NT-0001')
    expect(html).toContain('$7,200.00')
    expect(html).toContain('4 fields flagged')
  })

  it('leaves a clean vendor neutral with no tags', () => {
    const html = renderToStaticMarkup(<HighlightedInvoice payment={reyes} />)
    expect(countFlagged(reyes.highlights!)).toEqual({ high: 0, warn: 0 })
    expect(html).not.toContain('data-severity="high"')
    expect(html).not.toContain('data-severity="warn"')
    expect(html).toContain('No suspicious fields')
    expect(html).toContain('RP-10482')
  })

  it('renders nothing when the payload has no highlights', () => {
    const bare: Payment = { ...reyes, highlights: undefined }
    expect(renderToStaticMarkup(<HighlightedInvoice payment={bare} />)).toBe('')
  })

  it('every demo payment carries a document that starts with the vendor and invoice number', () => {
    for (const p of DEMO_PAYMENTS.map(withDemoDetail)) {
      expect(p.highlights, p.id).toBeDefined()
      expect(p.highlights![0]!.field).toBe('vendor_name')
      expect(p.highlights![1]!.value).toBe(p.invoiceNumber)
    }
  })
})
