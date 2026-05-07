import React, { useEffect, useState } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import api from '../api.js'

export default function Accuracy() {
  const [hours, setHours] = useState(24)
  const [data, setData] = useState({ current: { horizons: [] }, history: [] })

  useEffect(() => {
    api.get(`/api/accuracy?hours=${hours}`).then(setData).catch(() => {})
  }, [hours])

  const horizons = data.current.horizons.map(h => h.horizon)
  const series = data.history.map((rec, i) => {
    const row = { idx: i + 1 }
    horizons.forEach(h => {
      const e = rec.horizons?.find(x => x.horizon === h)
      row[`+${h}m`] = e?.mae_px
    })
    return row
  })

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Vorhersagegenauigkeit</h1>
      <div className="card mb-4">
        <label className="label">Zeitraum</label>
        <select className="input" value={hours} onChange={e => setHours(parseInt(e.target.value))}>
          <option value="1">1 Stunde</option>
          <option value="6">6 Stunden</option>
          <option value="24">24 Stunden</option>
          <option value="168">7 Tage</option>
          <option value="720">30 Tage</option>
        </select>
      </div>

      <div className="card mb-4">
        <h3 className="text-lg font-medium mb-2">Aktuelle Auswertung (letzte {hours}h)</h3>
        <table className="w-full text-sm">
          <thead><tr className="border-b">
            <th className="text-left p-1">Horizont</th><th className="text-left p-1">Samples</th>
            <th className="text-left p-1">MAE (px)</th><th className="text-left p-1">RMSE x</th>
            <th className="text-left p-1">RMSE y</th>
          </tr></thead>
          <tbody>
            {data.current.horizons.map(h => (
              <tr key={h.horizon} className="border-b">
                <td className="p-1">+{h.horizon} min</td>
                <td className="p-1">{h.samples}</td>
                <td className="p-1">{h.mae_px?.toFixed?.(2) ?? '—'}</td>
                <td className="p-1">{h.rmse_x_px?.toFixed?.(2) ?? '—'}</td>
                <td className="p-1">{h.rmse_y_px?.toFixed?.(2) ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3 className="text-lg font-medium mb-2">MAE-Verlauf</h3>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={series}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="idx" />
            <YAxis />
            <Tooltip />
            <Legend />
            {horizons.map(h => <Line key={h} type="monotone" dataKey={`+${h}m`} stroke="#2563eb" dot={{ r: 2 }} connectNulls />)}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
