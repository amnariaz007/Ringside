import { useState } from 'react'
import type { FormEvent } from 'react'
import { useAuth } from '../auth'
import { RingsArt } from '../visuals'

export default function Login() {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(username, password)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <section className="login-art">
        <div className="brand">
          <img src="/brand/ringside-mark.svg" alt="" width={34} height={34} />
          <span>Ringside</span>
        </div>
        <div>
          <h1>Catch the ring before you ship.</h1>
          <p>
            A fraud and dispute copilot for small PayPal sellers: every order scored with reasons, linked accounts
            exposed, and dispute replies drafted from your own evidence. You approve every action.
          </p>
          <ul className="login-points">
            <li><b>01</b> Explainable risk score on every PayPal order</li>
            <li><b>02</b> Fraud rings found through shared addresses and phones</li>
            <li><b>03</b> Dispute copilot with evidence, guardrails and your sign-off</li>
          </ul>
        </div>
        <p className="login-foot">PayPal sandbox · built for the PayPal AI Hackathon 2026</p>
        <RingsArt className="login-rings" size={520} />
      </section>

      <section className="login-form-wrap">
        <form className="login-form" onSubmit={submit}>
          <div>
            <span className="eyebrow">Seller sign-in</span>
            <h2 style={{ marginTop: 8 }}>Welcome back</h2>
          </div>
          {error && <div className="notice notice-error" role="alert">{error}</div>}
          <label className="field">
            Email
            <input type="email" autoComplete="username" required value={username}
              onChange={(e) => setUsername(e.target.value)} autoFocus />
          </label>
          <label className="field">
            Password
            <input type="password" autoComplete="current-password" required value={password}
              onChange={(e) => setPassword(e.target.value)} />
          </label>
          <button className="button button-primary" type="submit" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
          <p className="muted small">Judges: the demo login is in the Devpost submission.</p>
        </form>
      </section>
    </div>
  )
}
