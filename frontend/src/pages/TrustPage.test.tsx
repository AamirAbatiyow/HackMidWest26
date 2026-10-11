import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { redTeamSummary } from '@/data/cedar'
import { DEMO_TRUST } from '@/data/trust'
import { CedarGuardrails } from '@/pages/TrustPage'

function render(blocked: number | null = 31, running = false) {
  const suite = DEMO_TRUST.security_controls.redteam_suite
  return renderToStaticMarkup(
    <MemoryRouter>
      <CedarGuardrails trust={DEMO_TRUST} redTeam={redTeamSummary(suite.total_cases, blocked)} redTeamRunning={running} />
    </MemoryRouter>,
  )
}

const count = (html: string, needle: string) => html.split(needle).length - 1

describe('CedarGuardrails', () => {
  it('leads with the headline, the one-line explanation and the red-team result', () => {
    const html = render()
    expect(html).toContain('9 Cedar rules, default-deny')
    expect(html).toContain('Cedar is the permission layer around the agent')
    expect(html).toContain('31/31 blocked')
    expect(html).toContain('href="/redteam"')
  })

  it('shows a clear ALLOW / LIMITED / DENY marker for every agent action', () => {
    const html = render()
    expect(count(html, 'data-outcome="allow"')).toBe(3 * 2) // row + badge
    expect(count(html, 'data-outcome="limited"')).toBe(1 * 2)
    expect(count(html, 'data-outcome="deny"')).toBe(6 * 2)
    expect(html).toContain('>ALLOW<')
    expect(html).toContain('>LIMITED<')
    expect(html).toContain('>DENY<')
    for (const label of ['Read the invoice', 'Place a hold', 'Settle: move the money', 'Change a vendor&#x27;s bank details', 'Deny a vendor']) {
      expect(html, label).toContain(label)
    }
  })

  it('lists all 9 rules with id, plain English and what each protects against', () => {
    const html = render()
    for (let i = 1; i <= 9; i++) expect(html).toContain(`>P-0${i}<`)
    expect(html).toContain('Protects against')
    expect(html).toContain('Owner or System')
    expect(html).toContain('call-back to the number on file')
  })

  it('reports a pending or partial red-team run honestly', () => {
    expect(render(null, true)).toContain('running 31…')
    expect(render(null, false)).toContain('31 cases')
    expect(render(30)).toContain('30/31 blocked')
  })
})
