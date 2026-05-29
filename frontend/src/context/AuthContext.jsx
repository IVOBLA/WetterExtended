// AuthContext.jsx — WetterExtended JWT-Auth React Context
//
// Strategie:
//   - Access Token lebt nur im React-State (Memory) — kein localStorage
//   - Refresh Token ist HttpOnly Cookie (nur vom Browser gesendet)
//   - Nach Seiten-Reload: automatischer /api/auth/refresh-Aufruf
//   - Access Token wird 5 Minuten vor Ablauf automatisch erneuert
//   - Bei 401 von api.js: User wird ausgeloggt (via onUnauthorized-Callback)

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useRef,
} from 'react'
import { setToken, onUnauthorized } from '../api.js'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser]       = useState(null)  // { id, username, role }
  const [loading, setLoading] = useState(true)  // true bis erster Refresh-Versuch
  const refreshTimer          = useRef(null)

  // JWT-Payload client-seitig dekodieren (kein Verify — nur für exp-Auslesen)
  function _decodePayload(token) {
    try {
      const b64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
      return JSON.parse(atob(b64))
    } catch {
      return null
    }
  }

  // Auto-Refresh 5 Minuten vor Ablauf des Access Tokens planen
  function _scheduleRefresh(token) {
    if (refreshTimer.current) clearTimeout(refreshTimer.current)
    const payload = _decodePayload(token)
    if (!payload?.exp) return
    const msUntilExpiry = payload.exp * 1000 - Date.now()
    const msUntilRefresh = msUntilExpiry - 5 * 60 * 1000
    if (msUntilRefresh > 0) {
      refreshTimer.current = setTimeout(_doRefresh, msUntilRefresh)
    }
  }

  // Token-Refresh via HttpOnly-Cookie
  async function _doRefresh() {
    try {
      const r = await fetch('/api/auth/refresh', {
        method: 'POST',
        credentials: 'include',
      })
      if (!r.ok) {
        _clearAuth()
        return false
      }
      const data = await r.json()
      if (data?.access_token) {
        setToken(data.access_token)
        setUser(data.user)
        _scheduleRefresh(data.access_token)
        return true
      }
    } catch {
      // Netzwerkfehler — kein Logout, nur kein Refresh
    }
    return false
  }

  function _clearAuth() {
    setUser(null)
    setToken('')
    if (refreshTimer.current) clearTimeout(refreshTimer.current)
  }

  // Beim Mount: Session aus Refresh-Cookie wiederherstellen
  // + onUnauthorized-Callback registrieren (wird von api.js bei 401 aufgerufen)
  useEffect(() => {
    onUnauthorized(_clearAuth)
    _doRefresh().finally(() => setLoading(false))
    return () => {
      if (refreshTimer.current) clearTimeout(refreshTimer.current)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Login: POST /api/auth/login → Access Token in Memory, Refresh Cookie setzen
  async function login(username, password) {
    const r = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ username, password }),
    })
    const data = await r.json()
    if (!r.ok) throw new Error(data.error || 'Anmeldung fehlgeschlagen')
    setToken(data.access_token)
    setUser(data.user)
    _scheduleRefresh(data.access_token)
    return data.user
  }

  // Logout: Refresh Token serverseitig blacklisten, lokalen State löschen
  async function logout() {
    try {
      await fetch('/api/auth/logout', {
        method: 'POST',
        credentials: 'include',
      })
    } catch {
      // Netzwerkfehler beim Logout ignorieren
    }
    _clearAuth()
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth() muss innerhalb von <AuthProvider> verwendet werden')
  return ctx
}
