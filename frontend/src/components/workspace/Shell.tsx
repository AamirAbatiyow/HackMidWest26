import { Outlet } from 'react-router-dom'
import { useGlobalShortcuts } from '@/lib/useGlobalShortcuts'
import { OrchestratorTimeline } from './OrchestratorTimeline'
import { CommandPalette } from './CommandPalette'
import { ExplainDialog } from './ExplainDialog'
import { ShortcutsDialog } from './ShortcutsDialog'
import { StatusBar } from './StatusBar'
import { TopBar } from './TopBar'

/** 36px top bar · orchestrator rail · routed main · 24px status strip. */
export function Shell() {
  useGlobalShortcuts()
  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-background text-foreground">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-1 focus:left-1 focus:z-50 focus:rounded-xs focus:bg-primary focus:px-2 focus:py-1 focus:text-xs focus:text-primary-foreground">
        Skip to content
      </a>
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <OrchestratorTimeline />
        <main id="main" className="flex min-h-0 min-w-0 flex-1">
          <Outlet />
        </main>
      </div>
      <StatusBar />
      <CommandPalette />
      <ShortcutsDialog />
      <ExplainDialog />
    </div>
  )
}
