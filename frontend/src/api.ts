// Typed client for the PayGuard Django API. Field names mirror the DRF serializers.

export type Level = 'low' | 'medium' | 'high'

export interface Finding {
  rule: string
  points: number
  reason: string
  evidence: Record<string, unknown>
}

export interface Assessment {
  score: number
  level: Level
  explanation: string
  explanation_source: string
  engine_version: string
  created_at: string
  findings: Finding[]
}

export interface OrderRow {
  id: number
  paypal_order_id: string
  created_at: string
  amount: string
  currency: string
  buyer: string
  payer_id: string
  payer_country: string
  ship_country: string
  seller_protection: string
  score: number | null
  level: Level | null
}

export interface OrderDetail extends OrderRow {
  status: string
  shipping_address: string | null
  is_reshipper: boolean
  seller_protection_advice: string
  assessment: Assessment | null
  refunds: { paypal_refund_id: string; amount: string; created_at: string }[]
  disputes: { id: number; paypal_dispute_id: string; status: string; reason: string }[]
}

export type CopilotAction = 'FIGHT' | 'ACCEPT' | 'PARTIAL_REFUND'

export interface DisputeRow {
  id: number
  paypal_dispute_id: string
  paypal_order_id: string
  buyer: string
  copilot: { status: string; recommendation: CopilotAction | ''; confidence: string } | null
  reason: string
  status: string
  amount: string
  currency: string
  seller_response_due_at: string | null
  outcome: string
  created_at: string
}

export interface EvidenceItem {
  id: string
  kind: string
  title: string
  detail: string
  supports: 'fight' | 'accept' | ''
  data: Record<string, unknown>
}

export interface CopilotCase {
  id: number
  status: 'PREPARING' | 'READY' | 'SUBMITTING' | 'SUBMITTED' | 'FAILED'
  dispute: {
    id: number
    paypal_dispute_id: string
    reason: string
    status: string
    amount: string
    currency: string
    outcome: string
    seller_response_due_at: string | null
    created_at: string
    order_id: number | null
    paypal_order_id: string
    buyer: string
    payer_id: string
  }
  evidence: EvidenceItem[]
  buyer_messages: { id: string; posted_at: string; content: string; untrusted: boolean }[]
  recommendation: CopilotAction
  confidence: 'high' | 'medium' | 'low'
  reasons: { text: string; evidence_ids: string[] }[]
  offer_amount: string | null
  draft_text: string
  draft_source: string
  draft_cited: string[]
  guard_notes: string[]
  decided_action: CopilotAction | ''
  final_text: string
  edited_by_seller: boolean
  approved_at: string | null
  submitted_at: string | null
  error: string
  prepared_at: string | null
}

export interface Dashboard {
  orders_total: number
  level_counts: Record<Level, number>
  money_at_risk: {
    currency: string
    risky_orders_amount: string
    risky_orders_count: number
    other_currency_orders: number
    open_disputes_amount: string
  }
  open_disputes: {
    id: number
    paypal_dispute_id: string
    reason: string
    status: string
    amount: string
    currency: string
    buyer: string
    due_at: string | null
    hours_left: number | null
  }[]
  dispute_record: { won: number; lost: number; other: number }
  riskiest_buyers: { payer_id: string; name: string; max_score: number; level: Level; orders: number }[]
  recent_risky_orders: {
    id: number
    paypal_order_id: string
    buyer: string
    amount: string
    currency: string
    score: number
    level: Level
    created_at: string
  }[]
}

export interface RingStats {
  buyers: number
  orders: number
  refunds: number
  refunded_amount: string
  disputes: number
  disputes_lost: number
  lost_amount: string
  open_high_risk_amount: string
  shared_addresses: number
  shared_phones: number
  shared_email_patterns: number
  max_risk_score: number
  newest_order_at: string
  currency: string
}

export interface Ring {
  id: string
  payer_ids: string[]
  stats: RingStats
  summary: string
  summary_source: string
}

export type GraphNodeType = 'buyer' | 'order' | 'address' | 'phone' | 'email_pattern' | 'refund' | 'dispute'

export interface GraphNode {
  id: string
  type: GraphNodeType
  label: string
  data: Record<string, unknown>
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  kind: string
}

export interface BuyerGraph {
  payer_id: string
  is_ring: boolean
  stats: RingStats
  nodes: GraphNode[]
  edges: GraphEdge[]
  summary: string
  summary_source: string
}

export interface AuditRow {
  id: number
  actor: 'system' | 'ai' | 'seller' | 'paypal'
  action: string
  object_type: string
  object_id: string
  paypal_id: string
  payload: Record<string, unknown>
  created_at: string
}

export interface Page<T> {
  count: number
  results: T[]
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function get<T>(path: string): Promise<T> {
  return request<T>(path)
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response
  try {
    res = await fetch(`/api${path}`, { ...init, headers: { Accept: 'application/json', ...init.headers } })
  } catch {
    throw new ApiError(0, 'Could not reach the Ringside server.')
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail
    } catch {
      /* body wasn't JSON */
    }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
}

export const api = {
  health: () => get<{ ok: boolean; paypal_mode: string; ai_provider: string }>('/health/'),
  dashboard: () => get<Dashboard>('/dashboard/'),
  orders: (level?: Level) => get<Page<OrderRow>>(`/orders/?limit=200${level ? `&level=${level}` : ''}`),
  order: (id: string | number) => get<OrderDetail>(`/orders/${id}/`),
  disputes: () => get<Page<DisputeRow>>('/disputes/?limit=200'),
  rings: () => get<{ results: Ring[] }>('/graph/rings/'),
  buyerGraph: (payerId: string) => get<BuyerGraph>(`/graph/buyers/${encodeURIComponent(payerId)}/`),
  copilot: (disputeId: string | number) => get<CopilotCase>(`/disputes/${disputeId}/copilot/`),
  regenerate: (disputeId: string | number) => post<CopilotCase>(`/disputes/${disputeId}/copilot/regenerate/`),
  submit: (disputeId: string | number, action: CopilotAction, text: string) =>
    post<CopilotCase>(`/disputes/${disputeId}/copilot/submit/`, { action, text, confirm: true }),
  audit: (actor?: string) => get<Page<AuditRow>>(`/audit/?limit=200${actor ? `&actor=${actor}` : ''}`),
}
