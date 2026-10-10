import { Bot, Calculator, Check, Loader2, Lock, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { AGENT_STEPS } from '@/data/agents'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface AgentActivityPanelProps {
  open: boolean
  onClose: () => void
  /** Restart the animation when this changes (e.g. the selected payment id). */
  runKey?: string
  subjectLabel?: string
}

type StepState = 'done' | 'running' | 'pending'

export function AgentActivityPanel({ open, onClose, runKey, subjectLabel }: AgentActivityPanelProps) {
  const [current, setCurrent] = useState(0)

  useEffect(() => {
    if (!open) return
    setCurrent(0)
    let i = 0
    let timer: ReturnType<typeof setTimeout>
    const tick = () => {
      i += 1
      setCurrent(i)
      if (i < AGENT_STEPS.length) timer = setTimeout(tick, AGENT_STEPS[i]?.durationMs ?? 600)
    }
    timer = setTimeout(tick, AGENT_STEPS[0]?.durationMs ?? 600)
    return () => clearTimeout(timer)
  }, [open, runKey])

  const states = useMemo<StepState[]>(
    () => AGENT_STEPS.map((_, i) => (i < current ? 'done' : i === current ? 'running' : 'pending')),
    [current],
  )
  const allDone = current >= AGENT_STEPS.length

  return (
    <aside
      aria-label="Agent activity"
      aria-hidden={!open}
      className={cn(
        'fixed inset-y-0 right-0 z-40 flex w-[340px] max-w-full flex-col border-l bg-sidebar text-sidebar-foreground shadow-card-hover transition-transform duration-250 ease-[var(--ease-vouch)]',
        open ? 'translate-x-0' : 'translate-x-full',
      )}
    >
      <header className="flex items-center justify-between gap-3 border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="flex size-7 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <Bot className="size-4" aria-hidden="true" />
          </span>
          <div>
            <h2 className="text-sm font-semibold">Agent activity</h2>
            <p className="text-[11px] text-muted-foreground">{subjectLabel ?? 'Screening this week’s invoices'}</p>
          </div>
        </div>
        <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close agent activity">
          <X aria-hidden="true" />
        </Button>
      </header>

      <ol className="flex-1 space-y-1 overflow-y-auto px-3 py-3" aria-live="polite">
        {AGENT_STEPS.map((step, i) => {
          const state = states[i]
          return (
            <li
              key={step.id}
              className={cn(
                'flex gap-3 rounded-lg px-2 py-2 transition-colors duration-200',
                state === 'running' && 'bg-accent',
              )}
            >
              <span
                className={cn(
                  'mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full ring-1 ring-inset',
                  state === 'done' && 'bg-vouched-soft text-vouched ring-vouched-ring',
                  state === 'running' && 'bg-card text-foreground ring-border',
                  state === 'pending' && 'bg-transparent text-muted-foreground/50 ring-border',
                )}
                aria-hidden="true"
              >
                {state === 'done' ? (
                  <Check className="size-3" />
                ) : state === 'running' ? (
                  <Loader2 className="size-3 animate-spin" />
                ) : (
                  <span className="size-1.5 rounded-full bg-current" />
                )}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <p className={cn('text-[13px] font-medium', state === 'pending' && 'text-muted-foreground')}>
                    {step.title}
                  </p>
                  <span className="text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
                    {step.usesModel ? 'AI' : 'Code'}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">
                  <span className="sr-only">{state === 'done' ? 'Done. ' : state === 'running' ? 'In progress. ' : 'Waiting. '}</span>
                  {step.detail}
                </p>
              </div>
            </li>
          )
        })}
      </ol>

      <footer className="space-y-2 border-t px-4 py-3">
        <p className="flex items-start gap-2 text-xs text-foreground/85">
          <Calculator className="mt-0.5 size-3.5 shrink-0 text-vouched" aria-hidden="true" />
          Amounts come from verified calculations, never the AI.
        </p>
        <p className="flex items-start gap-2 text-xs text-muted-foreground">
          <Lock className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
          The model runs on a private server. Invoices never leave your workspace.
        </p>
        <p className="text-[11px] text-muted-foreground" role="status">
          {allDone ? 'All steps complete. Ready for your approval.' : `Step ${Math.min(current + 1, AGENT_STEPS.length)} of ${AGENT_STEPS.length}`}
        </p>
      </footer>
    </aside>
  )
}
