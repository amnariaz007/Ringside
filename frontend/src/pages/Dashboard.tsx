import { Link } from 'react-router-dom'
import { api } from '../api'
import { Async, Card, PageHeader, RiskBadge, Stat } from '../components'
import { hoursLeft, money, reasonLabel, relative } from '../format'
import { useLoad } from '../hooks'

export default function Dashboard() {
  const state = useLoad(() => api.dashboard(), [])
  const rings = useLoad(() => api.rings(), [])

  return (
    <>
      <PageHeader title="Overview" subtitle="Juniper Lane Apparel · last 30 days" />
      <Async state={state}>
        {(d) => (
          <>
            <div className="stats">
              <Stat
                label="Money at risk"
                value={money(d.money_at_risk.risky_orders_amount, d.money_at_risk.currency)}
                hint={`${d.money_at_risk.risky_orders_count} risky orders not yet resolved` +
                  (d.money_at_risk.other_currency_orders ? ` (+${d.money_at_risk.other_currency_orders} in other currencies)` : '')}
                tone={d.money_at_risk.risky_orders_count ? 'high' : undefined}
              />
              <Stat
                label="Open disputes"
                value={d.open_disputes.length}
                hint={d.open_disputes[0] ? `next deadline: ${hoursLeft(d.open_disputes[0].hours_left)}` : 'none'}
                tone={d.open_disputes.length ? 'medium' : undefined}
              />
              <Stat
                label="Orders scored"
                value={d.orders_total}
                hint={`${d.level_counts.high} high · ${d.level_counts.medium} medium · ${d.level_counts.low} low`}
              />
              <Stat
                label="Dispute record"
                value={`${d.dispute_record.won}–${d.dispute_record.lost}`}
                hint="won – lost"
              />
            </div>

            <div className="grid-2">
              <Card title="Needs your attention" action={<Link to="/orders?level=high">All high risk →</Link>}>
                {d.recent_risky_orders.length === 0 ? (
                  <p className="empty">No risky orders waiting. Nice.</p>
                ) : (
                  <ul className="list">
                    {d.recent_risky_orders.map((o) => (
                      <li key={o.id}>
                        <Link to={`/orders/${o.id}`} className="list-row">
                          <RiskBadge level={o.level} score={o.score} />
                          <span className="grow">
                            <strong>{o.buyer}</strong>
                            <span className="muted"> · {relative(o.created_at)}</span>
                          </span>
                          <span className="num">{money(o.amount, o.currency)}</span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>

              <Card title="Dispute deadlines" action={<Link to="/disputes">All disputes →</Link>}>
                {d.open_disputes.length === 0 ? (
                  <p className="empty">No open disputes.</p>
                ) : (
                  <ul className="list">
                    {d.open_disputes.map((x) => (
                      <li key={x.id}>
                        <Link to={`/disputes/${x.id}`} className="list-row">
                        <span className={`deadline ${x.hours_left !== null && x.hours_left < 72 ? 'deadline-urgent' : ''}`}>
                          {hoursLeft(x.hours_left)}
                        </span>
                        <span className="grow">
                          <strong>{reasonLabel(x.reason)}</strong>
                          <span className="muted"> · {x.buyer}</span>
                        </span>
                        <span className="num">{money(x.amount, x.currency)}</span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            </div>

            <div className="grid-2">
              <Card title="Fraud rings" action={<Link to="/rings">Open graph →</Link>}>
                <Async state={rings}>
                  {(r) =>
                    r.results.length === 0 ? (
                      <p className="empty">No linked accounts found.</p>
                    ) : (
                      <ul className="list">
                        {r.results.map((ring) => (
                          <li key={ring.id}>
                            <Link to={`/rings?buyer=${ring.id}`} className="list-row list-row-top">
                              <span className="ring-count">{ring.stats.buyers}</span>
                              <span className="grow">{ring.summary}</span>
                            </Link>
                          </li>
                        ))}
                      </ul>
                    )
                  }
                </Async>
              </Card>

              <Card title="Riskiest buyers">
                <ul className="list">
                  {d.riskiest_buyers.map((b) => (
                    <li key={b.payer_id}>
                      <Link to={`/rings?buyer=${b.payer_id}`} className="list-row">
                        <RiskBadge level={b.level} score={b.max_score} />
                        <span className="grow">
                          <strong>{b.name}</strong>
                          <span className="muted"> · {b.orders} order{b.orders === 1 ? '' : 's'}</span>
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </Card>
            </div>
          </>
        )}
      </Async>
    </>
  )
}
