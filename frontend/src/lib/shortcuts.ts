/** Single source of truth for keyboard shortcuts; hints render from this table. */
export const SHORTCUTS = {
  palette: { keys: ['⌘', 'K'], label: 'Command palette' },
  search: { keys: ['/'], label: 'Search' },
  help: { keys: ['?'], label: 'Shortcuts' },
  next: { keys: ['j'], label: 'Next row' },
  prev: { keys: ['k'], label: 'Previous row' },
  open: { keys: ['↵'], label: 'Open detail' },
  close: { keys: ['esc'], label: 'Close' },
  check: { keys: ['x'], label: 'Select row' },
  approve: { keys: ['a'], label: 'Approve selected / vouched' },
  hold: { keys: ['h'], label: 'Hold for a quick check' },
  verify: { keys: ['v'], label: 'Mark as verified' },
  appeal: { keys: ['p'], label: 'Appeal · vendor is fine' },
  explain: { keys: ['e'], label: 'Explain this flag' },
  feed: { keys: ['f'], label: 'Agent feed' },
  theme: { keys: ['t'], label: 'Theme' },
  goPayments: { keys: ['g', 'p'], label: 'Payments' },
  goApprove: { keys: ['g', 'a'], label: 'Approval' },
  goFairness: { keys: ['g', 'f'], label: 'Fairness' },
  goNetwork: { keys: ['g', 'n'], label: 'Network' },
  goRedTeam: { keys: ['g', 'r'], label: 'Red team' },
  goTokens: { keys: ['g', 't'], label: 'Tokens' },
} as const

export type ShortcutId = keyof typeof SHORTCUTS

export function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable || target.getAttribute('role') === 'slider'
}
