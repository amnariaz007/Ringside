import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { api, UNAUTHORIZED_EVENT } from './api'
import type { SessionUser } from './api'

interface AuthState {
  user: SessionUser | null
  checking: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    // Also sets the CSRF cookie that every POST needs.
    api.me()
      .then((r) => setUser(r.authenticated && r.user ? r.user : null))
      .catch(() => setUser(null))
      .finally(() => setChecking(false))
    const expired = () => setUser(null)
    window.addEventListener(UNAUTHORIZED_EVENT, expired)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, expired)
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const r = await api.login(username, password)
    await api.me() // Django rotates the CSRF token on login; fetch the new cookie
    setUser(r.user)
  }, [])

  const logout = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      setUser(null)
      await api.me().catch(() => undefined)
    }
  }, [])

  return <AuthContext.Provider value={{ user, checking, login, logout }}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
