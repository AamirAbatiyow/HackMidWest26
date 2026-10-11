import { useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { usePaymentActions } from '@/components/workspace/usePaymentActions'
import { usePayments } from '@/store/PaymentsProvider'
import { useUi } from '@/store/UiProvider'
import { useVisibleRows } from '@/store/useVisibleRows'
import { useTheme } from '@/theme/ThemeProvider'
import { QUEUE_PATH } from './routes'
import { isEditableTarget } from './shortcuts'

export const SHORTCUTS_EVENT = 'vouch:shortcuts'
export const FOCUS_SEARCH_EVENT = 'vouch:focus-search'

/**
 * Keyboard-first navigation. j/k move the cursor, Enter opens the panel,
 * x selects, a/h/v/p act, / searches, ? lists shortcuts, g-prefix navigates.
 */
export function useGlobalShortcuts() {
  const ui = useUi()
  const { payments } = usePayments()
  const { order } = useVisibleRows()
  const { run } = usePaymentActions()
  const { toggle } = useTheme()
  const navigate = useNavigate()
  const location = useLocation()
  const pendingG = useRef<number | null>(null)

  // Refs keep the listener stable while state changes.
  const state = useRef({ ui, payments, order, run, toggle, navigate, pathname: location.pathname })
  state.current = { ui, payments, order, run, toggle, navigate, pathname: location.pathname }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const s = state.current
      const u = s.ui
      const meta = e.metaKey || e.ctrlKey

      if (meta && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        u.setPaletteOpen(!u.paletteOpen)
        return
      }
      if (isEditableTarget(e.target) || e.altKey || meta) return
      if (u.paletteOpen) return

      const onPayments = s.pathname === QUEUE_PATH
      const idx = u.activeId ? s.order.indexOf(u.activeId) : -1
      const active = u.activeId ? s.payments.find((p) => p.id === u.activeId) : undefined
      const targets = u.checked.size > 0 ? s.payments.filter((p) => u.checked.has(p.id) && p.lifecycle !== 'settled') : active && active.lifecycle !== 'settled' ? [active] : []

      if (pendingG.current !== null) {
        window.clearTimeout(pendingG.current)
        pendingG.current = null
        // Hidden views keep their chords so a deep link is one keystroke away during a demo.
        const map: Record<string, string> = { p: QUEUE_PATH, a: '/approve', l: '/netstats', r: '/redteam', u: '/trust', n: '/network', t: '/tokens' }
        const to = map[e.key.toLowerCase()]
        if (to) {
          e.preventDefault()
          s.navigate(to)
          return
        }
      }

      switch (e.key) {
        case 'g':
          pendingG.current = window.setTimeout(() => (pendingG.current = null), 800)
          return
        case '/':
          e.preventDefault()
          if (!onPayments) s.navigate(QUEUE_PATH)
          window.dispatchEvent(new Event(FOCUS_SEARCH_EVENT))
          return
        case '?':
          e.preventDefault()
          window.dispatchEvent(new Event(SHORTCUTS_EVENT))
          return
        case 'f':
          e.preventDefault()
          u.setFeedOpen(!u.feedOpen)
          return
        case 't':
          e.preventDefault()
          s.toggle()
          return
        case 'Escape':
          if (u.checked.size) u.clearChecked()
          else if (u.activeId) u.setActive(null)
          else if (u.search) u.setSearch('')
          return
      }

      if (!onPayments) return

      switch (e.key) {
        case 'j':
        case 'ArrowDown': {
          e.preventDefault()
          const next = s.order[Math.min(s.order.length - 1, idx + 1)]
          if (next) u.setActive(next)
          return
        }
        case 'k':
        case 'ArrowUp': {
          e.preventDefault()
          const prev = s.order[Math.max(0, idx <= 0 ? 0 : idx - 1)]
          if (prev) u.setActive(prev)
          return
        }
        case 'Enter':
        case 'o':
          if (u.activeId) {
            e.preventDefault()
            u.open(u.activeId)
          }
          return
        case 'x':
          if (u.activeId) {
            e.preventDefault()
            u.toggleChecked(u.activeId)
          }
          return
        case 'a':
          e.preventDefault()
          if (targets.length === 0) {
            s.navigate('/approve')
            return
          }
          void (async () => {
            for (const p of targets) await s.run(p, 'approve', undefined, { quiet: targets.length > 1 })
            if (targets.length > 1) u.clearChecked()
            s.navigate('/approve')
          })()
          return
        case 'h':
          e.preventDefault()
          void (async () => {
            for (const p of targets) await s.run(p, 'hold', undefined, { quiet: targets.length > 1 })
            if (targets.length > 1) u.clearChecked()
          })()
          return
        case 'v':
          e.preventDefault()
          void (async () => {
            for (const p of targets) await s.run(p, 'verify', undefined, { quiet: targets.length > 1 })
            if (targets.length > 1) u.clearChecked()
          })()
          return
        case 'p':
          if (active && active.lifecycle !== 'settled') {
            e.preventDefault()
            void s.run(active, 'appeal')
          }
          return
        case 'e':
          if (active) {
            e.preventDefault()
            u.setExplainOpen(true)
          }
          return
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
}
