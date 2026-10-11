/** Single source of truth for keyboard shortcuts; hints render from this table. */
export const SHORTCUTS = {
  palette: { keys: ['⌘', 'K'], label: 'Commands' },
  search: { keys: ['/'], label: 'Search' },
  help: { keys: ['?'], label: 'Shortcuts' },
  next: { keys: ['j'], label: 'Next' },
  prev: { keys: ['k'], label: 'Previous' },
  open: { keys: ['↵'], label: 'Open' },
  close: { keys: ['esc'], label: 'Close' },
  check: { keys: ['x'], label: 'Select' },
  approve: { keys: ['a'], label: 'Approve' },
  hold: { keys: ['h'], label: 'Hold' },
  verify: { keys: ['v'], label: 'Mark verified' },
  appeal: { keys: ['p'], label: 'Vendor is fine' },
  explain: { keys: ['e'], label: 'Why flagged?' },
  feed: { keys: ['f'], label: 'Orchestrator timeline' },
  theme: { keys: ['t'], label: 'Theme' },
  goPayments: { keys: ['g', 'p'], label: 'Payments' },
  goApprove: { keys: ['g', 'a'], label: 'Approval' },
  goLatency: { keys: ['g', 'l'], label: 'Latency' },
  goRedTeam: { keys: ['g', 'r'], label: 'Red team' },
  goTrust: { keys: ['g', 'u'], label: 'Trust' },
} as const

export type ShortcutId = keyof typeof SHORTCUTS

export function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable || target.getAttribute('role') === 'slider'
}
