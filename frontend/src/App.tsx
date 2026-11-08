import { NavLink, Outlet } from 'react-router-dom'
import { api } from './api'
import { useLoad } from './hooks'

const NAV = [
  { to: '/', label: 'Overview', end: true },
  { to: '/orders', label: 'Orders' },
  { to: '/rings', label: 'Fraud rings' },
  { to: '/disputes', label: 'Disputes' },
  { to: '/audit', label: 'Audit log' },
]

export default function App() {
  const health = useLoad(() => api.health(), [])
  const mock = health.data?.paypal_mode === 'mock'

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <img src="/brand/ringside-mark.svg" alt="" width={28} height={28} />
          <span>Ringside</span>
        </div>
        <nav aria-label="Main">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => (isActive ? 'active' : '')}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className="muted small">Fraud & dispute copilot for PayPal sellers</span>
          {health.data && (
            <span className={`env ${mock ? 'env-mock' : 'env-live'}`}
              title="Simulated data is labelled honestly; sandbox mode calls PayPal's sandbox API.">
              PayPal: {health.data.paypal_mode} · AI: {health.data.ai_provider}
            </span>
          )}
        </div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  )
}
