import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import type { LatencyStats } from '@/api/types'
import { compactWaterfall, COST_LINE, DEMO_LATENCY, DEMO_TOPOLOGY, EMPTY_TIMINGS_TITLE, hasTimings } from '@/data/netstats'
import { NetstatsPage } from '@/pages/NetstatsPage'

const apiRef: { latency: LatencyStats } = { latency: DEMO_LATENCY }

vi.mock('@/api/ApiProvider', () => ({
  useApi: () => ({
    api: {
      getLatency: async () => structuredClone(apiRef.latency),
      getTopology: async () => structuredClone(DEMO_TOPOLOGY),
    },
    mode: 'live',
  }),
}))

/** What the live backend returns before the first invoice: every counter 0, every timing null. */
function emptyLatency(): LatencyStats {
  const zero = { p50Ms: null, p95Ms: null, count: 0, latestMs: null }
  return {
    ...structuredClone(DEMO_LATENCY),
    pipelineSteps: Object.fromEntries(Object.keys(DEMO_LATENCY.pipelineSteps).map((k) => [k, { ...zero }])),
    inference: Object.fromEntries(Object.entries(DEMO_LATENCY.inference).map(([k, v]) => [k, { ...v, ...zero }])),
    decider: { ...DEMO_LATENCY.decider, ...zero },
    postgres: { configured: true, ok: true, latencyMs: null, p50Ms: null, p95Ms: null },
    objectStorage: { configured: false, ok: null, latencyMs: null, p50Ms: null, p95Ms: null },
    lastRunWaterfall: null,
  }
}

const COST_TEXT = `${COST_LINE.before}${COST_LINE.linkText}${COST_LINE.after}`

async function mountPage(latency: LatencyStats) {
  apiRef.latency = latency
  render(
    <MemoryRouter>
      <NetstatsPage />
    </MemoryRouter>,
  )
  await screen.findByText('Akamai Network Topology')
}

describe('hasTimings', () => {
  it('is false until any step, endpoint or the decider has a sample', () => {
    expect(hasTimings(emptyLatency())).toBe(false)
    expect(hasTimings(DEMO_LATENCY)).toBe(true)
  })
})

describe('compactWaterfall', () => {
  it('folds the ten timers into read / checks / score / policy / write from the latest run', () => {
    const { runId, steps } = compactWaterfall(DEMO_LATENCY)
    expect(runId).toBe('run-demo-001')
    expect(steps).toEqual([
      { step: 'read', latencyMs: 14 + 7 + 18 },
      { step: 'checks', latencyMs: 2 + 4 + 5 + 22 },
      { step: 'score', latencyMs: 92 },
      { step: 'policy', latencyMs: 3 },
      { step: 'write', latencyMs: 13 },
    ])
  })

  it('falls back to rolling p50s without a run and drops groups with no sample', () => {
    const latency = { ...structuredClone(DEMO_LATENCY), lastRunWaterfall: null }
    delete latency.pipelineSteps.writer
    const { runId, steps } = compactWaterfall(latency)
    expect(runId).toBeNull()
    expect(steps.map((s) => s.step)).toEqual(['read', 'checks', 'score', 'policy'])
    expect(steps[2]).toEqual({ step: 'score', latencyMs: 85 })
  })

  it('is empty when nothing was measured', () => {
    expect(compactWaterfall(emptyLatency()).steps).toEqual([])
  })
})

describe('Latency page with no runs yet', () => {
  it('shows the send-an-invoice state instead of dashes and 0 ms', async () => {
    await mountPage(emptyLatency())
    expect(screen.getByText(EMPTY_TIMINGS_TITLE)).toBeInTheDocument()
    expect(screen.queryByText('Key Timings')).not.toBeInTheDocument()
    expect(screen.queryByText('Per-step Timing')).not.toBeInTheDocument()
    expect(screen.queryByText(/0 ms/)).not.toBeInTheDocument()
    expect(screen.queryByText(/— ms/)).not.toBeInTheDocument()
    expect(screen.getByText(/no runs yet/)).toBeInTheDocument()
  })

  it('still shows the topology', async () => {
    await mountPage(emptyLatency())
    expect(screen.getByRole('img', { name: 'Network topology diagram' })).toBeInTheDocument()
  })
})

describe('Latency page with timings', () => {
  it('shows one row of key numbers and one compact per-step waterfall', async () => {
    await mountPage(DEMO_LATENCY)
    const tiles = screen.getByText('Key Timings').closest('section')!
    const labels = Array.from(tiles.querySelectorAll('.uppercase')).map((el) => el.textContent)
    expect(labels).toEqual(['hackathon-chat', 'hackathon-embedding', 'Postgres', 'Object Storage', `Decider · ${DEMO_LATENCY.decider.engine}`])
    expect(within(tiles).getByText(`${DEMO_LATENCY.inference['hackathon-chat'].p50Ms} ms`)).toBeInTheDocument()
    expect(screen.getByText('Per-step Timing')).toBeInTheDocument()
    for (const step of ['Read', 'Checks', 'Score', 'Policy', 'Write']) expect(screen.getByText(step)).toBeInTheDocument()
    expect(screen.queryByText(/Detector|reader|sender check|vendor resolution/i)).not.toBeInTheDocument()
  })

  it('does not show the long tables, sparklines, the summed end-to-end number or the unrelated runtime rows', async () => {
    await mountPage(DEMO_LATENCY)
    expect(screen.queryByText('Pipeline Steps')).not.toBeInTheDocument()
    expect(screen.queryByText('Akamai Hosted Inference')).not.toBeInTheDocument()
    expect(screen.queryByText('Tier Map')).not.toBeInTheDocument()
    expect(document.querySelector('[aria-label$="p50 trend"]')).toBeNull()
    expect(screen.queryByText(/Pipeline p50|Pipeline p95|sum of hops|end to end/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Policy checks/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Last settlement/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Design tokens/)).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /tokens/ })).not.toBeInTheDocument()
  })
})

describe('cost line', () => {
  it('is the exact sentence with ACFE 2024 linked, at the bottom of the page', async () => {
    await mountPage(emptyLatency())
    const line = screen.getByTestId('cost-line')
    expect(line).toHaveTextContent(COST_TEXT)
    expect(COST_TEXT).toBe(
      'The full Vouch stack runs for about $186/month ($2,232/year). A single median fraud case at organizations with fewer than 100 employees costs $141,000 (ACFE 2024). Stopping one case pays for more than 60 years of running Vouch ($141,000 ÷ $2,232 ≈ 63).',
    )
    const link = screen.getByRole('link', { name: 'ACFE 2024' })
    expect(link).toHaveAttribute('href', 'https://www.acfe.com/-/media/files/acfe/pdfs/rttn/2024/2024-report-to-the-nations.pdf')
    expect(line.compareDocumentPosition(screen.getByText('Akamai Network Topology')) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy()
    expect(line.parentElement?.lastElementChild).toBe(line)
  })
})
