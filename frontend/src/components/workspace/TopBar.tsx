import { useEffect, useRef } from 'react'
import { NavLink } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { useUi } from '@/store/UiProvider'
import { Shortcut } from './Shortcut'

/** Every routed view; the palette lists all of them. */
export const VIEWS = [
  { to: '/', label: 'Payables', key: 'p', nav: true },
  { to: '/approve', label: 'Approval', key: 'a', nav: false },
  { to: '/fairness', label: 'Fairness', key: 'f', nav: true },
  { to: '/network', label: 'Network', key: 'n', nav: true },
  { to: '/redteam', label: 'Red team', key: 'r', nav: true },
  { to: '/tokens', label: 'Design tokens', key: 't', nav: false },
] as const

export const SEARCH_INPUT_ID = 'global-search'

export function TopBar() {
  const { openPalette, search, setSearch } = useUi()
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const onFocus = () => inputRef.current?.focus()
    window.addEventListener('vouch:focus-search', onFocus)
    return () => window.removeEventListener('vouch:focus-search', onFocus)
  }, [])

  return (
    <header className="flex h-topbar shrink-0 items-center gap-3 border-b bg-background px-3">
      <NavLink to="/" className="num text-xs font-semibold tracking-[0.14em] text-foreground uppercase outline-none focus-visible:ring-1 focus-visible:ring-ring" aria-label="Vouch payables">
        Vouch
      </NavLink>
      <nav aria-label="Views" className="flex items-center">
        {VIEWS.filter((v) => v.nav).map((v) => (
          <NavLink
            key={v.to}
            to={v.to}
            end={v.to === '/'}
            className={({ isActive }) =>
              cn(
                'relative flex h-topbar items-center px-2 text-sm outline-none focus-visible:ring-1 focus-visible:ring-ring',
                isActive ? 'text-foreground after:absolute after:inset-x-2 after:bottom-0 after:h-px after:bg-foreground' : 'text-muted-foreground hover:text-foreground',
              )
            }
          >
            {v.label}
          </NavLink>
        ))}
      </nav>

      <div className="relative ml-2 flex h-6 max-w-[320px] min-w-0 flex-1 items-center">
        <input
          ref={inputRef}
          id={SEARCH_INPUT_ID}
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              setSearch('')
              e.currentTarget.blur()
            }
          }}
          placeholder="Search"
          aria-label="Search payments"
          className="num h-6 w-full rounded-xs border bg-surface-1 px-2 pr-6 text-xs text-foreground outline-none placeholder:text-muted-foreground/70 focus:border-accent-cool/60 [&::-webkit-search-cancel-button]:hidden"
        />
        <Shortcut id="search" className="pointer-events-none absolute right-2" />
      </div>

      <div className="ml-auto flex items-center gap-1 text-xs">
        <button type="button" className="flex h-6 items-center gap-1.5 rounded-xs px-2 text-muted-foreground hover:bg-surface-2 hover:text-foreground" onClick={() => openPalette()} aria-label="Open command palette">
          Commands <Shortcut id="palette" />
        </button>
      </div>
    </header>
  )
}
