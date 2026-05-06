import React, { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import api from '../api.js'

const NAV = [
  { to: '/', label: 'Dashboard' },
  { to: '/map', label: 'Karte' },
  { to: '/locations', label: 'Orte' },
  { to: '/thresholds', label: 'Schwellwerte' },
  { to: '/horizons', label: 'Horizonte' },
  { to: '/training', label: 'Training' },
  { to: '/config', label: 'Konfiguration' },
  { to: '/progress', label: 'Lernfortschritt' },
  { to: '/accuracy', label: 'Genauigkeit' },
  { to: '/logs', label: 'Logs' },
]

export default function Layout() {
  const [git, setGit] = useState({ branch: '', commit: '' })
  useEffect(() => { api.get('/api/git').then(setGit).catch(() => {}) }, [])
  return (
    <div className="flex min-h-screen bg-gray-50">
      <nav className="w-56 bg-slate-800 text-slate-100 flex flex-col">
        <div className="p-4 border-b border-slate-700">
          <strong>Wetterprojekt</strong>
          <div className="text-xs text-slate-400 mt-1">{git.branch} @ {git.commit}</div>
        </div>
        {NAV.map(n => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.to === '/'}
            className={({ isActive }) =>
              `px-4 py-2 hover:bg-slate-700 ${isActive ? 'bg-slate-700 border-l-4 border-blue-500' : ''}`
            }
          >
            {n.label}
          </NavLink>
        ))}
      </nav>
      <main className="flex-1 p-6 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}
