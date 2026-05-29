import React, { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import api from '../api.js'
import { useAuth } from '../context/AuthContext.jsx'

const NAV = [
  { to: '/',             label: 'Dashboard' },
  { to: '/map',          label: 'Karte' },
  { to: '/live',         label: 'Live-Daten' },
  { to: '/atmosphaere',  label: 'Atmosphäre' },
  { to: '/data',         label: 'Datensatz' },
  { to: '/locations',    label: 'Orte' },
  { to: '/thresholds',   label: 'Schwellwerte' },
  { to: '/cell-filters', label: 'Filter-Galerie' },
  { to: '/horizons',     label: 'Horizonte' },
  { to: '/training',     label: 'Training' },
  { to: '/config',       label: 'Konfiguration' },
  { to: '/progress',     label: 'Lernfortschritt' },
  { to: '/accuracy',     label: 'Genauigkeit' },
  { to: '/logs',         label: 'Logs' },
  { to: '/ai-analysis',  label: 'KI-Analyse' },
]

const ROLE_BADGE = {
  superadmin: 'bg-purple-500',
  admin:      'bg-blue-500',
  operator:   'bg-green-500',
  viewer:     'bg-gray-500',
}

export default function Layout() {
  const { user, logout }                  = useAuth()
  const navigate                          = useNavigate()
  const [git, setGit]                     = useState({ branch: '', commit: '' })

  useEffect(() => { api.get('/api/git').then(setGit).catch(() => {}) }, [])

  async function handleLogout() {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="flex min-h-screen bg-gray-50">
      <nav className="w-56 bg-slate-800 text-slate-100 flex flex-col shrink-0">
        {/* Titel */}
        <div className="p-4 border-b border-slate-700">
          <strong>WetterExtended</strong>
          <div className="text-xs text-slate-400 mt-1">{git.branch} @ {git.commit}</div>
        </div>

        {/* Navigation */}
        <div className="flex-1 overflow-y-auto">
          {NAV.map(n => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === '/'}
              className={({ isActive }) =>
                `block px-4 py-2 hover:bg-slate-700 text-sm ${
                  isActive ? 'bg-slate-700 border-l-4 border-blue-500 pl-3' : ''
                }`
              }
            >
              {n.label}
            </NavLink>
          ))}

          {/* Benutzerverwaltung — nur für superadmin sichtbar */}
          {user?.role === 'superadmin' && (
            <NavLink
              to="/users"
              className={({ isActive }) =>
                `block px-4 py-2 hover:bg-slate-700 text-sm ${
                  isActive ? 'bg-slate-700 border-l-4 border-purple-500 pl-3' : ''
                }`
              }
            >
              👥 Benutzer
            </NavLink>
          )}
        </div>

        {/* User-Info + Logout */}
        {user && (
          <div className="p-3 border-t border-slate-700 space-y-2">
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full flex-shrink-0 ${ROLE_BADGE[user.role] || 'bg-gray-500'}`} />
              <div className="min-w-0">
                <div className="text-xs font-medium text-slate-200 truncate">{user.username}</div>
                <div className="text-xs text-slate-500">{user.role}</div>
              </div>
            </div>
            <button
              onClick={handleLogout}
              className="w-full text-xs text-slate-400 hover:text-slate-200
                         hover:bg-slate-700 rounded px-2 py-1 text-left transition-colors"
            >
              Abmelden
            </button>
          </div>
        )}
      </nav>

      <main className="flex-1 p-6 overflow-auto min-w-0">
        <Outlet />
      </main>
    </div>
  )
}
