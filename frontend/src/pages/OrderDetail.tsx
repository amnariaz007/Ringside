import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import type { Finding, OrderDetail as Order, Shipment } from '../api'
import { Async, Card, PageHeader, ProtectionBadge, ScoreMeter } from '../components'
import { RiskRing } from '../visuals'
import { dateTime, humanize, money, reasonLabel } from '../format'
import { useLoad } from '../hooks'

function EvidenceList({ finding }: { finding: Finding }) {
  const entries = Object.entries(finding.evidence)
  if (finding.rule === 'LINKED_TO_BAD_ACTOR') {
    const linked = finding.evidence.linked_accounts as { payer_id: string; links: string[]; refunds: number; disputes: number }[]
    return (
      <ul className="evidence">
        {linked.map((a) => (
          <li key={a.payer_id}>
            <Link to={`/rings?buyer=${a.payer_id}`}>{a.payer_id}</Link> shares {a.links.map(humanize).join(', ').toLowerCase()}
            {' '}· {a.refunds} refund{a.refunds === 1 ? '' : 's'}, {a.disputes} dispute{a.disputes === 1 ? '' : 's'}
          </li>
        ))}
      </ul>
    )
  }
  return (
    <dl className="evidence-kv">
      {entries.map(([k, v]) => (
        <div key={k}>
          <dt>{humanize(k)}</dt>
          <dd>{String(v)}</dd>
        </div>
      ))}
    </dl>
  )
}

const CARRIERS = ['USPS', 'UPS', 'FEDEX', 'DHL'] as const
const CARRIER_LABEL: Record<string, string> = { USPS: 'USPS', UPS: 'UPS', FEDEX: 'FedEx', DHL: 'DHL' }
const TRACKING_NOTE: Record<string, string> = {
  sent: 'Tracking sent to PayPal.',
  simulated: 'Tracking recorded on the simulated PayPal order.',
  failed: "Saved in Ringside, but PayPal didn't accept the tracking. See the audit log.",
  unchanged: 'Saved.',
}

function ShipmentSummary({ s }: { s: Shipment }) {
  return (
    <dl className="kv">
      <dt>Carrier</dt><dd>{CARRIER_LABEL[s.carrier] ?? s.carrier}</dd>
      <dt>Tracking</dt><dd><code>{s.tracking_number}</code></dd>
      <dt>Shipped</dt><dd>{dateTime(s.shipped_at)}</dd>
      <dt>Status</dt>
      <dd>
        {s.status === 'DELIVERED' && s.delivered_at ? `Delivered ${dateTime(s.delivered_at)}` : humanize(s.status)}
        {s.signature_confirmed && <span className="pill pill-protected inline">signed for</span>}
      </dd>
      <dt>Address</dt><dd>{s.to_paypal_address ? 'The address on the PayPal order' : 'A different address'}</dd>
    </dl>
  )
}

function ShippingCard({ order, onSaved }: { order: Order; onSaved: (o: Order) => void }) {
  const s = order.shipment
  const [editing, setEditing] = useState(false)
  const [carrier, setCarrier] = useState(s?.carrier ?? 'USPS')
  const [tracking, setTracking] = useState(s?.tracking_number ?? '')
  const [delivered, setDelivered] = useState(s?.status === 'DELIVERED')
  const [signed, setSigned] = useState(s?.signature_confirmed ?? false)
  const [toPaypal, setToPaypal] = useState(s?.to_paypal_address ?? true)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const [error, setError] = useState('')

  function resetForm() {
    setCarrier(s?.carrier ?? 'USPS'); setTracking(s?.tracking_number ?? ''); setDelivered(s?.status === 'DELIVERED')
    setSigned(s?.signature_confirmed ?? false); setToPaypal(s?.to_paypal_address ?? true)
  }
  // Reset the form whenever a different order (or a fresh save) comes in.
  // oxlint-disable-next-line react-hooks/exhaustive-deps
  useEffect(resetForm, [s])

  if (!order.can_ship && !s) return null

  async function save(e: FormEvent) {
    e.preventDefault()
    setBusy(true); setError(''); setNote('')
    try {
      const fresh = await api.ship(order.id, {
        carrier, tracking_number: tracking.replace(/\s+/g, '').toUpperCase(), delivered, signature_confirmed: delivered && signed, to_paypal_address: toPaypal,
      })
      setNote(TRACKING_NOTE[fresh.paypal_tracking] ?? 'Saved.')
      setEditing(false)
      onSaved(fresh)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const form = (
    <form className="ship-form" onSubmit={save}>
      <label className="field">Carrier
        <select value={carrier} onChange={(e) => setCarrier(e.target.value)}>
          {CARRIERS.map((c) => <option key={c} value={c}>{CARRIER_LABEL[c]}</option>)}
        </select>
      </label>
      <label className="field">Tracking number
        <input value={tracking} onChange={(e) => setTracking(e.target.value)} required maxLength={60}
          pattern="[A-Za-z0-9\-\s]{6,60}" placeholder="9400100000000000000000" autoComplete="off" spellCheck={false} />
      </label>
      <label className="check"><input type="checkbox" checked={toPaypal} onChange={(e) => setToPaypal(e.target.checked)} />
        Shipped to the address on the PayPal order</label>
      <label className="check"><input type="checkbox" checked={delivered} onChange={(e) => setDelivered(e.target.checked)} />
        The carrier shows it as delivered</label>
      {delivered && (
        <label className="check"><input type="checkbox" checked={signed} onChange={(e) => setSigned(e.target.checked)} />
          Signed for on delivery</label>
      )}
      <div className="button-row">
        <button className="button button-primary" disabled={busy}>{busy ? 'Saving…' : s ? 'Update shipment' : 'Mark as shipped'}</button>
        {s && <button type="button" className="button" onClick={() => { resetForm(); setEditing(false) }}>Cancel</button>}
      </div>
    </form>
  )

  return (
    <Card title="Shipping" action={s && !editing ? <button className="link-button" onClick={() => setEditing(true)}>Edit</button> : undefined}>
      {s && !editing ? <ShipmentSummary s={s} /> : (
        <>
          {!s && <p className="muted small">Add the tracking number. Ringside sends it to PayPal, and it becomes the main evidence if the buyer says the parcel never arrived.</p>}
          {form}
        </>
      )}
      {note && <p className="notice notice-success small" role="status">{note}</p>}
      {error && <p className="notice notice-error small" role="alert">{error}</p>}
    </Card>
  )
}

export default function OrderDetail() {
  const { id = '' } = useParams()
  const state = useLoad(() => api.order(id), [id])
  const [saved, setSaved] = useState<Order | null>(null)
  useEffect(() => setSaved(null), [id])
  const view = saved && String(saved.id) === id ? { ...state, data: saved } : state

  return (
    <Async state={view}>
      {(o) => {
        const a = o.assessment
        return (
          <>
            <PageHeader
              eyebrow="Order"
              title={`${money(o.amount, o.currency)} from ${o.buyer}`}
              subtitle={<>PayPal order <code>{o.paypal_order_id}</code> · {dateTime(o.created_at)}</>}
            >
              <Link to={`/rings?buyer=${o.payer_id}`} className="button">View buyer links</Link>
            </PageHeader>

            <div className="grid-detail">
              <div className="stack">
                {a && (
                  <Card className={`verdict verdict-${a.level}`}>
                    <div className="verdict-head">
                      <span className="eyebrow">Risk verdict</span>
                      <span className="muted small">
                        rules engine {a.engine_version} · text by {a.explanation_source}
                      </span>
                    </div>
                    <div className="verdict-body">
                      <RiskRing score={a.score} level={a.level} size={88} />
                      <div className="grow">
                        <p className={`level-word level-${a.level}`} style={{ fontSize: 14 }}>{a.level} risk</p>
                        <p className="verdict-text">{a.explanation}</p>
                      </div>
                    </div>
                    <ScoreMeter score={a.score} level={a.level} />
                  </Card>
                )}

                <Card title={a && a.findings.length ? `Why: ${a.findings.length} signal${a.findings.length === 1 ? '' : 's'}` : 'Why'}>
                  {!a || a.findings.length === 0 ? (
                    <p className="empty">No warning signs on this order.</p>
                  ) : (
                    <ol className="findings">
                      {a.findings.map((f) => (
                        <li key={f.rule}>
                          <span className="points">+{f.points}</span>
                          <div>
                            <p className="finding-reason">{f.reason}</p>
                            <p className="finding-rule">{f.rule}</p>
                            <EvidenceList finding={f} />
                          </div>
                        </li>
                      ))}
                    </ol>
                  )}
                </Card>
              </div>

              <div className="stack">
                <Card title="Seller Protection">
                  <ProtectionBadge status={o.seller_protection} />
                  <p className="advice">{o.seller_protection_advice}</p>
                </Card>
                <Card title="Order">
                  <dl className="kv">
                    <dt>Buyer</dt><dd>{o.buyer} <span className="muted">({o.payer_id})</span></dd>
                    <dt>Payer country</dt><dd>{o.payer_country || '—'}</dd>
                    <dt>Ships to</dt>
                    <dd>
                      {o.shipping_address ?? '—'}
                      {o.is_reshipper && <span className="pill pill-unprotected inline">forwarder</span>}
                    </dd>
                    <dt>Status</dt><dd>{humanize(o.status)}</dd>
                  </dl>
                </Card>
                <ShippingCard order={o} onSaved={setSaved} />
                {(o.refunds.length > 0 || o.disputes.length > 0) && (
                  <Card title="After the sale">
                    <ul className="plain">
                      {o.refunds.map((r) => (
                        <li key={r.paypal_refund_id}>Refunded {money(r.amount, o.currency)} · {dateTime(r.created_at)}</li>
                      ))}
                      {o.disputes.map((d) => (
                        <li key={d.id}>
                          <Link to={`/disputes/${d.id}`}>Dispute: {reasonLabel(d.reason)}</Link> · {humanize(d.status)}
                        </li>
                      ))}
                    </ul>
                  </Card>
                )}
              </div>
            </div>
          </>
        )
      }}
    </Async>
  )
}
