import React, { useEffect, useState } from 'react'
import api from '../api.js'

export default function Locations() {
  const [list, setList] = useState([])
  const [msg, setMsg] = useState('')
  const [loading, setLoading] = useState(true)
  const [apiError, setApiError] = useState(false)

  useEffect(() => {
    api.get('/api/locations')
      .then(d => { setList(d.watchlist || []); setApiError(false) })
      .catch(() => setApiError(true))
      .finally(() => setLoading(false))
  }, [])

  function add() {
    setList([...list, {
      name: '', lat: 46.62, lon: 14.31, radius_km: 5,
      email: '', whatsapp: '',
    }])
  }

  function update(i, key, val) {
    const next = [...list]
    const strKeys = ['name', 'email', 'whatsapp']
    next[i] = { ...next[i], [key]: strKeys.includes(key) ? val : parseFloat(val) }
    setList(next)
  }

  function remove(i) { setList(list.filter((_, idx) => idx !== i)) }

  async function save() {
    try {
      await api.post('/api/locations', list)
      setMsg('Gespeichert. Wirkt sofort im nächsten Live-Loop-Zyklus.')
    } catch (e) { setMsg('Fehler: ' + e.message) }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Beobachtete Orte</h1>
      {msg && (
        <div className="bg-blue-100 border border-blue-300 text-blue-900 p-2 rounded mb-3 text-sm">
          {msg}
        </div>
      )}
      {loading && <div className="text-gray-400 text-sm mb-3">Lade Orte…</div>}
      {apiError && (
        <div className="bg-red-100 border border-red-400 text-red-900 p-3 rounded mb-3 text-sm">
          <strong>Service nicht erreichbar</strong> — Orte konnten nicht geladen werden.<br/>
          <code className="text-xs">sudo systemctl status wetterprojekt-admin</code>
        </div>
      )}

      {/* Hinweis-Box WhatsApp */}
      <div className="bg-green-50 border border-green-200 text-green-900 p-3 rounded mb-4 text-xs">
        <strong>WhatsApp via CallMeBot:</strong> Jeder Empfänger muss einmalig
        WhatsApp an <strong>+34 644 82 17 47</strong> senden:{' '}
        <em>„I allow callmebot to send me messages"</em> → erhält seinen persönlichen APIKey.
        Format: <code>+43699Nummer:APIKey</code> — mehrere Empfänger mit Semikolon trennen.
      </div>

      <div className="overflow-x-auto">
        <table className="w-full bg-white border border-gray-200 rounded text-sm">
          <thead className="bg-gray-100">
            <tr>
              <th className="p-2 text-left">Name</th>
              <th className="p-2 text-left">Lat</th>
              <th className="p-2 text-left">Lon</th>
              <th className="p-2 text-left">Radius (km)</th>
              <th className="p-2 text-left">E-Mail(s)</th>
              <th className="p-2 text-left">WhatsApp (+Nr:APIKey)</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {list.map((l, i) => (
              <tr key={i} className="border-t">
                <td className="p-2">
                  <input
                    className="input"
                    value={l.name}
                    onChange={e => update(i, 'name', e.target.value)}
                    placeholder="Klagenfurt"
                  />
                </td>
                <td className="p-2">
                  <input
                    className="input"
                    type="number"
                    step="0.0001"
                    value={l.lat}
                    onChange={e => update(i, 'lat', e.target.value)}
                  />
                </td>
                <td className="p-2">
                  <input
                    className="input"
                    type="number"
                    step="0.0001"
                    value={l.lon}
                    onChange={e => update(i, 'lon', e.target.value)}
                  />
                </td>
                <td className="p-2">
                  <input
                    className="input"
                    type="number"
                    step="0.1"
                    value={l.radius_km}
                    onChange={e => update(i, 'radius_km', e.target.value)}
                  />
                </td>
                <td className="p-2">
                  <input
                    className="input"
                    type="text"
                    value={l.email ?? ''}
                    onChange={e => update(i, 'email', e.target.value)}
                    placeholder="user1@example.com;user2@example.com"
                  />
                </td>
                <td className="p-2">
                  <input
                    className="input"
                    type="text"
                    value={l.whatsapp ?? ''}
                    onChange={e => update(i, 'whatsapp', e.target.value)}
                    placeholder="+43699...:APIKey1;+43664...:APIKey2"
                  />
                </td>
                <td className="p-2">
                  <button className="btn-danger" onClick={() => remove(i)}>x</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-4 space-x-2">
        <button className="btn-secondary" onClick={add}>+ Ort hinzufügen</button>
        <button className="btn-primary" onClick={save}>Speichern</button>
      </div>
    </div>
  )
}
