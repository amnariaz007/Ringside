/* Juniper Lane Apparel: the public storefront where a buyer pays with PayPal.
   It is deliberately separate from Ringside (no login, no risk data): a paid
   order reaches Ringside the way any PayPal order would. */

import { useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, api } from '../api'
import type { ShopInfo, ShopProduct } from '../api'
import { money } from '../format'
import { useLoad } from '../hooks'

interface PayPalButtons {
  render: (el: HTMLElement) => Promise<void>
  close?: () => Promise<void>
}
interface PayPalNamespace {
  Buttons: (options: {
    style?: Record<string, string | number>
    createOrder: () => Promise<string>
    onApprove: (data: { orderID: string }, actions: { restart: () => Promise<void> }) => Promise<void>
    onCancel?: () => void
    onError?: (err: unknown) => void
  }) => PayPalButtons
}
declare global {
  interface Window {
    paypal?: PayPalNamespace
  }
}

const SDK_ID = 'paypal-js-sdk'

function loadSdk(clientId: string, currency: string): Promise<PayPalNamespace> {
  if (window.paypal) return Promise.resolve(window.paypal)
  return new Promise((resolve, reject) => {
    const existing = document.getElementById(SDK_ID) as HTMLScriptElement | null
    const script = existing ?? document.createElement('script')
    script.addEventListener('load', () => (window.paypal ? resolve(window.paypal) : reject(new Error('PayPal did not load'))))
    script.addEventListener('error', () => reject(new Error('Could not load PayPal checkout')))
    if (!existing) {
      const params = new URLSearchParams({
        'client-id': clientId, currency, intent: 'capture', components: 'buttons',
        'disable-funding': 'card,credit,paylater,venmo',
      })
      script.id = SDK_ID
      script.src = `https://www.paypal.com/sdk/js?${params}`
      script.async = true
      document.head.appendChild(script)
    }
  })
}

type Cart = Record<string, number>
const MAX_QTY = 5

function Swatch({ product }: { product: ShopProduct }) {
  return (
    <div className="swatch" style={{ background: product.swatch }} aria-hidden="true">
      <svg viewBox="0 0 120 90" preserveAspectRatio="none">
        {Array.from({ length: 9 }, (_, i) => (
          <line key={i} x1={i * 15 - 20} y1="90" x2={i * 15 + 40} y2="0" stroke="#fff" strokeOpacity="0.07" strokeWidth="6" />
        ))}
      </svg>
      <span>{product.colour}</span>
    </div>
  )
}

function Checkout({ info, cart, onPaid }: { info: ShopInfo; cart: Cart; onPaid: (orderId: string, pending: boolean) => void }) {
  const holder = useRef<HTMLDivElement>(null)
  const cartRef = useRef(cart)
  cartRef.current = cart
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!info.checkout_enabled || !holder.current) return
    let buttons: PayPalButtons | null = null
    let alive = true
    loadSdk(info.paypal_client_id, info.currency)
      .then((paypal) => {
        if (!alive || !holder.current) return
        buttons = paypal.Buttons({
          style: { layout: 'vertical', color: 'gold', shape: 'rect', label: 'paypal', height: 44 },
          createOrder: async () => {
            setError('')
            const items = Object.entries(cartRef.current).filter(([, q]) => q > 0).map(([sku, quantity]) => ({ sku, quantity }))
            try {
              const { id } = await api.shopCreateOrder(items)
              return id
            } catch (e) {
              // Show the server's reason (rate limit, sandbox off...) rather than PayPal's generic error.
              setError(e instanceof ApiError ? e.message : 'Could not start the checkout.')
              throw e
            }
          },
          onApprove: async (data, actions) => {
            setBusy(true)
            try {
              const result = await api.shopCapture(data.orderID)
              onPaid(result.order_id ?? data.orderID, result.status === 'PENDING')
            } catch (e) {
              const retry = e instanceof ApiError && (e.body as { retry?: boolean } | undefined)?.retry
              if (retry) return actions.restart()
              setError(e instanceof Error ? e.message : 'The payment did not go through.')
            } finally {
              setBusy(false)
            }
          },
          onCancel: () => setError('Payment cancelled. Your bag is still here.'),
          onError: () => setError((prev) => prev || 'PayPal checkout ran into a problem. Please try again.'),
        })
        return buttons.render(holder.current)
      })
      .catch((e: unknown) => alive && setError(e instanceof Error ? e.message : String(e)))
    return () => {
      alive = false
      void buttons?.close?.()
    }
  }, [info, onPaid])

  if (!info.checkout_enabled) {
    return (
      <p className="notice small">
        Checkout opens when Ringside runs with <code>PAYPAL_MODE=sandbox</code>. In mock mode, orders arrive through the simulator.
      </p>
    )
  }
  return (
    <>
      <div ref={holder} className="paypal-holder" aria-busy={busy} />
      {busy && <p className="muted small">Confirming your payment with PayPal…</p>}
      {error && <p className="notice notice-error small" role="alert">{error}</p>}
    </>
  )
}

export default function Shop() {
  const state = useLoad(() => api.shop(), [])
  const [cart, setCart] = useState<Cart>({})
  const [paid, setPaid] = useState<{ orderId: string; pending: boolean } | null>(null)
  const info = state.data

  const lines = useMemo(
    () => (info?.products ?? []).filter((p) => (cart[p.sku] ?? 0) > 0).map((p) => ({ p, q: cart[p.sku] })),
    [info, cart],
  )
  const total = lines.reduce((sum, { p, q }) => sum + Number(p.price) * q, 0)
  const setQty = (sku: string, q: number) => setCart((c) => ({ ...c, [sku]: Math.max(0, Math.min(MAX_QTY, q)) }))
  // Stable identity so the PayPal buttons aren't re-rendered on every cart change.
  const onPaid = useMemo(() => (orderId: string, pending: boolean) => { setPaid({ orderId, pending }); setCart({}) }, [])

  return (
    <div className="store">
      <div className="store-banner" role="note">
        Sandbox store for the Ringside demo. Pay with a PayPal <b>sandbox</b> buyer account; no real money moves.
      </div>
      <header className="store-head">
        <div>
          <span className="store-mark" aria-hidden="true">JL</span>
          <div>
            <strong>Juniper Lane Apparel</strong>
            <span>{info?.shop.location ?? 'Austin, Texas'} · small-batch clothing</span>
          </div>
        </div>
      </header>

      <main className="store-main">
        {state.error && <div className="notice notice-error" role="alert">The shop is closed right now: {state.error}</div>}
        {!info && !state.error && <div className="skeleton" aria-busy="true" />}
        {info && (
          <div className="store-grid">
            <section aria-labelledby="catalogue">
              <h1 id="catalogue" className="store-title">Made to be worn in.</h1>
              <p className="muted store-sub">Four pieces from our autumn run, cut and finished in Austin.</p>
              <div className="products">
                {info.products.map((p) => {
                  const q = cart[p.sku] ?? 0
                  return (
                    <article key={p.sku} className="product">
                      <Swatch product={p} />
                      <div className="product-body">
                        <div className="product-line">
                          <h2>{p.name}</h2>
                          <span className="num">{money(p.price, info.currency)}</span>
                        </div>
                        <p className="muted small">{p.blurb}</p>
                        {q === 0 ? (
                          <button className="button" onClick={() => setQty(p.sku, 1)}>Add to bag</button>
                        ) : (
                          <div className="stepper" role="group" aria-label={`Quantity of ${p.name}`}>
                            <button onClick={() => setQty(p.sku, q - 1)} aria-label="One fewer">−</button>
                            <span aria-live="polite">{q}</span>
                            <button onClick={() => setQty(p.sku, q + 1)} disabled={q >= MAX_QTY} aria-label="One more">+</button>
                          </div>
                        )}
                      </div>
                    </article>
                  )
                })}
              </div>
            </section>

            <aside className="bag" aria-labelledby="bag-title">
              {paid ? (
                <div className="paid" role="status">
                  <span className="eyebrow">{paid.pending ? 'Payment processing' : 'Payment received'}</span>
                  <h2 id="bag-title">Thank you!</h2>
                  <p>
                    {paid.pending
                      ? <>PayPal is still processing order <code>{paid.orderId}</code>. You'll get an email when it completes; please don't pay again.</>
                      : <>Your PayPal order <code>{paid.orderId}</code> is paid. We'll ship it from Austin and email the tracking number.</>}
                  </p>
                  <button className="button" onClick={() => setPaid(null)}>Keep shopping</button>
                </div>
              ) : (
                <>
                  <h2 id="bag-title">Your bag</h2>
                  {lines.length === 0 ? (
                    <p className="empty">Nothing here yet.</p>
                  ) : (
                    <>
                      <ul className="bag-lines">
                        {lines.map(({ p, q }) => (
                          <li key={p.sku}>
                            <span>{q} × {p.name}</span>
                            <span className="num">{money(String(Number(p.price) * q), info.currency)}</span>
                          </li>
                        ))}
                      </ul>
                      <div className="bag-total">
                        <span>Total</span>
                        <span className="num">{money(total.toFixed(2), info.currency)}</span>
                      </div>
                      <p className="muted small">Ships to the address on your PayPal account.</p>
                    </>
                  )}
                  <div hidden={lines.length === 0}>
                    <Checkout info={info} cart={cart} onPaid={onPaid} />
                  </div>
                </>
              )}
            </aside>
          </div>
        )}
      </main>
      <footer className="store-foot">
        <span>© Juniper Lane Apparel (a fictional shop)</span>
        <a href="/">Seller? Open Ringside →</a>
      </footer>
    </div>
  )
}
