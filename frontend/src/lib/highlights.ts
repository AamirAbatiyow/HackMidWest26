import type { InvoiceHighlight } from '@/api/types'

/** How many invoice fields are red (high) and amber (warn). */
export function countFlagged(highlights: InvoiceHighlight[]): { high: number; warn: number } {
  return {
    high: highlights.filter((h) => h.severity === 'high').length,
    warn: highlights.filter((h) => h.severity === 'warn').length,
  }
}
