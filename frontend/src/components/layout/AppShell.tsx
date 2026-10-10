import { Bot, Moon, Settings2, Sun, Wifi, WifiOff } from 'lucide-react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useApi } from '@/api/ApiProvider'
import { Logo } from '@/components/brand/Logo'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { AgentActivityPanel } from '@/components/vouch/AgentActivityPanel'
import { cn } from '@/lib/utils'
import { useUi } from '@/store/UiProvider'
import { useTheme } from '@/theme/ThemeProvider'

const NAV = [
  { to: '/', label: 'Payables' },
  { to: '/fairness', label: 'Fairness' },
  { to: '/network', label: 'Network' },
  { to: '/redteam', label: 'Red team' },
  { to: '/tokens', label: 'Tokens' },
]

export function ApiModeControl({ className }: { className?: string }) {
  const { mode, setMode, baseUrl, health } = useApi()
  const live = mode === 'live'
  return (
    <div className={cn('space-y-3', className)}>
      <div className="flex items-center justify-between gap-4">
        <Label htmlFor="api-mode" className="flex flex-col items-start gap-0.5">
          <span className="text-sm font-medium">Live API</span>
          <span className="text-xs font-normal text-muted-foreground">
            {live ? `Connected to ${baseUrl}` : 'Using built-in demo data'}
          </span>
        </Label>
        <Switch id="api-mode" checked={live} onCheckedChange={(v) => setMode(v ? 'live' : 'mock')} />
      </div>
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {health?.ok ? (
          <Wifi className="size-3.5 text-vouched" aria-hidden="true" />
        ) : (
          <WifiOff className="size-3.5 text-attention" aria-hidden="true" />
        )}
        {health == null
          ? 'Checking…'
          : health.ok
            ? `${live ? 'Backend' : 'Mock'} healthy${health.latencyMs != null && live ? ` · ${health.latencyMs} ms` : ''}`
            : 'Backend unreachable. Flip the switch off to keep using demo data.'}
      </p>
    </div>
  )
}

export function AppShell() {
  const { theme, toggle } = useTheme()
  const { mode } = useApi()
  const { agentPanelOpen, toggleAgentPanel, closeAgentPanel, agentRunKey, agentSubject } = useUi()
  const location = useLocation()
  const minimal = location.pathname.startsWith('/approve') || location.pathname.startsWith('/receipt')

  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-sm focus:text-primary-foreground"
      >
        Skip to content
      </a>
      <header className="sticky top-0 z-30 border-b bg-background/85 backdrop-blur supports-backdrop-filter:bg-background/70">
        <div className="mx-auto flex h-16 max-w-[1440px] items-center justify-between gap-6 px-4 sm:px-8">
          <div className="flex items-center gap-8">
            <NavLink to="/" className="rounded-md outline-none focus-visible:ring-3 focus-visible:ring-ring/50" aria-label="Vouch home">
              <Logo />
            </NavLink>
            {!minimal && (
              <nav aria-label="Primary" className="hidden items-center gap-1 md:flex">
                {NAV.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === '/'}
                    className={({ isActive }) =>
                      cn(
                        'rounded-lg px-3 py-1.5 text-sm font-medium transition-colors duration-150 outline-none focus-visible:ring-3 focus-visible:ring-ring/50',
                        isActive ? 'bg-accent text-foreground' : 'text-muted-foreground hover:bg-accent/60 hover:text-foreground',
                      )
                    }
                  >
                    {item.label}
                  </NavLink>
                ))}
              </nav>
            )}
          </div>

          <div className="flex items-center gap-1.5">
            <span
              className={cn(
                'mr-1 hidden h-6 items-center gap-1.5 rounded-full px-2 text-[11px] font-medium sm:inline-flex',
                mode === 'live' ? 'bg-vouched-soft text-vouched' : 'bg-muted text-muted-foreground',
              )}
            >
              <span className={cn('size-1.5 rounded-full', mode === 'live' ? 'bg-vouched' : 'bg-muted-foreground/60')} aria-hidden="true" />
              {mode === 'live' ? 'Live API' : 'Demo data'}
            </span>

            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant={agentPanelOpen ? 'secondary' : 'ghost'}
                  size="icon"
                  onClick={toggleAgentPanel}
                  aria-pressed={agentPanelOpen}
                  aria-label="Toggle agent activity panel"
                >
                  <Bot aria-hidden="true" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Agent activity</TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon" onClick={toggle} aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}>
                  {theme === 'dark' ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
                </Button>
              </TooltipTrigger>
              <TooltipContent>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</TooltipContent>
            </Tooltip>

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" aria-label="Settings">
                  <Settings2 aria-hidden="true" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-80 p-3">
                <DropdownMenuLabel className="px-0 pb-2">Data source</DropdownMenuLabel>
                <ApiModeControl />
                <DropdownMenuSeparator className="my-3" />
                <p className="text-xs text-muted-foreground">
                  Signed in as <span className="font-medium text-foreground">Dana</span> · KC Wholesale Distribution
                </p>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
        {!minimal && (
          <nav aria-label="Primary mobile" className="flex gap-1 overflow-x-auto px-3 pb-2 md:hidden">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) =>
                  cn(
                    'shrink-0 rounded-lg px-3 py-1.5 text-sm font-medium',
                    isActive ? 'bg-accent text-foreground' : 'text-muted-foreground',
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        )}
      </header>

      <main
        id="main"
        className={cn(
          'mx-auto w-full max-w-[1440px] flex-1 px-4 py-8 transition-[padding] duration-250 sm:px-8',
          agentPanelOpen && 'xl:pr-[372px]',
        )}
      >
        <Outlet />
      </main>

      <footer className="border-t py-6 text-center text-xs text-muted-foreground">
        Every payment, checked and explained. Vouch never auto-denies anyone and never adds fees.
      </footer>

      <AgentActivityPanel open={agentPanelOpen} onClose={closeAgentPanel} runKey={agentRunKey} subjectLabel={agentSubject} />
    </div>
  )
}
