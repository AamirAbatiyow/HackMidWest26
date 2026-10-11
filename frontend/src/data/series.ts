/** Deterministic pseudo-series for sparklines (demo only, seeded by key). */
export function series(key: string, n: number, center: number, spread: number): number[] {
  let h = 2166136261
  for (const ch of key) h = Math.imul(h ^ ch.charCodeAt(0), 16777619)
  const out: number[] = []
  for (let i = 0; i < n; i++) {
    h ^= h << 13
    h ^= h >>> 17
    h ^= h << 5
    const r = ((h >>> 0) % 1000) / 1000 - 0.5
    out.push(Math.max(0, center + r * spread))
  }
  return out
}
