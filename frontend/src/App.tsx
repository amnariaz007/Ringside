import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { api } from './api'
import { useAuth } from './auth'
import { useLoad } from './hooks'
import Landing from './pages/Landing'
import Login from './pages/Login'
import { Icon } from './visuals'

const NAV = [
  { to: '/', label: 'Overview', icon: 'overview', end: true },
  { to: '/orders', label: 'Orders', icon: 'orders' },
  { to: '/rings', label: 'Fraud rings', icon: 'rings' },
  { to: '/disputes', label: 'Disputes', icon: 'disputes' },
  { to: '/audit', label: 'Audit log', icon: 'audit' },
] as const

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
  const { pathname } = useLocation()
  if (checking) return <div className="page"><div className="skeleton" aria-busy="true" /></div>
  // Visitors see the landing page at "/"; any deeper link asks them to sign in first.
  if (!user) return pathname === '/' ? <Landing /> : <Login />
  return <Shell />
}
