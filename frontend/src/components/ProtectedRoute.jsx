// ProtectedRoute.jsx — Route Guard mit optionalem Rollen-Check
//
// Verwendung in App.jsx:
//   <ProtectedRoute>                          → Login erforderlich (jede Rolle)
//   <ProtectedRoute requiredRole="admin">     → admin oder superadmin erforderlich
//   <ProtectedRoute requiredRole="superadmin">→ nur superadmin
//
// Rollenhierarchie: viewer(10) < operator(20) < admin(30) < superadmin(40)

import React from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'

const ROLE_LEVEL = {
  superadmin: 40,
  admin:      30,
  operator:   20,
  viewer:     10,
}

export default function ProtectedRoute({ children, requiredRole }) {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-slate-900">
        <div className="text-slate-400 text-sm animate-pulse">
          Verbindung wird hergestellt…
        </div>
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  if (requiredRole) {
    const userLevel     = ROLE_LEVEL[user.role]     || 0
    const requiredLevel = ROLE_LEVEL[requiredRole]  || 0
    if (userLevel < requiredLevel) {
      return (
        <div className="flex items-center justify-center h-screen bg-gray-50">
          <div className="bg-white rounded-xl shadow p-8 max-w-sm text-center">
            <div className="text-4xl mb-3">🔒</div>
            <div className="text-gray-800 font-semibold mb-1">Kein Zugriff</div>
            <div className="text-gray-500 text-sm">
              Diese Seite erfordert die Rolle <strong>{requiredRole}</strong>.
              <br />Deine aktuelle Rolle: <strong>{user.role}</strong>
            </div>
          </div>
        </div>
      )
    }
  }

  return children
}
