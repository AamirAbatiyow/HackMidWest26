import type { NetworkStatus } from '@/api/types'

export const DEMO_NETWORK: NetworkStatus = {
  hops: [
    { id: 'h1', from: 'Owner app', to: 'NodeBalancer', p50Ms: 18, p95Ms: 41, isPrivate: false },
    { id: 'h2', from: 'NodeBalancer', to: 'API', p50Ms: 3, p95Ms: 7, isPrivate: true },
    { id: 'h3', from: 'API', to: 'Private model server', p50Ms: 212, p95Ms: 488, isPrivate: true },
    { id: 'h4', from: 'API', to: 'Postgres', p50Ms: 2, p95Ms: 6, isPrivate: true },
  ],
  modelVersion: 'vouch-screen-7b · 2026.10.1',
  tokens: { promptToday: 184_320, completionToday: 41_906, perPaymentAvg: 2_830 },
  policyChecks: { passed: 1_284, total: 1_284 },
  region: 'us-central (Chicago)',
  updatedAt: new Date().toISOString(),
}
