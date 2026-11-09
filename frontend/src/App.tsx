import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { api } from './api'
import { useAuth } from './auth'
import { useLoad } from './hooks'
import Login from './pages/Login'
import { Icon } from './visuals'

const NAV = [
  { to: '/', label: 'Overview', icon: 'overview', end: true },
  { to: '/orders', label: 'Orders', icon: 'orders' },
  { to: '/rings', label: 'Fraud rings', icon: 'rings' },
  { to: '/disputes', label: 'Disputes', icon: 'disputes' },
  { to: '/audit', label: 'Audit log', icon: 'audit' },
] as const

const DEMO_EVENTS = [
  { key: 'normal', label: 'Normal order' },
  { key: 'scammer', label: 'Risky order' },
  { key: 'ring', label: 'Fraud-ring order' },
  { key: 'dispute', label: 'Buyer dispute' },
] as const

/** Plays a simulated PayPal event through the real pipeline, then opens what it produced. */
function DemoEvents() {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  async function run(key: string, action: () => Promise<{ go: string }>) {
    setBusy(key); setError('')
    try {
      const { go } = await action()
      window.location.assign(go) // full reload, so every list shows the new data
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setBusy('')
    }
  }

  return (
    <div className="demo-events">
      <button className="demo-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
        Demo events <span aria-hidden="true">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="demo-list">
          {DEMO_EVENTS.map((e) => (
            <button key={e.key} disabled={busy !== ''} onClick={() => void run(e.key, () => api.demoPlay(e.key))}>
              {busy === e.key ? 'Arriving…' : e.label}
            </button>
          ))}
          <button className="demo-reset" disabled={busy !== ''}
            onClick={() => window.confirm('Reset the demo? This deletes all orders, disputes and the audit log, then rebuilds the 30-day history.')
              && void run('reset', () => api.demoReset())}>
            {busy === 'reset' ? 'Resetting…' : 'Reset demo data'}
          </button>
          {error && <span className="demo-error" role="alert">{error}</span>}
        </div>
      )}
    </div>
  )
}

function Shell() {
  const { user, logout } = useAuth()
  const health = useLoad(() => api.health(), [])
  const dash = useLoad(() => api.dashboard(), [])
  const openDisputes = dash.data?.open_disputes.length ?? 0

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <img src="/brand/ringside-mark.svg" alt="" width={30} height={30} />
          <span>Ringside</span>
        </div>
        <nav aria-label="Main">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={'end' in n} className={({ isActive }) => (isActive ? 'active' : '')}>
              <Icon name={n.icon} />
              {n.label}
              {n.to === '/disputes' && openDisputes > 0 && (
                <span className="nav-count" aria-label={`${openDisputes} open`}>{openDisputes}</span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="shop-card">
            <strong>Juniper Lane Apparel</strong>
            <span>Austin, Texas · USD</span>
            <a href="/shop" target="_blank" rel="noreferrer">Open the shop ↗</a>
          </div>
          {health.data?.demo_controls && <DemoEvents />}
          {health.data && (
            <span className="env">
              PAYPAL <b>{health.data.paypal_mode === 'mock' ? 'demo data' : 'connected'}</b> · AI <b>{health.data.ai_provider}</b>
            </span>
          )}
          {user && (
            <button className="logout" onClick={() => void logout()}>
              Sign out {user.username}
            </button>
          )}
        </div>
      </aside>
      <main className="main">
        <div className="page">
          <Outlet />
        </div>
      </main>
    </div>
  )
}

export default function App() {
  const { user, checking } = useAuth()
  if (checking) return <div className="page"><div className="skeleton" aria-busy="true" /></div>
  return user ? <Shell /> : <Login />
}
