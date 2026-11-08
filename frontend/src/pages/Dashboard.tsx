import { Link } from 'react-router-dom'
import { api } from '../api'
import type { Dashboard as DashboardData } from '../api'
import { Async, Card, Figure, Figures } from '../components'
import { hoursLeft, money, reasonLabel, relative } from '../format'
import { useLoad } from '../hooks'
import { RingsArt, RiskRing } from '../visuals'

function greeting(): string {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

/** One plain sentence about what needs the seller today. */
function headline(d: DashboardData): string {
  const parts: string[] = []
  const risky = d.money_at_risk.risky_orders_count
  if (risky) parts.push(`${risky} order${risky === 1 ? '' : 's'} worth ${money(d.money_at_risk.risky_orders_amount, d.money_at_risk.currency)} need a decision before you ship`)
  const next = d.open_disputes[0]
  if (next) parts.push(`a dispute is due in ${hoursLeft(next.hours_left).replace(' left', '')}`)
  if (!parts.length) return 'Nothing needs you right now. Every order is low risk and no disputes are open.'
  const s = parts.join(', and ')
  return s.charAt(0).toUpperCase() + s.slice(1) + '.'
}

export default function Dashboard() {
  const state = useLoad(() => api.dashboard(), [])
  const rings = useLoad(() => api.rings(), [])
  const today = new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })

  return (
    <Async state={state}>
      {(d) => (
        <>
          <section className="hero">
            <RingsArt className="hero-rings" size={380} />
            <span className="eyebrow">{today}</span>
            <h1>{greeting()}, Juniper Lane.</h1>
            <p>{headline(d)}</p>
            <div className="hero-actions">
              {d.recent_risky_orders[0] && (
                <Link className="button button-primary" to={`/orders/${d.recent_risky_orders[0].id}`}>
                  Review riskiest order
                </Link>
              )}
              {d.open_disputes[0] && (
                <Link className="button" to={`/disputes/${d.open_disputes[0].id}`}>Open dispute copilot</Link>
              )}
              <Link className="button" to="/rings">See fraud rings</Link>
            </div>
          </section>

          <Figures>
            <Figure label="Money at risk" tone={d.money_at_risk.risky_orders_count ? 'high' : undefined}
              value={money(d.money_at_risk.risky_orders_amount, d.money_at_risk.currency)}
              hint={`${d.money_at_risk.risky_orders_count} unresolved risky order${d.money_at_risk.risky_orders_count === 1 ? '' : 's'}` +
                (d.money_at_risk.other_currency_orders ? ` · +${d.money_at_risk.other_currency_orders} in other currencies` : '')} />
            <Figure label="Open disputes" tone={d.open_disputes.length ? 'medium' : undefined} value={d.open_disputes.length}
              hint={d.open_disputes[0] ? `next due: ${hoursLeft(d.open_disputes[0].hours_left)}` : 'none open'} />
            <Figure label="Orders scored" value={d.orders_total}
              hint={`${d.level_counts.high} high · ${d.level_counts.medium} medium · ${d.level_counts.low} low`} />
            <Figure label="Dispute record" value={`${d.dispute_record.won}–${d.dispute_record.lost}`} hint="won – lost" />
          </Figures>

          <div className="grid-2">
            <Card title="Hold before shipping" action={<Link to="/orders?level=high">All high risk →</Link>}>
              {d.recent_risky_orders.length === 0 ? (
                <p className="empty">No risky orders waiting.</p>
              ) : (
                <ul className="list">
                  {d.recent_risky_orders.map((o) => (
                    <li key={o.id}>
                      <Link to={`/orders/${o.id}`} className="list-row">
                        <RiskRing score={o.score} level={o.level} size={34} />
                        <span className="grow">
                          <strong>{o.buyer}</strong>
                          <span className="muted block small">placed {relative(o.created_at)}</span>
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
                          <span className="muted block small">{x.buyer}</span>
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
              {d.riskiest_buyers.length === 0 ? (
                <p className="empty">No risky buyers.</p>
              ) : (
                <ul className="list">
                  {d.riskiest_buyers.map((b) => (
                    <li key={b.payer_id}>
                      <Link to={`/rings?buyer=${b.payer_id}`} className="list-row">
                        <RiskRing score={b.max_score} level={b.level} size={34} />
                        <span className="grow">
                          <strong>{b.name}</strong>
                          <span className="muted block small">{b.orders} order{b.orders === 1 ? '' : 's'}</span>
                        </span>
                        <span className={`level-word level-${b.level}`}>{b.level}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </>
      )}
    </Async>
  )
}
