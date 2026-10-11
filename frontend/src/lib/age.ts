/** Compact age: "14h", "2d", "3w". */
export function formatAge(iso: string, now = Date.now()): string {
  const ms = Math.max(0, now - new Date(iso).getTime())
  const h = Math.floor(ms / 3_600_000)
  if (h < 1) return `${Math.max(1, Math.floor(ms / 60_000))}m`
  if (h < 48) return `${h}h`
  const d = Math.floor(h / 24)
  if (d < 14) return `${d}d`
  return `${Math.floor(d / 7)}w`
}

/** Compact due: "3d", "today", "-2d" (past). */
export function formatDueShort(iso: string, now = new Date()): string {
  const days = Math.round((new Date(iso).getTime() - now.getTime()) / 86_400_000)
  if (days === 0) return 'today'
  if (days < 0) return `${days}d`
  return `${days}d`
}
