import React, { useEffect, useState } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import api from '../api.js'

export default function Accuracy() {
  const [hours, setHours] = useState(24)
  const [data, setData] = useState({ current: { horizons: [], tolerance_km: 5 }, history: [] })
  const [apiHealth, setApiHealth] = useState({ total: 0, by_service: {} })

  useEffect(() => {
    api.get(`/api/accuracy?hours=${hours}`).then(setData).catch(() => {})
    api.get(`/api/api_health?hours=${hours}`).then(setApiHealth).catch(() => {})
  }, [hours])

  const horizons = data.current.horizons.map(h => h.horizon)
  const tolKm = data.current.tolerance_km

  const seriesKm = data.history.map((rec, i) => {
    const row = { idx: i + 1 }
    horizons.forEach(h => {
      const e = rec.horizons?.find(x => x.horizon === h)
      row[`+${h}m`] = e?.mae_km
    })
    return row
  })
  const seriesHit = data.history.map((rec, i) => {
    const row = { idx: i + 1 }
    horizons.forEach(h => {
      const e = rec.horizons?.find(x => x.horizon === h)
      row[`+${h}m`] = e?.hit_rate != null ? (e.hit_rate * 100) : null
    })
    return row
  })

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Vorhersagegenauigkeit (Closed-Loop)</h1>

      <div className="card mb-4">
        <label className="label">Zeitraum</label>
        <select className="input" value={hours} onChange={e => setHours(parseInt(e.target.value))}>
          <option value="1">1 Stunde</option>
          <option value="6">6 Stunden</option>
          <option value="24">24 Stunden</option>
          <option value="168">7 Tage</option>
          <option value="720">30 Tage</option>
        </select>
        <div className="text-sm text-gray-500 mt-2">
          Treffer-Toleranz: <b>{tolKm} km</b> (siehe config.VERIFICATION_TOLERANCE_KM)
        </div>
      </div>

      <div className="card mb-4">
        <h3 className="text-lg font-medium mb-2">Aktuelle Auswertung (letzte {hours} h)</h3>
        <table className="w-full text-sm">
          <thead><tr className="border-b">
            <th className="text-left p-1">Horizont</th>
            <th className="text-left p-1">Samples</th>
            <th className="text-left p-1">Hits</th>
            <th className="text-left p-1">Missed</th>
            <th className="text-left p-1">Hit-Rate</th>
            <th className="text-left p-1">MAE (km)</th>
            <th className="text-left p-1">RMSE (km)</th>
            <th className="text-left p-1">MAE (px)</th>
          </tr></thead>
          <tbody>
            {data.current.horizons.map(h => (
              <tr key={h.horizon} className="border-b">
                <td className="p-1">+{h.horizon} min</td>
                <td className="p-1">{h.samples}</td>
                <td className="p-1">{h.hits}</td>
                <td className="p-1">{h.missed}</td>
                <td className="p-1">{h.hit_rate != null ? (h.hit_rate * 100).toFixed(1) + '%' : '—'}</td>
                <td className="p-1">{h.mae_km?.toFixed?.(2) ?? '—'}</td>
                <td className="p-1">{h.rmse_km?.toFixed?.(2) ?? '—'}</td>
                <td className="p-1">{h.mae_px?.toFixed?.(2) ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card mb-4">
        <h3 className="text-lg font-medium mb-2">MAE (km) — Verlauf</h3>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={seriesKm}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="idx" />
            <YAxis label={{ value: 'km', angle: -90, position: 'insideLeft' }} />
            <Tooltip />
            <Legend />
            {horizons.map(h => <Line key={h} type="monotone" dataKey={`+${h}m`} dot={{ r: 2 }} connectNulls />)}
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="card mb-4">
        <h3 className="text-lg font-medium mb-2">Hit-Rate (%) — Verlauf</h3>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={seriesHit}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="idx" />
            <YAxis domain={[0, 100]} />
            <Tooltip />
            <Legend />
            {horizons.map(h => <Line key={h} type="monotone" dataKey={`+${h}m`} dot={{ r: 2 }} connectNulls />)}
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="card">
        <h3 className="text-lg font-medium mb-2">API-Health (letzte {hours} h)</h3>
        {apiHealth.total === 0 ? (
          <div className="text-sm text-green-700">Keine API-Fehler im Zeitraum.</div>
        ) : (
          <table className="w-full text-sm">
            <thead><tr className="border-b">
              <th className="text-left p-1">Service</th>
              <th className="text-left p-1">Fehler</th>
              <th className="text-left p-1">Fallback</th>
              <th className="text-left p-1">Häufigster Grund</th>
              <th className="text-left p-1">Letzter Fehler</th>
            </tr></thead>
            <tbody>
              {Object.entries(apiHealth.by_service || {}).map(([svc, info]) => {
                const topReason = Object.entries(info.reasons || {})
                  .sort((a, b) => b[1] - a[1])[0]
                return (
                  <tr key={svc} className="border-b">
                    <td className="p-1">{svc}</td>
                    <td className="p-1">{info.count}</td>
                    <td className="p-1">{info.fallback_count}</td>
                    <td className="p-1">{topReason ? `${topReason[0]} (${topReason[1]})` : '—'}</td>
                    <td className="p-1 text-xs">{info.last_ts || '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
