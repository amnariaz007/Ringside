import { useState } from 'react'
import { api } from '../api'
import { Async, Card, PageCount, PageHeader } from '../components'
import { dateTime } from '../format'
import { useLoad } from '../hooks'

const ACTORS = ['', 'paypal', 'system', 'ai', 'seller'] as const

function summarize(payload: Record<string, unknown>): string {
  if (typeof payload.text === 'string') return payload.text
  return Object.entries(payload)
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') || '—' : String(v)}`)
    .join(' · ')
}

export default function Audit() {
  const [actor, setActor] = useState<string>('')
  const state = useLoad(() => api.audit(actor || undefined), [actor])
  return (
    <>
      <PageHeader title="Audit log" subtitle="Every score, AI output, seller decision and PayPal call, in order">
        <div className="segmented" role="tablist" aria-label="Filter by actor">
          {ACTORS.map((a) => (
            <button key={a || 'all'} role="tab" aria-selected={actor === a} className={actor === a ? 'active' : ''}
              onClick={() => setActor(a)}>
              {a || 'All'}
            </button>
          ))}
        </div>
      </PageHeader>
      <Card className="card-flush">
        <Async state={state}>
          {(page) => (
            <>
            <PageCount shown={page.results.length} total={page.count} />
            <ol className="timeline">
              {page.results.map((e) => (
                <li key={e.id}>
                  <span className={`actor actor-${e.actor}`}>{e.actor}</span>
                  <div className="grow">
                    <p><strong>{e.action}</strong> {e.paypal_id && <code className="muted">{e.paypal_id}</code>}</p>
                    <p className="muted small clamp">{summarize(e.payload)}</p>
                  </div>
                  <time className="muted small">{dateTime(e.created_at)}</time>
                </li>
              ))}
            </ol>
            </>
          )}
        </Async>
      </Card>
    </>
  )
}
