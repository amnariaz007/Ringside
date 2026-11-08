import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { Async, Card, PageCount, PageHeader } from '../components'
import { dateTime, humanize, money, reasonLabel } from '../format'
import { useLoad } from '../hooks'

function deadline(iso: string | null): { text: string; urgent: boolean } {
  if (!iso) return { text: '—', urgent: false }
  const h = (new Date(iso).getTime() - Date.now()) / 3_600_000
  if (h < 0) return { text: 'overdue', urgent: true }
  return { text: h < 48 ? `${Math.floor(h)} h left` : `${Math.floor(h / 24)} days left`, urgent: h < 72 }
}

export default function Disputes() {
  const state = useLoad(() => api.disputes(), [])
  const navigate = useNavigate()
  return (
    <>
      <PageHeader
        title="Disputes"
        subtitle="Evidence, a recommendation and a drafted reply for every dispute. Nothing is sent until you approve it."
      />
      <Card className="card-flush">
        <Async state={state}>
          {(page) => (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Reason</th>
                    <th>Copilot</th>
                    <th>Status</th>
                    <th>Respond by</th>
                    <th className="hide-sm">Opened</th>
                    <th className="num">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {page.results.map((d) => {
                    const dl = deadline(d.seller_response_due_at)
                    return (
                      <tr key={d.id} className="clickable" onClick={() => navigate(`/disputes/${d.id}`)}>
                        <td>
                          <Link to={`/disputes/${d.id}`} onClick={(e) => e.stopPropagation()}>
                            <strong>{reasonLabel(d.reason)}</strong>
                          </Link>
                          <div className="muted small">{d.buyer} · <code>{d.paypal_dispute_id}</code></div>
                        </td>
                        <td>
                          {!d.copilot ? <span className="muted small">not started</span>
                            : d.copilot.status === 'READY' ? (
                              <span className="pill pill-partial">Ready: {humanize(d.copilot.recommendation)}</span>
                            ) : (
                              <span className="pill pill-none">{humanize(d.copilot.status)}</span>
                            )}
                        </td>
                        <td>{d.outcome ? humanize(d.outcome) : humanize(d.status)}</td>
                        <td><span className={`deadline ${dl.urgent ? 'deadline-urgent' : ''}`}>{dl.text}</span></td>
                        <td className="muted hide-sm">{dateTime(d.created_at)}</td>
                        <td className="num">{money(d.amount, d.currency)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              {page.results.length === 0 && <p className="empty">No disputes. Long may it last.</p>}
              <PageCount shown={page.results.length} total={page.count} />
            </div>
          )}
        </Async>
      </Card>
    </>
  )
}
