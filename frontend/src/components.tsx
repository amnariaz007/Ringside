import type { ReactNode } from 'react'
import type { Level } from './api'
import type { Loadable } from './hooks'

export function RiskBadge({ level, score }: { level: Level | null; score?: number | null }) {
  if (!level) return <span className="badge badge-none">not scored</span>
  return (
    <span className={`badge badge-${level}`}>
      {score !== undefined && score !== null && <strong>{score}</strong>}
      {level}
    </span>
  )
}

export function ProtectionBadge({ status }: { status: string }) {
  const map: Record<string, [string, string]> = {
    ELIGIBLE: ['protected', 'Protected'],
    PARTIALLY_ELIGIBLE: ['partial', 'Partly protected'],
    NOT_ELIGIBLE: ['unprotected', 'Not protected'],
  }
  const [cls, label] = map[status] ?? ['none', 'Unknown']
  return <span className={`pill pill-${cls}`}>{label}</span>
}

export function ScoreMeter({ score, level }: { score: number; level: Level }) {
  return (
    <div className="meter" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={score}>
      <div className={`meter-fill meter-${level}`} style={{ width: `${score}%` }} />
      <span className="meter-tick" style={{ left: '30%' }} />
      <span className="meter-tick" style={{ left: '60%' }} />
    </div>
  )
}

export function Card({ title, action, children, className = '' }: {
  title?: ReactNode
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`card ${className}`}>
      {(title || action) && (
        <header className="card-head">
          {title && <h2>{title}</h2>}
          {action}
        </header>
      )}
      {children}
    </section>
  )
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: Level }) {
  return (
    <div className={`stat ${tone ? `stat-${tone}` : ''}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      {hint && <span className="stat-hint">{hint}</span>}
    </div>
  )
}

/** Shows loading / error states so pages only render real data. */
export function Async<T>({ state, children }: { state: Loadable<T>; children: (data: T) => ReactNode }) {
  if (state.error) {
    if (state.status === 404) return <div className="notice">Not found: {state.error}.</div>
    const serverDown = state.status === 0 || (state.status ?? 0) >= 500
    return (
      <div className="notice notice-error" role="alert">
        Couldn't load data: {state.error}
        {serverDown && ' Check that the backend is running.'}
      </div>
    )
  }
  if (state.loading && !state.data) return <div className="skeleton" aria-busy="true" />
  return <>{state.data !== null && children(state.data)}</>
}

/** "Showing 200 of 340": never let a page limit silently hide rows. */
export function PageCount({ shown, total }: { shown: number; total: number }) {
  if (total <= shown) return null
  return <p className="muted small page-count">Showing the newest {shown} of {total}.</p>
}

export function PageHeader({ title, subtitle, eyebrow, children }: {
  title: string
  subtitle?: ReactNode
  eyebrow?: string
  children?: ReactNode
}) {
  return (
    <div className="page-header">
      <div>
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <h1>{title}</h1>
        {subtitle && <p className="muted">{subtitle}</p>}
      </div>
      {children}
    </div>
  )
}

export function Figures({ children }: { children: ReactNode }) {
  return <div className="figures">{children}</div>
}

export function Figure({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: Level }) {
  return (
    <div className={`figure ${tone ? `figure-${tone}` : ''}`}>
      <span className="figure-label">{label}</span>
      <span className="figure-value">{value}</span>
      {hint && <span className="figure-hint">{hint}</span>}
    </div>
  )
}
