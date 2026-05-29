// UserManagement.jsx — Benutzerverwaltung (nur superadmin)
//
// Seite /users — zeigt alle User in einer Tabelle.
// Aktionen: Anlegen, Rolle ändern, Passwort setzen, Deaktivieren/Aktivieren.
// Nur erreichbar für Benutzer mit Rolle "superadmin".

import React, { useEffect, useState } from 'react'
import api from '../api.js'
import { useAuth } from '../context/AuthContext.jsx'

const ROLES = ['superadmin', 'admin', 'operator', 'viewer']

const ROLE_BADGE = {
  superadmin: 'bg-purple-100 text-purple-800',
  admin:      'bg-blue-100   text-blue-800',
  operator:   'bg-green-100  text-green-800',
  viewer:     'bg-gray-100   text-gray-700',
}

const ROLE_DESC = {
  superadmin: 'Alle Rechte + Benutzerverwaltung',
  admin:      'Konfiguration ändern, kein User-Management',
  operator:   'Training/Refresh starten, keine Konfiguration',
  viewer:     'Nur lesen',
}

// ---------------------------------------------------------------------------
// Modal-Wrapper
// ---------------------------------------------------------------------------
function Modal({ title, onClose, children }) {
  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-md">
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-base font-semibold text-gray-800">{title}</h3>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-2xl leading-none w-8 h-8
                       flex items-center justify-center rounded-lg hover:bg-gray-100"
          >
            &times;
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Haupt-Komponente
// ---------------------------------------------------------------------------
export default function UserManagement() {
  const { user: currentUser } = useAuth()
  const [users,    setUsers]    = useState([])
  const [loading,  setLoading]  = useState(true)
  const [error,    setError]    = useState('')
  const [modal,    setModal]    = useState(null)
  const [form,     setForm]     = useState({})
  const [saving,   setSaving]   = useState(false)
  const [formErr,  setFormErr]  = useState('')

  // --- Daten laden ---
  async function load() {
    setError('')
    try {
      const data = await api.get('/api/users')
      setUsers(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load() }, [])

  // --- Modal öffnen ---
  function openCreate() {
    setForm({ username: '', password: '', role: 'viewer' })
    setFormErr('')
    setModal({ type: 'create' })
  }
  function openEdit(u) {
    setForm({ role: u.role, active: u.active === 1 })
    setFormErr('')
    setModal({ type: 'edit', user: u })
  }
  function openPassword(u) {
    setForm({ password: '' })
    setFormErr('')
    setModal({ type: 'password', user: u })
  }

  // --- Aktionen ---
  async function handleCreate() {
    if (!form.username?.trim() || !form.password || !form.role) {
      setFormErr('Alle Felder ausfüllen'); return
    }
    if (form.password.length < 8) {
      setFormErr('Passwort mindestens 8 Zeichen'); return
    }
    setSaving(true); setFormErr('')
    try {
      await api.post('/api/users', {
        username: form.username.trim(),
        password: form.password,
        role:     form.role,
      })
      await load()
      setModal(null)
    } catch (e) { setFormErr(e.message) }
    finally     { setSaving(false) }
  }

  async function handleEdit() {
    setSaving(true); setFormErr('')
    try {
      await api.patch(`/api/users/${modal.user.id}`, {
        role:   form.role,
        active: form.active ? 1 : 0,
      })
      await load()
      setModal(null)
    } catch (e) { setFormErr(e.message) }
    finally     { setSaving(false) }
  }

  async function handlePassword() {
    if (!form.password || form.password.length < 8) {
      setFormErr('Passwort mindestens 8 Zeichen'); return
    }
    setSaving(true); setFormErr('')
    try {
      await api.post(`/api/users/${modal.user.id}/password`, { password: form.password })
      setModal(null)
    } catch (e) { setFormErr(e.message) }
    finally     { setSaving(false) }
  }

  async function handleToggleActive(u) {
    const action = u.active ? 'deaktivieren' : 'aktivieren'
    if (u.active && !confirm(`Benutzer "${u.username}" wirklich ${action}?`)) return
    try {
      if (u.active) {
        await api.delete(`/api/users/${u.id}`)
      } else {
        await api.patch(`/api/users/${u.id}`, { active: 1 })
      }
      await load()
    } catch (e) { setError(e.message) }
  }

  // --- Zugriffsprüfung ---
  if (currentUser?.role !== 'superadmin') {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-red-600 text-sm font-medium">
          🔒 Diese Seite ist nur für Superadmins zugänglich.
        </div>
      </div>
    )
  }

  // --- Render ---
  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">Benutzerverwaltung</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            User anlegen, Rollen vergeben, Zugänge verwalten
          </p>
        </div>
        <button
          onClick={openCreate}
          className="bg-blue-600 hover:bg-blue-500 text-white text-sm
                     font-medium px-4 py-2 rounded-lg transition-colors"
        >
          + Neuer Benutzer
        </button>
      </div>

      {/* Rollen-Legende */}
      <div className="grid grid-cols-2 gap-2 mb-6">
        {ROLES.map(r => (
          <div key={r} className="flex items-center gap-2 bg-white rounded-lg
                                   border px-3 py-2 text-sm">
            <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${ROLE_BADGE[r]}`}>
              {r}
            </span>
            <span className="text-gray-500 text-xs">{ROLE_DESC[r]}</span>
          </div>
        ))}
      </div>

      {error && (
        <div className="mb-4 bg-red-50 border border-red-200 text-red-700
                        rounded-lg px-4 py-2 text-sm">
          {error}
        </div>
      )}

      {/* Tabelle */}
      {loading ? (
        <div className="text-gray-500 text-sm animate-pulse">Lade Benutzerliste…</div>
      ) : (
        <div className="bg-white rounded-xl shadow-sm border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  Benutzer
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  Rolle
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider hidden md:table-cell">
                  Letzter Login
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  Status
                </th>
                <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  Aktionen
                </th>
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id} className="border-b last:border-0 hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3">
                    <div className="font-medium text-gray-800 flex items-center gap-1">
                      {u.username}
                      {u.username === currentUser?.username && (
                        <span className="text-xs text-blue-500 font-normal">(du)</span>
                      )}
                    </div>
                    <div className="text-xs text-gray-400">
                      ID {u.id} · seit {u.created_at?.slice(0, 10)}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`inline-block px-2 py-0.5 rounded-full text-xs
                                      font-medium ${ROLE_BADGE[u.role] || 'bg-gray-100 text-gray-700'}`}>
                      {u.role}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs hidden md:table-cell">
                    {u.last_login
                      ? u.last_login.slice(0, 16).replace('T', ' ') + ' UTC'
                      : '—'
                    }
                  </td>
                  <td className="px-4 py-3">
                    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium
                                      ${u.active
                                        ? 'bg-green-100 text-green-700'
                                        : 'bg-red-100   text-red-600'
                                      }`}>
                      {u.active ? 'Aktiv' : 'Inaktiv'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-3">
                      <button
                        onClick={() => openEdit(u)}
                        className="text-blue-600 hover:text-blue-800 text-xs font-medium"
                      >
                        Bearbeiten
                      </button>
                      <button
                        onClick={() => openPassword(u)}
                        className="text-gray-500 hover:text-gray-700 text-xs font-medium"
                      >
                        Passwort
                      </button>
                      <button
                        onClick={() => handleToggleActive(u)}
                        disabled={u.username === currentUser?.username}
                        className={`text-xs font-medium disabled:opacity-30 disabled:cursor-not-allowed
                                    ${u.active
                                      ? 'text-red-500 hover:text-red-700'
                                      : 'text-green-600 hover:text-green-800'
                                    }`}
                      >
                        {u.active ? 'Deaktivieren' : 'Aktivieren'}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ---- Modals ---- */}
      {modal?.type === 'create' && (
        <Modal title="Neuen Benutzer anlegen" onClose={() => setModal(null)}>
          <div className="space-y-4">
            <div>
              <label className="block text-sm text-gray-600 mb-1.5 font-medium">Benutzername</label>
              <input type="text" value={form.username}
                onChange={e => setForm(f => ({ ...f, username: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm
                           focus:outline-none focus:ring-2 focus:ring-blue-500"
                autoFocus />
            </div>
            <div>
              <label className="block text-sm text-gray-600 mb-1.5 font-medium">
                Passwort <span className="font-normal text-gray-400">(min. 8 Zeichen)</span>
              </label>
              <input type="password" value={form.password}
                onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm
                           focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-sm text-gray-600 mb-1.5 font-medium">Rolle</label>
              <select value={form.role}
                onChange={e => setForm(f => ({ ...f, role: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm
                           focus:outline-none focus:ring-2 focus:ring-blue-500">
                {ROLES.map(r => (
                  <option key={r} value={r}>{r} — {ROLE_DESC[r]}</option>
                ))}
              </select>
            </div>
            {formErr && <div className="text-red-600 text-sm">{formErr}</div>}
            <div className="flex gap-2 justify-end pt-1">
              <button onClick={() => setModal(null)}
                className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800">
                Abbrechen
              </button>
              <button onClick={handleCreate} disabled={saving}
                className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500
                           text-white rounded-lg disabled:opacity-50 transition-colors">
                {saving ? 'Erstelle…' : 'Erstellen'}
              </button>
            </div>
          </div>
        </Modal>
      )}

      {modal?.type === 'edit' && (
        <Modal title={`Bearbeiten: ${modal.user.username}`} onClose={() => setModal(null)}>
          <div className="space-y-4">
            <div>
              <label className="block text-sm text-gray-600 mb-1.5 font-medium">Rolle</label>
              <select value={form.role}
                onChange={e => setForm(f => ({ ...f, role: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm
                           focus:outline-none focus:ring-2 focus:ring-blue-500">
                {ROLES.map(r => (
                  <option key={r} value={r}>{r} — {ROLE_DESC[r]}</option>
                ))}
              </select>
            </div>
            <div className="flex items-center gap-2">
              <input type="checkbox" id="active_chk" checked={!!form.active}
                onChange={e => setForm(f => ({ ...f, active: e.target.checked }))}
                className="w-4 h-4 rounded" />
              <label htmlFor="active_chk" className="text-sm text-gray-600">
                Konto aktiv
              </label>
            </div>
            {formErr && <div className="text-red-600 text-sm">{formErr}</div>}
            <div className="flex gap-2 justify-end pt-1">
              <button onClick={() => setModal(null)}
                className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800">
                Abbrechen
              </button>
              <button onClick={handleEdit} disabled={saving}
                className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500
                           text-white rounded-lg disabled:opacity-50 transition-colors">
                {saving ? 'Speichere…' : 'Speichern'}
              </button>
            </div>
          </div>
        </Modal>
      )}

      {modal?.type === 'password' && (
        <Modal title={`Passwort ändern: ${modal.user.username}`} onClose={() => setModal(null)}>
          <div className="space-y-4">
            <div>
              <label className="block text-sm text-gray-600 mb-1.5 font-medium">
                Neues Passwort <span className="font-normal text-gray-400">(min. 8 Zeichen)</span>
              </label>
              <input type="password" value={form.password}
                onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm
                           focus:outline-none focus:ring-2 focus:ring-blue-500"
                autoFocus />
            </div>
            {formErr && <div className="text-red-600 text-sm">{formErr}</div>}
            <div className="flex gap-2 justify-end pt-1">
              <button onClick={() => setModal(null)}
                className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800">
                Abbrechen
              </button>
              <button onClick={handlePassword} disabled={saving}
                className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500
                           text-white rounded-lg disabled:opacity-50 transition-colors">
                {saving ? 'Setze…' : 'Passwort setzen'}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
