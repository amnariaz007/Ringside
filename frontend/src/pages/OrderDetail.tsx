import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import type { Finding } from '../api'
import { Async, Card, PageHeader, ProtectionBadge, RiskBadge, ScoreMeter } from '../components'
import { dateTime, humanize, money } from '../format'
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

export default function OrderDetail() {
  const { id = '' } = useParams()
  const state = useLoad(() => api.order(id), [id])

  return (
    <Async state={state}>
      {(o) => {
        const a = o.assessment
        return (
          <>
            <PageHeader
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
                      <RiskBadge level={a.level} score={a.score} />
                      <span className="muted small">
                        rules engine {a.engine_version} · text by {a.explanation_source}
                      </span>
                    </div>
                    <ScoreMeter score={a.score} level={a.level} />
                    <p className="verdict-text">{a.explanation}</p>
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
                {(o.refunds.length > 0 || o.disputes.length > 0) && (
                  <Card title="After the sale">
                    <ul className="plain">
                      {o.refunds.map((r) => (
                        <li key={r.paypal_refund_id}>Refunded {money(r.amount, o.currency)} · {dateTime(r.created_at)}</li>
                      ))}
                      {o.disputes.map((d) => (
                        <li key={d.id}>Dispute: {humanize(d.reason)} · {humanize(d.status)}</li>
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
