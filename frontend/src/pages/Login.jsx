// Login.jsx — WetterExtended Login-Seite
//
// Dunkles Slate-Design passend zum Admin-Panel.
// Leitet nach erfolgreichem Login auf "/" weiter.
// Zeigt Lade-Spinner und Fehlermeldungen inline.

import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'

export default function Login() {
  const { login } = useAuth()
  const navigate  = useNavigate()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error,    setError]    = useState('')
  const [loading,  setLoading]  = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!username || !password) return
    setError('')
    setLoading(true)
    try {
      await login(username, password)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err.message || 'Anmeldung fehlgeschlagen')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-900 flex items-center justify-center px-4">
      <div className="bg-slate-800 rounded-2xl shadow-2xl p-8 w-full max-w-sm border border-slate-700">

        {/* Header */}
        <div className="text-center mb-8">
          <div className="text-3xl mb-2">🌩</div>
          <div className="text-xl font-bold text-white tracking-tight">
            WetterExtended
          </div>
          <div className="text-slate-400 text-sm mt-1">Admin Panel</div>
        </div>

        {/* Formular */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">
              Benutzername
            </label>
            <input
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              className="w-full bg-slate-700 border border-slate-600 text-white
                         rounded-lg px-4 py-2.5 text-sm
                         focus:outline-none focus:ring-2 focus:ring-blue-500
                         focus:border-transparent placeholder-slate-500"
              placeholder="admin"
              autoFocus
              autoComplete="username"
              disabled={loading}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">
              Passwort
            </label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              className="w-full bg-slate-700 border border-slate-600 text-white
                         rounded-lg px-4 py-2.5 text-sm
                         focus:outline-none focus:ring-2 focus:ring-blue-500
                         focus:border-transparent placeholder-slate-500"
              placeholder="••••••••"
              autoComplete="current-password"
              disabled={loading}
            />
          </div>

          {/* Fehlermeldung */}
          {error && (
            <div className="bg-red-900/40 border border-red-700/50 text-red-300
                            text-sm rounded-lg px-4 py-2.5">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading || !username || !password}
            className="w-full bg-blue-600 hover:bg-blue-500
                       disabled:opacity-40 disabled:cursor-not-allowed
                       text-white font-semibold rounded-lg py-2.5 text-sm
                       transition-colors mt-2"
          >
            {loading ? (
              <span className="flex items-center justify-center gap-2">
                <span className="inline-block w-4 h-4 border-2 border-white/30
                                 border-t-white rounded-full animate-spin" />
                Anmelden…
              </span>
            ) : (
              'Anmelden'
            )}
          </button>
        </form>

        {/* Footer */}
        <div className="mt-6 text-center text-xs text-slate-600">
          Raspberry Pi 5 · Kärnten
        </div>
      </div>
    </div>
  )
}
