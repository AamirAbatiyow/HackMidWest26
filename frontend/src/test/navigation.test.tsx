import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { AppProviders, AppRoutes } from '@/App'
import { QUEUE_PATH } from '@/lib/routes'

function LocationProbe() {
  const { pathname, search } = useLocation()
  return <output data-testid="location">{pathname + search}</output>
}

function mount(initialPath: string) {
  const user = userEvent.setup()
  render(
    <AppProviders>
      <MemoryRouter initialEntries={[initialPath]}>
        <AppRoutes />
        <LocationProbe />
      </MemoryRouter>
    </AppProviders>,
  )
  return { user }
}

const location = () => screen.getByTestId('location').textContent
const topBarNav = () => screen.getByRole('navigation', { name: 'Views' })

describe('splash', () => {
  it('shows only the wordmark on / and nothing from the workspace', () => {
    mount('/')
    expect(screen.getByRole('heading', { level: 1, name: 'Vouch' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Views' })).not.toBeInTheDocument()
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument()
    expect(screen.queryByText(/Commands/)).not.toBeInTheDocument()
    expect(location()).toBe('/')
  })

  it('goes to the live queue on click', async () => {
    const { user } = mount('/')
    await user.click(screen.getByRole('button', { name: /open the live queue/i }))
    expect(location()).toBe(QUEUE_PATH)
    expect(topBarNav()).toBeInTheDocument()
  })

  it('goes to the live queue on Enter', async () => {
    const { user } = mount('/')
    await user.keyboard('{Enter}')
    expect(location()).toBe(QUEUE_PATH)
  })

  it('goes to the live queue on Space', async () => {
    const { user } = mount('/')
    await user.keyboard(' ')
    expect(location()).toBe(QUEUE_PATH)
  })

  it('is skipped when opening /app directly', () => {
    mount(QUEUE_PATH)
    expect(location()).toBe(QUEUE_PATH)
    expect(screen.queryByRole('heading', { level: 1, name: 'Vouch' })).not.toBeInTheDocument()
    expect(topBarNav()).toBeInTheDocument()
  })
})

describe('top bar', () => {
  it('lists only the queue, Latency, Red team and Trust', () => {
    mount(QUEUE_PATH)
    const links = within(topBarNav()).getAllByRole('link')
    expect(links.map((l) => l.textContent)).toEqual(['Payables', 'Latency', 'Red team', 'Trust'])
    expect(links.map((l) => l.getAttribute('href'))).toEqual([QUEUE_PATH, '/netstats', '/redteam', '/trust'])
    for (const hidden of ['Fairness', 'Network', 'Design tokens', 'Tokens']) {
      expect(within(topBarNav()).queryByText(hidden)).not.toBeInTheDocument()
    }
  })

  it('logo links to the queue, not the splash', () => {
    mount('/trust')
    expect(screen.getByRole('link', { name: 'Vouch payables' })).toHaveAttribute('href', QUEUE_PATH)
  })

  it('navigates between the demo pages', async () => {
    const { user } = mount(QUEUE_PATH)
    await user.click(within(topBarNav()).getByRole('link', { name: 'Latency' }))
    expect(location()).toBe('/netstats')
    await user.click(within(topBarNav()).getByRole('link', { name: 'Trust' }))
    expect(location()).toBe('/trust')
    await user.click(within(topBarNav()).getByRole('link', { name: 'Red team' }))
    expect(location()).toBe('/redteam')
    await user.click(screen.getByRole('link', { name: 'Vouch payables' }))
    expect(location()).toBe(QUEUE_PATH)
  })
})

describe('command palette', () => {
  it('hides Fairness, Network and Design tokens from Go to', async () => {
    const { user } = mount(QUEUE_PATH)
    await user.keyboard('{Meta>}k{/Meta}')
    const dialog = await screen.findByRole('dialog', { name: 'Command palette' })
    const goTo = within(dialog).getByText('Go to').parentElement!
    const labels = within(goTo).getAllByRole('option').map((o) => o.textContent)
    expect(labels.some((l) => l?.startsWith('Payables'))).toBe(true)
    expect(labels.some((l) => l?.startsWith('Latency'))).toBe(true)
    expect(labels.some((l) => l?.startsWith('Trust'))).toBe(true)
    expect(labels.some((l) => l?.startsWith('Red team'))).toBe(true)
    expect(labels.join(' ')).not.toMatch(/Fairness|Network|Design tokens/)
  })
})

describe('redirects', () => {
  it('sends /payments/:id to the queue with that payment open', async () => {
    mount('/payments/pay-002')
    await waitFor(() => expect(location()).toBe(`${QUEUE_PATH}?payment=pay-002`))
  })

  it('sends the retired /fairness route to the queue', async () => {
    mount('/fairness')
    await waitFor(() => expect(location()).toBe(QUEUE_PATH))
  })

  it('sends unknown routes to the queue', async () => {
    mount('/nope/really')
    await waitFor(() => expect(location()).toBe(QUEUE_PATH))
  })

  it('keeps the hidden routes alive', () => {
    for (const path of ['/network', '/tokens', '/trust', '/netstats', '/redteam']) {
      const { unmount } = render(
        <AppProviders>
          <MemoryRouter initialEntries={[path]}>
            <AppRoutes />
            <LocationProbe />
          </MemoryRouter>
        </AppProviders>,
      )
      expect(location()).toBe(path)
      unmount()
    }
  })
})
