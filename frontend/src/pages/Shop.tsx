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

/* Order history lives in this browser only (the shop has no buyer accounts). */
interface PastOrder {
  id: string
  at: string
  pending: boolean
  total: string
  lines: { sku: string; name: string; colour: string; image: string; quantity: number; price: string }[]
}
const HISTORY_KEY = 'jl-orders'
const pendingKey = (orderId: string) => `jl-pending:${orderId}`

function readHistory(): PastOrder[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(HISTORY_KEY) ?? '[]')
    return Array.isArray(value) ? (value as PastOrder[]) : []
  } catch {
    return []
  }
}

function rememberOrder(orderId: string, pending: boolean, products: ShopProduct[]): PastOrder[] {
  let history = readHistory()
  try {
    const cart = JSON.parse(sessionStorage.getItem(pendingKey(orderId)) ?? '{}') as Cart
    const lines = products.filter((p) => (cart[p.sku] ?? 0) > 0).map((p) => ({
      sku: p.sku, name: p.name, colour: p.colour, image: p.image, quantity: cart[p.sku], price: p.price,
    }))
    const total = lines.reduce((sum, l) => sum + Number(l.price) * l.quantity, 0).toFixed(2)
    history = [{ id: orderId, at: new Date().toISOString(), pending, total, lines }, ...history.filter((o) => o.id !== orderId)].slice(0, 20)
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history))
    sessionStorage.removeItem(pendingKey(orderId))
  } catch {
    /* storage unavailable (private mode): the purchase still succeeded */
  }
  return history
}

function ProductImage({ product }: { product: ShopProduct }) {
  const [failed, setFailed] = useState(false)
  return (
    <div className="product-photo" style={failed ? { background: product.swatch } : undefined}>
      {!failed && (
        <img src={product.image} alt={`${product.name} in ${product.colour}`} loading="lazy" width={800} height={800}
          onError={() => setFailed(true)} />
      )}
      <span className="product-tag">{product.colour}</span>
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
              // Kept across PayPal's full-page redirect, so the order history knows what was bought.
              try { sessionStorage.setItem(pendingKey(id), JSON.stringify(cartRef.current)) } catch { /* ignore */ }
              return id
            } catch (e) {
              // Show the server's reason (rate limit, checkout closed...) rather than PayPal's generic error.
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
      <p className="notice small">Online checkout is unavailable right now. Please check back soon.</p>
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
  const [history, setHistory] = useState<PastOrder[]>(readHistory)
  const productsRef = useRef<ShopProduct[]>([])
  productsRef.current = info?.products ?? []
  const onPaid = useMemo(() => (orderId: string, pending: boolean) => {
    setHistory(rememberOrder(orderId, pending, productsRef.current))
    setPaid({ orderId, pending })
    setCart({})
  }, [])

  const count = lines.reduce((n, { q }) => n + q, 0)

  // When the browser blocks PayPal's popup, PayPal uses a full-page redirect and
  // sends the buyer back here with ?token=<order id>&PayerID=...; the page (and
  // bag) has reloaded, so finish the payment from the URL ourselves.
  const [finishing, setFinishing] = useState(false)
  const [returnError, setReturnError] = useState('')
  const finished = useRef(false)
  useEffect(() => {
    if (!info || finished.current) return
    const params = new URLSearchParams(window.location.search)
    const token = params.get('token')
    if (!token || !params.get('PayerID')) return
    finished.current = true
    window.history.replaceState(null, '', window.location.pathname)
    setFinishing(true)
    api.shopCapture(token)
      .then((r) => onPaid(r.order_id ?? token, r.status === 'PENDING'))
      .catch((e: unknown) => setReturnError(e instanceof Error ? e.message : 'The payment did not go through.'))
      .finally(() => setFinishing(false))
  }, [info, onPaid])

  return (
    <div className="store">
      <header className="store-head">
        <div className="store-head-inner">
          <a className="store-brand" href="/shop">
            <span className="store-mark" aria-hidden="true">JL</span>
            <span>
              <strong>Juniper Lane</strong>
              <small>Apparel · Austin, Texas</small>
            </span>
          </a>
          <nav className="store-nav" aria-label="Shop">
            <a href="#catalogue">Autumn run</a>
            {history.length > 0 && <a href="#orders">Your orders</a>}
            <a href="#bag-title" className="store-bag-link">
              Bag <span className="store-bag-count" aria-label={`${count} items`}>{count}</span>
            </a>
          </nav>
        </div>
      </header>

      <section className="store-hero">
        <div className="store-hero-inner">
          <span className="eyebrow">Autumn run · small batch</span>
          <h1>Made to be worn in.</h1>
          <p>Four pieces cut and finished in our Austin workshop. Free tracked shipping across the US.</p>
        </div>
      </section>

      <main className="store-main">
        {state.error && <div className="notice notice-error" role="alert">The shop is closed right now: {state.error}</div>}
        {!info && !state.error && <div className="skeleton" aria-busy="true" />}
        {finishing && <div className="notice" role="status">Confirming your payment with PayPal…</div>}
        {returnError && <div className="notice notice-error" role="alert">{returnError}</div>}
        {info && (
          <div className="store-grid">
            <section aria-labelledby="catalogue">
              <div className="store-section-head">
                <h2 id="catalogue">The collection</h2>
                <span className="muted small">{info.products.length} pieces</span>
              </div>
              <div className="products">
                {info.products.map((p) => {
                  const q = cart[p.sku] ?? 0
                  return (
                    <article key={p.sku} className="product">
                      <ProductImage product={p} />
                      <div className="product-body">
                        <div className="product-line">
                          <h3>{p.name}</h3>
                          <span className="num product-price">{money(p.price, info.currency)}</span>
                        </div>
                        <p className="muted small">{p.blurb}</p>
                        {q === 0 ? (
                          <button className="button button-primary" onClick={() => setQty(p.sku, 1)}>Add to bag</button>
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
                  <div className="bag-head">
                    <span className="eyebrow">Checkout</span>
                    <h2 id="bag-title">Your bag</h2>
                  </div>
                  {lines.length === 0 ? (
                    <p className="empty">Nothing here yet.</p>
                  ) : (
                    <>
                      <ul className="bag-lines">
                        {lines.map(({ p, q }) => (
                          <li key={p.sku}>
                            <img src={p.image} alt="" width={44} height={44} />
                            <span className="grow">{p.name}<small className="block muted">{p.colour} · qty {q}</small></span>
                            <span className="num">{money(String(Number(p.price) * q), info.currency)}</span>
                          </li>
                        ))}
                      </ul>
                      <dl className="bag-sums">
                        <dt>Shipping</dt><dd>Free</dd>
                        <dt className="bag-total">Total</dt><dd className="bag-total num">{money(total.toFixed(2), info.currency)}</dd>
                      </dl>
                      <p className="muted small">Ships to the address on your PayPal account.</p>
                    </>
                  )}
                  <div hidden={lines.length === 0}>
                    <Checkout info={info} cart={cart} onPaid={onPaid} />
                  </div>
                  <p className="bag-trust small">Secure checkout with PayPal</p>
                </>
              )}
            </aside>
          </div>
        )}
        {info && history.length > 0 && (
          <section className="store-orders" aria-labelledby="orders">
            <div className="store-section-head">
              <h2 id="orders">Your orders</h2>
              <span className="muted small">{history.length} placed from this browser</span>
            </div>
            <ul className="past-orders">
              {history.map((o) => (
                <li key={o.id} className="past-order">
                  <div className="past-order-head">
                    <div>
                      <span className="eyebrow">Order</span>
                      <code>{o.id}</code>
                    </div>
                    <span className="muted small">{new Date(o.at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}</span>
                    <span className={`pill ${o.pending ? 'pill-partial' : 'pill-protected'}`}>{o.pending ? 'Processing' : 'Paid'}</span>
                    <strong className="num">{money(o.total, info.currency)}</strong>
                  </div>
                  <ul className="bag-lines">
                    {o.lines.map((l) => (
                      <li key={l.sku}>
                        <img src={l.image} alt="" width={44} height={44} />
                        <span className="grow">{l.name}<small className="block muted">{l.colour} · qty {l.quantity}</small></span>
                        <span className="num">{money(String(Number(l.price) * l.quantity), info.currency)}</span>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          </section>
        )}
      </main>

      <footer className="store-foot">
        <div className="store-foot-inner">
          <span>© 2026 Juniper Lane Apparel · Austin, Texas</span>
          <a href="/">Seller sign-in</a>
        </div>
      </footer>
    </div>
  )
}
