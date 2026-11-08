import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../api'
import type { CopilotAction, CopilotCase, EvidenceItem } from '../api'
import { Async, Card, PageHeader } from '../components'
import { dateTime, humanize, money, reasonLabel } from '../format'
import { useLoad } from '../hooks'

const ACTION_LABEL: Record<CopilotAction, string> = {
  FIGHT: 'Fight with evidence',
  ACCEPT: 'Accept the claim',
  PARTIAL_REFUND: 'Offer a partial refund',
}
const ACTION_SHORT: Record<CopilotAction, string> = { FIGHT: 'Fight', ACCEPT: 'Accept', PARTIAL_REFUND: 'Partial refund' }

function dueIn(iso: string | null): { text: string; urgent: boolean } {
  if (!iso) return { text: 'no deadline', urgent: false }
  const h = (new Date(iso).getTime() - Date.now()) / 3_600_000
  if (h < 0) return { text: 'deadline passed', urgent: true }
  return { text: h < 48 ? `${Math.floor(h)} h to respond` : `${Math.floor(h / 24)} days to respond`, urgent: h < 72 }
}

/** Draft text with [E3] citations turned into chips that point at the evidence list. */
function CitedText({ text }: { text: string }) {
  const parts = text.split(/(\[E\d+\])/g)
  return (
    <p className="cited-text">
      {parts.map((p, i) => {
        const m = p.match(/^\[(E\d+)\]$/)
        return m ? (
          <a key={i} href={`#ev-${m[1]}`} className="cite">{m[1]}</a>
        ) : (
          <span key={i}>{p}</span>
        )
      })}
    </p>
  )
}

function EvidenceList({ items, cited }: { items: EvidenceItem[]; cited: Set<string> }) {
  return (
    <ol className="evidence-list">
      {items.map((e) => (
        <li key={e.id} id={`ev-${e.id}`} className={cited.has(e.id) ? 'is-cited' : ''}>
          <span className="ev-id">{e.id}</span>
          <div className="grow">
            <p className="ev-title">
              {e.title}
              {e.supports === 'fight' && <span className="pill pill-protected inline">supports fighting</span>}
              {e.supports === 'accept' && <span className="pill pill-unprotected inline">weakens a defence</span>}
              {e.internal && <span className="pill pill-none inline">internal · not sent to PayPal or AI</span>}
            </p>
            <p className="muted small">{e.detail}</p>
          </div>
        </li>
      ))}
    </ol>
  )
}

function Copilot({ initial }: { initial: CopilotCase }) {
  const [c, setCase] = useState(initial)
  const [action, setAction] = useState<CopilotAction>(initial.decided_action || initial.recommendation)
  const [text, setText] = useState(initial.final_text || initial.draft_text)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState<'' | 'submit' | 'regenerate'>('')
  const [error, setError] = useState<string | null>(null)
  const [offer, setOffer] = useState(initial.offer_amount ?? '')
  const [confirmRegen, setConfirmRegen] = useState(false)
  const sendButton = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    setCase(initial)
    setAction(initial.decided_action || initial.recommendation)
    setText(initial.final_text || initial.draft_text)
    setOffer(initial.offer_amount ?? '')
    setConfirming(false)
    setConfirmRegen(false)
    setError(null)
  }, [initial])

  const d = c.dispute
  const due = dueIn(d.seller_response_due_at)
  const cited = useMemo(() => new Set(Array.from(text.matchAll(/\[(E\d+)\]/g), (m) => m[1])), [text])
  const sent = c.status === 'SUBMITTED' || c.status === 'SUBMITTING'
  // Read-only once sent, or when PayPal is no longer waiting for the seller.
  const locked = sent || !d.awaiting_seller || c.status === 'NEEDS_DATA'
  const edited = text.trim() !== c.draft_text.trim()
  const changedDecision = edited || action !== c.recommendation

  async function send() {
    setBusy('submit')
    setError(null)
    try {
      setCase(await api.submit(d.id, action, text, String(offer)))
    } catch (e) {
      // A 502 carries the FAILED case (with PayPal's error); show it and keep the seller's text.
      if (e instanceof ApiError && e.status === 502 && e.body && typeof e.body === 'object' && 'status' in e.body) {
        setCase(e.body as CopilotCase)
      } else {
        setError(e instanceof Error ? e.message : String(e))
      }
    } finally {
      setBusy('')
      setConfirming(false)
    }
  }

  async function regenerate() {
    setConfirmRegen(false)
    setBusy('regenerate')
    setError(null)
    try {
      const fresh = await api.regenerate(d.id)
      setCase(fresh)
      setAction(fresh.recommendation)
      setText(fresh.draft_text)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Dispute copilot"
        title={`${reasonLabel(d.reason)} · ${money(d.amount, d.currency)}`}
        subtitle={
          <>
            {d.buyer && <>From {d.buyer} · </>}
            PayPal dispute <code>{d.paypal_dispute_id}</code>
            {d.order_id && <> · <Link to={`/orders/${d.order_id}`}>view order</Link></>}
          </>
        }
      >
        <span className={`deadline-pill ${due.urgent ? 'deadline-urgent' : ''}`}>
          {locked ? `PayPal status: ${humanize(d.status)}${d.outcome ? ` · ${humanize(d.outcome)}` : ''}` : due.text}
        </span>
      </PageHeader>

      {c.status === 'SUBMITTED' && (
        <div className="notice notice-success" role="status" tabIndex={-1} ref={(el) => el?.focus()}>
          <strong>Sent to PayPal</strong> {c.submitted_at && <>on {dateTime(c.submitted_at)}</>}: {ACTION_LABEL[c.decided_action || 'FIGHT'].toLowerCase()}.
          PayPal now shows this dispute as <strong>{humanize(d.status).toLowerCase()}</strong>
          {d.outcome && <> ({humanize(d.outcome).toLowerCase()})</>}.
        </div>
      )}
      {c.status === 'FAILED' && (
        <div className="notice notice-error" role="alert">
          PayPal didn't accept the submission: {c.error || 'unknown error'}. Your text is kept; you can try again.
        </div>
      )}
      {error && c.status !== 'FAILED' && <div className="notice notice-error" role="alert">{error}</div>}
      {c.status === 'NEEDS_DATA' && (
        <div className="notice" role="status">
          This dispute isn't linked to an order Ringside knows yet, so there's no evidence to work from.
          The copilot will prepare it automatically when PayPal sends the order details.
        </div>
      )}
      {!sent && !d.awaiting_seller && c.status !== 'NEEDS_DATA' && (
        <div className="notice" role="status">
          PayPal isn't waiting for your response on this dispute (status: {humanize(d.status).toLowerCase()}), so
          there's nothing to send.
        </div>
      )}

      <div className="grid-detail">
        <div className="stack">
          {c.status !== 'NEEDS_DATA' && <>
          <Card className={`verdict verdict-${c.recommendation === 'FIGHT' ? 'low' : c.recommendation === 'ACCEPT' ? 'high' : 'medium'}`}>
            <div className="verdict-head">
              <span className="muted small">Ringside recommends</span>
              <span className="muted small">decided by rules, not AI · confidence {c.confidence}</span>
            </div>
            <p className="rec-action">
              {ACTION_LABEL[c.recommendation]}
              {c.recommendation === 'PARTIAL_REFUND' && c.offer_amount && <> of {money(c.offer_amount, d.currency)}</>}
            </p>
            <ul className="reasons">
              {c.reasons.map((r, i) => (
                <li key={i}>
                  {r.text}{' '}
                  {r.evidence_ids.map((id) => (
                    <a key={id} href={`#ev-${id}`} className="cite">{id}</a>
                  ))}
                </li>
              ))}
            </ul>
          </Card>

          <Card
            title={sent ? 'What you sent to PayPal' : locked ? 'Prepared response (not sent)' : 'Your response to PayPal'}
            action={
              <span className="muted small">
                {c.draft_source === 'template' ? 'Draft built from evidence' : `AI draft · ${c.draft_source}`}
                {edited && !locked && ' · edited by you'}
              </span>
            }
          >
            {c.guard_notes.length > 0 && (
              <div className="notice guard-note">
                <strong>The AI draft was rejected by Ringside's safety check</strong>, so this draft was built
                directly from the evidence instead:
                <ul>{c.guard_notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
              </div>
            )}
            {locked ? (
              <CitedText text={sent ? c.final_text : c.draft_text} />
            ) : (
              <>
                <label className="sr-only" htmlFor="draft">Response text</label>
                <textarea
                  id="draft"
                  className="draft"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  readOnly={!!busy || confirming}
                  rows={9}
                  maxLength={2000}
                />
                <p className="muted small">
                  {text.length}/2000 · citations like [E3] are for your review and are removed before sending.
                </p>
                <div className="decision">
                  <fieldset className="segmented radio-segmented" disabled={!!busy || confirming}>
                    <legend className="sr-only">Your decision</legend>
                    {(Object.keys(ACTION_SHORT) as CopilotAction[])
                      .filter((a) => a !== 'PARTIAL_REFUND' || c.offer_amount)
                      .map((a) => (
                        <label key={a} className={action === a ? 'active' : ''}>
                          <input type="radio" name="decision" value={a} checked={action === a}
                            onChange={() => setAction(a)} />
                          {ACTION_SHORT[a]}
                          {a === c.recommendation && ' ✓'}
                        </label>
                      ))}
                  </fieldset>
                  {action === 'PARTIAL_REFUND' && (
                    <label className="offer-input">
                      Offer amount ({d.currency})
                      <input type="number" min="0" step={['JPY', 'HUF', 'TWD'].includes(d.currency) ? '1' : '0.01'}
                        value={offer} onChange={(e) => setOffer(e.target.value)} readOnly={!!busy || confirming} />
                      <span className="muted small">must be less than {money(d.amount, d.currency)}; the buyer has to agree</span>
                    </label>
                  )}
                  {action !== c.recommendation && (
                    <p className="warn small">
                      You're choosing differently from the recommendation. Make sure the text matches your decision.
                    </p>
                  )}
                </div>

                {!confirming ? (
                  <>
                  <div className="button-row">
                    <button ref={sendButton} className="button button-primary"
                      disabled={!!busy || text.trim().length < 20} onClick={() => setConfirming(true)}>
                      Review and send to PayPal
                    </button>
                    <button className="button" disabled={!!busy}
                      onClick={() => (changedDecision ? setConfirmRegen(true) : regenerate())}>
                      {busy === 'regenerate' ? 'Regenerating…' : 'Regenerate draft'}
                    </button>
                  </div>
                  {confirmRegen && (
                    <div className="confirm" role="alertdialog" aria-labelledby="regen-title"
                      onKeyDown={(e) => e.key === 'Escape' && setConfirmRegen(false)}>
                      <p id="regen-title">Regenerating replaces your edits and decision with a fresh draft.</p>
                      <div className="button-row">
                        <button className="button button-primary" onClick={regenerate} autoFocus>Replace my edits</button>
                        <button className="button" onClick={() => setConfirmRegen(false)}>Keep my edits</button>
                      </div>
                    </div>
                  )}
                  </>
                ) : (
                  <div className="confirm" role="alertdialog" aria-labelledby="confirm-title"
                    onKeyDown={(e) => {
                      if (e.key === 'Escape' && busy !== 'submit') {
                        setConfirming(false)
                        requestAnimationFrame(() => sendButton.current?.focus())
                      }
                    }}>
                    <p id="confirm-title">
                      <strong>Send "{ACTION_LABEL[action]}"{action === 'PARTIAL_REFUND' && ` of ${money(offer || 0, d.currency)}`} to PayPal?</strong>{' '}
                      PayPal receives your text
                      {action === 'FIGHT' && ' and the tracking number as proof of delivery'}. This can't be undone.
                    </p>
                    <div className="button-row">
                      <button className="button button-primary" disabled={busy === 'submit'} onClick={send} autoFocus>
                        {busy === 'submit' ? 'Sending…' : 'Yes, send to PayPal'}
                      </button>
                      <button className="button" disabled={busy === 'submit'} onClick={() => {
                        setConfirming(false)
                        requestAnimationFrame(() => sendButton.current?.focus())
                      }}>
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </>
            )}
          </Card>
          </>}
        </div>

        <div className="stack">
          <Card title={`Evidence (${c.evidence.length})`}>
            <EvidenceList items={c.evidence} cited={cited} />
          </Card>
          {c.buyer_messages.length > 0 && (
            <Card title="Buyer's message">
              <div className="quarantine">
                <p className="quarantine-label">Untrusted · shown for context only</p>
                {c.buyer_messages.map((m) => (
                  <blockquote key={m.id}>{m.content}</blockquote>
                ))}
                <p className="muted small">
                  Buyer messages never change the recommendation, aren't used as evidence, and any instructions
                  in them are ignored.
                </p>
              </div>
            </Card>
          )}
        </div>
      </div>
    </>
  )
}

export default function DisputeCopilot() {
  const { id = '' } = useParams()
  const state = useLoad(() => api.copilot(id), [id])
  return <Async state={state}>{(c) => <Copilot initial={c} />}</Async>
}
