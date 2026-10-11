const usd = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
})

const usdCents = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

export function formatMoney(amount: number, opts?: { cents?: boolean }): string {
  return opts?.cents ? usdCents.format(amount) : usd.format(amount)
}

export function formatDate(iso: string, opts?: Intl.DateTimeFormatOptions): string {
  const d = new Date(iso)
  return d.toLocaleDateString('en-US', opts ?? { month: 'short', day: 'numeric' })
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

/** "Due Fri, Oct 16" style with a relative hint. */
export function describeDue(iso: string, now = new Date()): string {
  const due = new Date(iso)
  const days = Math.round((due.getTime() - now.getTime()) / 86_400_000)
  const label = due.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
  if (days < 0) return `Due ${label} · ${Math.abs(days)}d past`
  if (days === 0) return `Due today · ${label}`
  if (days === 1) return `Due tomorrow · ${label}`
  return `Due ${label} · in ${days}d`
}

export function formatPercent(fraction: number, digits = 0): string {
  return `${(fraction * 100).toFixed(digits)}%`
}

export function formatInt(n: number): string {
  return new Intl.NumberFormat('en-US').format(n)
}

export function truncateMiddle(s: string, head = 10, tail = 8): string {
  if (s.length <= head + tail + 1) return s
  return `${s.slice(0, head)}…${s.slice(-tail)}`
}

export function pluralize(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`
}
