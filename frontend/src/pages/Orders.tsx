import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import type { Level } from '../api'
import { Async, Card, PageCount, PageHeader, ProtectionBadge, RiskBadge } from '../components'
import { dateTime, money } from '../format'
import { useLoad } from '../hooks'

const FILTERS: { value: Level | ''; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'high', label: 'High' },
  { value: 'medium', label: 'Medium' },
  { value: 'low', label: 'Low' },
]

export default function Orders() {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const level = (params.get('level') ?? '') as Level | ''
  const state = useLoad(() => api.orders(level || undefined), [level])

  return (
    <>
      <PageHeader title="Orders" subtitle="Every PayPal order, scored the moment it arrives">
        <div className="segmented" role="tablist" aria-label="Filter by risk level">
          {FILTERS.map((f) => (
            <button
              key={f.label}
              role="tab"
              aria-selected={level === f.value}
              className={level === f.value ? 'active' : ''}
              onClick={() => setParams(f.value ? { level: f.value } : {})}
            >
              {f.label}
            </button>
          ))}
        </div>
      </PageHeader>
      <Card className="card-flush">
        <Async state={state}>
          {(page) => (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Risk</th>
                    <th>Buyer</th>
                    <th className="hide-sm">Placed</th>
                    <th className="hide-sm">Route</th>
                    <th>Seller Protection</th>
                    <th className="num">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {page.results.map((o) => (
                    <tr key={o.id} className="clickable" onClick={() => navigate(`/orders/${o.id}`)}>
                      <td><RiskBadge level={o.level} score={o.score} /></td>
                      <td>
                        <Link to={`/orders/${o.id}`} onClick={(e) => e.stopPropagation()}>{o.buyer}</Link>
                      </td>
                      <td className="muted hide-sm">{dateTime(o.created_at)}</td>
                      <td className="hide-sm">
                        <span className={o.payer_country && o.ship_country && o.payer_country !== o.ship_country
                          ? 'route-mismatch' : 'muted'}>
                          {o.payer_country || '—'} → {o.ship_country || '—'}
                        </span>
                      </td>
                      <td><ProtectionBadge status={o.seller_protection} /></td>
                      <td className="num">{money(o.amount, o.currency)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {page.results.length === 0 && <p className="empty">No orders at this level.</p>}
              <PageCount shown={page.results.length} total={page.count} />
            </div>
          )}
        </Async>
      </Card>
    </>
  )
}
