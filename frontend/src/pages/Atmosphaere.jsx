import React, { useEffect, useState } from 'react'
import api from '../api.js'

// Windrichtung aus cos/sin
function windDir(cos_val, sin_val) {
  if (!cos_val && !sin_val) return '—'
  const deg = (Math.atan2(sin_val, cos_val) * 180 / Math.PI + 360) % 360
  const dirs = ['N','NO','O','SO','S','SW','W','NW','N']
  return dirs[Math.round(deg / 45)] + ' ' + deg.toFixed(0) + '°'
}

// Farbe je nach Gewitterpotenzial
function potentialStyle(p) {
  if (p === 'hoch')   return { bg: 'bg-red-50',    badge: 'bg-red-100 text-red-800',    label: '🔴 Hoch' }
  if (p === 'mäßig') return { bg: 'bg-yellow-50', badge: 'bg-yellow-100 text-yellow-800', label: '🟡 Mäßig' }
  return                     { bg: '',             badge: 'bg-green-100 text-green-800',  label: '🟢 Niedrig' }
}

// Spread-Farbe: kleiner Spread = hohe Feuchte = erhöhtes Risiko
function spreadColor(s) {
  if (s < 3) return 'text-red-600 font-semibold'
  if (s < 6) return 'text-yellow-600'
  return 'text-gray-700'
}

export default function Atmosphaere() {
  const [data,    setData]    = useState({ ts_utc: null, locations: [] })
  const [loading, setLoading] = useState(true)

  function load() {
    api.get('/api/atmosphere')
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    const t = setInterval(load, 5 * 60 * 1000)  // alle 5 Min neu laden
    return () => clearInterval(t)
  }, [])

  const ts = data.ts_utc ? data.ts_utc.substring(0, 16).replace('T', ' ') + ' UTC' : '—'
  const hasHigh = data.locations.some(l => l.potential === 'hoch')
  const hasMid  = data.locations.some(l => l.potential === 'mäßig')

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold">Atmosphäre Kärnten</h1>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-400">Stand: {ts}</span>
          <button onClick={load} className="btn-secondary text-sm">↺ Reload</button>
        </div>
      </div>

      {/* Warnbanner */}
      {hasHigh && (
        <div className="bg-red-100 border border-red-400 text-red-900 p-3 rounded mb-4 text-sm font-semibold">
          ⚠ Hohes Gewitterpotenzial in Teilen Kärntens — instabile Luftmasse (LI &lt; −3 °C)
        </div>
      )}
      {!hasHigh && hasMid && (
        <div className="bg-yellow-100 border border-yellow-400 text-yellow-900 p-3 rounded mb-4 text-sm">
          Mäßiges Gewitterpotenzial — leicht labile Luftmasse (LI &lt; −1 °C)
        </div>
      )}

      {loading ? (
        <div className="text-gray-500 text-sm">Lade atmosphärische Daten...</div>
      ) : data.locations.length === 0 ? (
        <div className="bg-gray-50 border rounded p-4 text-sm text-gray-600">
          Noch kein Snapshot verfügbar. Der Scheduler läuft alle 30 Minuten.
          Manuell starten:
          <code className="ml-1 bg-gray-100 px-1 rounded">python3 fetch_atmospheric_snapshot.py</code>
        </div>
      ) : (
        <div className="card overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-xs text-gray-500 uppercase">
                <th className="p-3 text-left">Ort</th>
                <th className="p-3 text-right">T 2m</th>
                <th className="p-3 text-right">Td 2m</th>
                <th className="p-3 text-right" title="Taupunkt-Spread: kleiner = feuchter">Spread</th>
                <th className="p-3 text-right" title="Lifted Index: negativ = instabil">LI</th>
                <th className="p-3 text-right">Gefriergrenze</th>
                <th className="p-3 text-right">Wind 10m</th>
                <th className="p-3 text-right">Wind 700hPa</th>
                <th className="p-3 text-center">Gewitter-Pot.</th>
              </tr>
            </thead>
            <tbody>
              {data.locations.map((loc, i) => {
                const ps = potentialStyle(loc.potential)
                return (
                  <tr key={i} className={`border-b ${ps.bg}`}>
                    <td className="p-3 font-semibold">{loc.name}</td>
                    <td className="p-3 text-right">{loc.t2m?.toFixed(1)} °C</td>
                    <td className="p-3 text-right">{loc.td2m?.toFixed(1)} °C</td>
                    <td className={`p-3 text-right ${spreadColor(loc.spread)}`}>
                      {loc.spread?.toFixed(1)} K
                    </td>
                    <td className={`p-3 text-right font-mono ${loc.li < -1 ? 'text-red-600 font-semibold' : ''}`}>
                      {loc.li?.toFixed(1)}
                    </td>
                    <td className="p-3 text-right text-gray-600">
                      {loc.fl_height > 0 ? `${Math.round(loc.fl_height)} m` : '—'}
                    </td>
                    <td className="p-3 text-right text-xs text-gray-600">
                      {loc.ff10m?.toFixed(0)} km/h
                    </td>
                    <td className="p-3 text-right text-xs text-gray-600">
                      {loc.wind_700hpa > 0
                        ? `${loc.wind_700hpa?.toFixed(0)} km/h ${windDir(loc.wind_dir_cos, loc.wind_dir_sin)}`
                        : '—'}
                    </td>
                    <td className="p-3 text-center">
                      <span className={`text-xs px-2 py-1 rounded-full ${ps.badge}`}>
                        {ps.label}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>

          {/* Legende */}
          <div className="mt-3 pt-3 border-t text-xs text-gray-500 grid grid-cols-2 md:grid-cols-4 gap-2">
            <div><b>LI</b> = Lifted Index (°C). Negativ = labil. &lt;−1 = mäßig, &lt;−3 = hoch instabil</div>
            <div><b>Spread</b> = T − Td. &lt;3 K = sehr feucht (Gewitterrisiko erhöht)</div>
            <div><b>Gefriergrenze</b> = Höhe der 0°C-Isotherme (MSL)</div>
            <div><b>Wind 700hPa</b> ≈ 3000 m, steuert Zugrichtung von Zellen</div>
          </div>
        </div>
      )}
    </div>
  )
}
