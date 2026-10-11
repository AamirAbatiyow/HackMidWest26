import type { Payment, RingNode } from '@/api/types'

export type GraphNodeKind = 'owner' | 'vendor' | 'bank' | 'phone' | 'address'

export interface GraphNode {
  id: string
  label: string
  kind: GraphNodeKind
  /** Risk tone for vendors: vouched = teal, attention = amber, ring = red. */
  tone: 'owner' | 'vouched' | 'attention' | 'ring' | 'fact'
  paymentId?: string
  ring?: boolean
  amount?: number
}

export interface GraphLink {
  source: string
  target: string
  kind: 'pays' | 'shares'
  ring?: boolean
}

export interface VendorGraph {
  nodes: GraphNode[]
  links: GraphLink[]
}

/** Builds the vendor risk map: owner at the center, vendors around, shared facts as link hubs. */
export function buildVendorGraph(payments: Payment[]): VendorGraph {
  const nodes: GraphNode[] = [{ id: 'owner', label: 'KC Wholesale', kind: 'owner', tone: 'owner' }]
  const links: GraphLink[] = []
  const seen = new Map<string, GraphNode>()

  for (const p of payments) {
    const existing = seen.get(p.vendor.id)
    const ring = Boolean(p.ring)
    const tone: GraphNode['tone'] = ring ? 'ring' : p.status === 'vouched' ? 'vouched' : 'attention'
    if (existing) {
      existing.amount = (existing.amount ?? 0) + p.amount
      // Escalate tone if any payment for the vendor is flagged.
      if (tone === 'ring' || (tone === 'attention' && existing.tone === 'vouched')) existing.tone = tone
      continue
    }
    const node: GraphNode = { id: p.vendor.id, label: p.vendor.name, kind: 'vendor', tone, paymentId: p.id, ring, amount: p.amount }
    seen.set(p.vendor.id, node)
    nodes.push(node)
    links.push({ source: 'owner', target: node.id, kind: 'pays' })
  }

  // Fold ring sub-graphs (shared bank / phone / address) into the map.
  for (const p of payments) {
    if (!p.ring) continue
    const idMap = new Map<string, string>()
    for (const n of p.ring.nodes) {
      if (n.kind === 'vendor') {
        const id = n.focus ? p.vendor.id : `ring-${n.id}`
        idMap.set(n.id, id)
        if (!nodes.some((x) => x.id === id)) {
          nodes.push({ id, label: n.label, kind: 'vendor', tone: 'ring', ring: true })
        } else {
          const existing = nodes.find((x) => x.id === id)!
          existing.ring = true
          existing.tone = 'ring'
        }
      } else {
        const id = `fact-${n.id}`
        idMap.set(n.id, id)
        if (!nodes.some((x) => x.id === id)) nodes.push({ id, label: n.label, kind: n.kind as RingNode['kind'] as GraphNodeKind, tone: 'fact', ring: true })
      }
    }
    for (const e of p.ring.edges) {
      const s = idMap.get(e.from)
      const t = idMap.get(e.to)
      if (s && t) links.push({ source: s, target: t, kind: 'shares', ring: true })
    }
  }

  return { nodes, links }
}
