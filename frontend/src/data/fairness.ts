import type { FairnessReport } from '@/api/types'

export const DEMO_FAIRNESS: FairnessReport = {
  period: 'Last 90 days',
  fraudCaught: {
    count: 4,
    amount: 31_900,
    examples: ['Changed bank details (2)', 'Fake-vendor ring (1)', 'Split invoice (1)'],
  },
  honestAffected: {
    blocked: 0,
    quickChecks: 6,
    avgResolveMinutes: 102,
  },
  heldShare: 0.09,
  avgDelayDays: 0.4,
  newSmallVendorsOnTime: 0.97,
  parity: [
    { country: 'US', label: 'United States', payments: 212, heldShare: 0.08, avgDelayDays: 0.3 },
    { country: 'MX', label: 'Mexico', payments: 96, heldShare: 0.09, avgDelayDays: 0.4 },
    { country: 'PL', label: 'Poland', payments: 54, heldShare: 0.09, avgDelayDays: 0.5 },
    { country: 'BR', label: 'Brazil', payments: 38, heldShare: 0.08, avgDelayDays: 0.4 },
  ],
}
