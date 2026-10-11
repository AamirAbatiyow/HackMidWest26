import { describe, expect, it, vi } from 'vitest'
import { fetchTimeline } from './useOrchestratorTimeline'

const okJson = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })

describe('fetchTimeline', () => {
  it('GETs /v1/payments/{id}/timeline on the configured base URL and normalizes the body', async () => {
    const fetchImpl = vi.fn(async () => okJson({ card_id: 'run_a.1', run_id: 'run_a', run_status: 'running', complete: false, steps: [{ order: 1, step: 'intake', status: 'ok', result: 'received via email' }] }))
    const t = await fetchTimeline('http://localhost:8101/', 'run_a.1', fetchImpl as unknown as typeof fetch)
    expect(fetchImpl).toHaveBeenCalledTimes(1)
    const [url] = (fetchImpl.mock.calls as unknown as [string, RequestInit][])[0]!
    expect(url).toBe('http://localhost:8101/v1/payments/run_a.1/timeline')
    expect(t.complete).toBe(false)
    expect(t.runStatus).toBe('running')
    expect(t.steps).toHaveLength(1)
    expect(t.steps[0]!.step).toBe('intake')
  })

  it('throws on a non-2xx response so the pane can show the error', async () => {
    const fetchImpl = vi.fn(async () => new Response('{}', { status: 404, statusText: 'Not Found' }))
    await expect(fetchTimeline('http://api', 'nope', fetchImpl as unknown as typeof fetch)).rejects.toThrow('404 Not Found')
  })
})
