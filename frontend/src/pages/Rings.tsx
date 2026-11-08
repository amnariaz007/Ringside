import { useMemo } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Background, Controls, Handle, Position, ReactFlow } from '@xyflow/react'
import type { Edge, Node, NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { api } from '../api'
import type { BuyerGraph, GraphNode, GraphNodeType } from '../api'
import { Async, Card, PageHeader, RiskBadge } from '../components'
import { money } from '../format'
import { useLoad } from '../hooks'

// Columns, left to right: shared evidence -> buyers -> orders -> what happened after.
const COLUMN: Record<GraphNodeType, number> = {
  address: 0, phone: 0, email_pattern: 0, buyer: 1, order: 2, refund: 3, dispute: 3,
}
const EVIDENCE = new Set<GraphNodeType>(['address', 'phone', 'email_pattern'])
const COL_X = [0, 300, 600, 880]
const ROW_H = 84

const TYPE_LABEL: Record<GraphNodeType, string> = {
  buyer: 'Buyer', order: 'Order', address: 'Shipping address', phone: 'Phone',
  email_pattern: 'Email pattern', refund: 'Refund', dispute: 'Dispute',
}

type PGData = { node: GraphNode; focus: boolean }

function PGNode({ data }: NodeProps<Node<PGData>>) {
  const navigate = useNavigate()
  const n = data.node
  const target =
    n.type === 'buyer' ? `/rings?buyer=${n.data.payer_id}` : n.type === 'order' ? `/orders/${n.data.order_pk}` : null
  const d = n.data as Record<string, string | number | boolean>
  let sub: string = TYPE_LABEL[n.type]
  let tone = ''
  if (n.type === 'buyer') {
    tone = `tone-${d.level}`
    sub = `${d.refunds} refund${d.refunds === 1 ? '' : 's'} · ${d.disputes} dispute${d.disputes === 1 ? '' : 's'}`
  } else if (n.type === 'order') {
    tone = `tone-${d.level}`
    sub = `risk ${d.score}${d.refunded ? ' · refunded' : ''}${d.disputed ? ' · disputed' : ''}`
  } else if (n.type === 'dispute') {
    tone = d.result === 'lost' ? 'tone-high' : d.result === 'won' ? 'tone-low' : 'tone-medium'
    sub = d.result ? String(d.result) : String(d.outcome || d.status).toLowerCase().replace(/_/g, ' ')
  } else if (n.type === 'refund') {
    tone = 'tone-medium'
  } else if (n.type === 'address' && d.is_reshipper) {
    sub = 'Freight forwarder'
    tone = 'tone-high'
  }
  return (
    <div
      className={`pg-node pg-${n.type} ${tone} ${data.focus ? 'pg-focus' : ''}`}
      // Keyboard users can open orders and re-centre on buyers too.
      role={target ? 'link' : undefined}
      tabIndex={target ? 0 : undefined}
      aria-label={target ? `${TYPE_LABEL[n.type]} ${n.label}: ${sub}` : undefined}
      onKeyDown={(e) => {
        if (target && (e.key === 'Enter' || e.key === ' ')) {
          e.preventDefault()
          navigate(target)
        }
      }}
    >
      <Handle type="target" position={Position.Left} />
      <span className="pg-label">{n.label}</span>
      <span className="pg-sub">{sub}</span>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

const nodeTypes = { pg: PGNode }

function layout(g: BuyerGraph): { nodes: Node<PGData>[]; edges: Edge[] } {
  // Rows follow the buyers: each order sits beside its buyer, each refund or dispute beside its order.
  const byId = new Map(g.nodes.map((n) => [n.id, n]))
  const children = new Map<string, string[]>()
  g.edges.forEach((e) => {
    const t = byId.get(e.target)?.type
    if (t === 'order' || t === 'refund' || t === 'dispute') {
      children.set(e.source, [...(children.get(e.source) ?? []), e.target])
    }
  })
  const y = new Map<string, number>()
  let row = 0
  g.nodes.filter((n) => n.type === 'buyer').forEach((b) => {
    const orders = children.get(b.id) ?? []
    const start = row
    orders.forEach((oid) => {
      const outcomes = children.get(oid) ?? []
      y.set(oid, row)
      outcomes.forEach((cid, k) => y.set(cid, row + k))
      row += Math.max(1, outcomes.length)
    })
    if (orders.length === 0) row += 1
    y.set(b.id, (start + row - 1) / 2)
  })
  // Shared evidence is centred against the buyers it links.
  const evidence = g.nodes.filter((n) => EVIDENCE.has(n.type))
  const offset = (row - evidence.length) / 2
  evidence.forEach((n, i) => y.set(n.id, offset + i))

  const nodes: Node<PGData>[] = g.nodes.map((n) => ({
    id: n.id,
    type: 'pg',
    position: { x: COL_X[COLUMN[n.type]], y: (y.get(n.id) ?? 0) * ROW_H },
    data: { node: n, focus: n.id === `buyer:${g.payer_id}` },
  }))
  const edges: Edge[] = g.edges.map((e) => {
    // Draw evidence -> buyer so every edge flows left to right.
    const flip = EVIDENCE.has(byId.get(e.target)?.type as GraphNodeType)
    return {
      id: e.id,
      source: flip ? e.target : e.source,
      target: flip ? e.source : e.target,
      className: `pg-edge pg-edge-${e.kind}`,
    }
  })
  return { nodes, edges }
}

function GraphView({ payerId }: { payerId: string }) {
  const navigate = useNavigate()
  const state = useLoad(() => api.buyerGraph(payerId), [payerId])
  // Only lay out data that belongs to the current URL, so fitView always fits the right graph.
  const current = state.data?.payer_id === payerId ? state.data : null
  const flow = useMemo(() => (current ? layout(current) : null), [current])

  return (
    <Async state={state}>
      {(g) => (
        <>
          <div className={`ai-summary ${g.is_ring ? 'ai-summary-alert' : ''}`}>
            <span className="ai-tag">{g.summary_source === 'template' ? 'Summary' : 'AI summary'}</span>
            <p>{g.summary}</p>
          </div>
          <div className="graph" role="region" aria-label="Graph of linked buyers, orders and shared details">
            {flow && (
              <ReactFlow
                key={g.payer_id}
                nodes={flow.nodes}
                edges={flow.edges}
                nodeTypes={nodeTypes}
                fitView
                fitViewOptions={{ padding: 0.2 }}
                nodesConnectable={false}
                onNodeClick={(_, node) => {
                  const n = (node.data as PGData).node
                  if (n.type === 'buyer') navigate(`/rings?buyer=${n.data.payer_id}`)
                  if (n.type === 'order') navigate(`/orders/${n.data.order_pk}`)
                }}
              >
                <Background gap={24} size={1} />
                <Controls showInteractive={false} />
              </ReactFlow>
            )}
          </div>
          <div className="legend">
            <span><i className="lg lg-strong" /> shared address or phone (strong link)</span>
            <span><i className="lg lg-plain" /> own address or order</span>
            <span><i className="lg lg-weak" /> email pattern (supporting only)</span>
            <span className="muted">Click a buyer to re-centre, an order to open it.</span>
          </div>
        </>
      )}
    </Async>
  )
}

export default function Rings() {
  const [params] = useSearchParams()
  const rings = useLoad(() => api.rings(), [])
  const selected = params.get('buyer') ?? rings.data?.results[0]?.id ?? null

  return (
    <>
      <PageHeader
        title="Fraud rings"
        subtitle="Buyers joined by a shared shipping address or phone. Email look-alikes are shown but never link accounts on their own."
      />
      <div className="grid-rings">
        <Card title="Detected rings">
          <Async state={rings}>
            {(r) =>
              r.results.length === 0 ? (
                <p className="empty">No linked accounts found.</p>
              ) : (
                <ul className="list">
                  {r.results.map((ring) => (
                    <li key={ring.id}>
                      <Link
                        to={`/rings?buyer=${ring.id}`}
                        className={`list-row list-row-top ${ring.payer_ids.includes(selected ?? '') ? 'selected' : ''}`}
                      >
                        <span className="ring-count">{ring.stats.buyers}</span>
                        <span className="grow">
                          <strong>{ring.stats.buyers} linked accounts</strong>
                          <span className="muted small block">
                            {money(ring.stats.refunded_amount, ring.stats.currency)} refunded ·{' '}
                            {money(ring.stats.lost_amount, ring.stats.currency)} lost
                          </span>
                        </span>
                        <RiskBadge level={ring.stats.max_risk_score >= 60 ? 'high' : ring.stats.max_risk_score >= 30 ? 'medium' : 'low'} score={ring.stats.max_risk_score} />
                      </Link>
                    </li>
                  ))}
                </ul>
              )
            }
          </Async>
        </Card>
        <Card title={selected ? <>Links around <code>{selected}</code></> : 'Graph'}>
          {selected ? <GraphView payerId={selected} /> : <p className="empty">Pick a ring to see its graph.</p>}
        </Card>
      </div>
    </>
  )
}
