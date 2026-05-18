import React, { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import api from '../api.js'

const NAV = [
  { to: '/',            label: 'Dashboard' },
  { to: '/map',         label: 'Karte' },
  { to: '/live',        label: 'Live-Daten' },
  { to: '/atmosphaere', label: 'Atmosphäre' },
  { to: '/data',        label: 'Datensatz' },
  { to: '/locations',   label: 'Orte' },
  { to: '/thresholds',  label: 'Schwellwerte' },
  { to: '/horizons',    label: 'Horizonte' },
  { to: '/training',    label: 'Training' },
  { to: '/config',      label: 'Konfiguration' },
  { to: '/progress',    label: 'Lernfortschritt' },
  { to: '/accuracy',    label: 'Genauigkeit' },
  { to: '/logs',        label: 'Logs' },
  { to: '/ai-analysis', label: 'KI-Analyse' },
]

export default function Layout() {
  const [git, setGit] = useState({ branch: '', commit: '' })
  useEffect(() => { api.get('/api/git').then(setGit).catch(() => {}) }, [])

  return (
    <div className="flex min-h-screen bg-gray-50">
      <nav className="w-56 bg-slate-800 text-slate-100 flex flex-col shrink-0">
        <div className="p-4 border-b border-slate-700">
          <strong>WetterExtended</strong>
          <div className="text-xs text-slate-400 mt-1">{git.branch} @ {git.commit}</div>
        </div>
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
        </div>
      </nav>
      <main className="flex-1 p-6 overflow-auto min-w-0">
        <Outlet />
      </main>
    </div>
  )
}
