// AuthContext.jsx — WetterExtended JWT-Auth React Context
//
// Strategie:
//   - Access Token lebt nur im React-State (Memory) — kein localStorage
//   - Refresh Token ist HttpOnly Cookie (nur vom Browser gesendet)
//   - Nach Seiten-Reload: automatischer /api/auth/refresh-Aufruf
//   - Access Token wird 5 Minuten vor Ablauf automatisch erneuert
//   - BroadcastChannel: verhindert Token-Rotation Race bei mehreren Tabs
//     → Tab der zuerst refresht teilt neuen Token mit allen anderen Tabs
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

// BroadcastChannel-Name muss über alle Tabs gleich sein
const _BC_CHANNEL = 'we_auth_sync'

export function AuthProvider({ children }) {
  const [user, setUser]       = useState(null)  // { id, username, role }
  const [loading, setLoading] = useState(true)  // true bis erster Refresh-Versuch
  const refreshTimer          = useRef(null)
  const bcRef                 = useRef(null)    // BroadcastChannel Instanz
  const refreshingRef         = useRef(false)   // Verhindert parallele Refresh-Requests

  // JWT-Payload client-seitig dekodieren (kein Verify — nur für exp-Auslesen)
  function _decodePayload(token) {
    try {
      const b64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
      return JSON.parse(atob(b64))
    } catch {
      return null
    }
  }

  // Neuen Token an alle anderen Tabs senden
  function _broadcastToken(accessToken, userData) {
    try {
      bcRef.current?.postMessage({ type: 'token_update', accessToken, user: userData })
    } catch {
      // BroadcastChannel nicht verfügbar — kein Problem, nur kein Tab-Sync
    }
  }

  // Auto-Refresh 5 Minuten vor Ablauf des Access Tokens planen
  function _scheduleRefresh(token) {
    if (refreshTimer.current) clearTimeout(refreshTimer.current)
    const payload = _decodePayload(token)
    if (!payload?.exp) return
    const msUntilExpiry  = payload.exp * 1000 - Date.now()
    const msUntilRefresh = msUntilExpiry - 5 * 60 * 1000
    if (msUntilRefresh > 0) {
      refreshTimer.current = setTimeout(_doRefresh, msUntilRefresh)
    }
  }

  // Token-Refresh via HttpOnly-Cookie
  async function _doRefresh() {
    // Verhindert Race Condition: nur ein gleichzeitiger Refresh-Request pro Tab
    if (refreshingRef.current) return false
    refreshingRef.current = true
    try {
      const r = await fetch('/api/auth/refresh', {
        method: 'POST',
        credentials: 'include',
      })
      if (!r.ok) {
        // 401: Token abgelaufen oder rotiert — Prüfe ob anderer Tab bereits refresht hat
        // (wird über BroadcastChannel mitgeteilt, kurze Wartezeit)
        await new Promise(resolve => setTimeout(resolve, 200))
        // Wenn inzwischen ein Token via Broadcast angekommen ist → kein Logout
        // (setUser wurde bereits durch _handleBroadcast gesetzt)
        // Falls nicht → Logout
        if (!user) {
          _clearAuth()
        }
        return false
      }
      const data = await r.json()
      if (data?.access_token) {
        setToken(data.access_token)
        setUser(data.user)
        _scheduleRefresh(data.access_token)
        _broadcastToken(data.access_token, data.user)
        return true
      }
    } catch {
      // Netzwerkfehler — kein Logout, nur kein Refresh
    } finally {
      refreshingRef.current = false
    }
    return false
  }

  function _clearAuth() {
    setUser(null)
    setToken('')
    if (refreshTimer.current) clearTimeout(refreshTimer.current)
  }

  // BroadcastChannel Nachrichten verarbeiten (kommt von anderen Tabs)
  function _handleBroadcast(event) {
    if (event?.data?.type === 'token_update' && event.data.accessToken) {
      setToken(event.data.accessToken)
      setUser(event.data.user)
      _scheduleRefresh(event.data.accessToken)
    } else if (event?.data?.type === 'logout') {
      _clearAuth()
    }
  }

  // Beim Mount: BroadcastChannel öffnen, Session aus Refresh-Cookie
  // wiederherstellen, onUnauthorized-Callback registrieren
  useEffect(() => {
    // BroadcastChannel für Tab-Synchronisation
    try {
      bcRef.current = new BroadcastChannel(_BC_CHANNEL)
      bcRef.current.onmessage = _handleBroadcast
    } catch {
      // BroadcastChannel nicht unterstützt (sehr alte Browser) — weiter ohne Sync
    }

    onUnauthorized(_clearAuth)
    _doRefresh().finally(() => setLoading(false))

    return () => {
      if (refreshTimer.current) clearTimeout(refreshTimer.current)
      try { bcRef.current?.close() } catch { /* ignore */ }
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
    _broadcastToken(data.access_token, data.user)
    return data.user
  }

  // Logout: Refresh Token serverseitig blacklisten, alle Tabs abmelden
  async function logout() {
    try {
      await fetch('/api/auth/logout', {
        method: 'POST',
        credentials: 'include',
      })
    } catch {
      // Netzwerkfehler beim Logout ignorieren
    }
    // Alle anderen Tabs ebenfalls abmelden
    try {
      bcRef.current?.postMessage({ type: 'logout' })
    } catch { /* ignore */ }
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
