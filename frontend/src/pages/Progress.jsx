import React, { useEffect, useState } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import api from '../api.js'

export default function Progress() {
  const [versions, setVersions] = useState([])

  useEffect(() => { api.get('/api/progress').then(d => setVersions(d.versions || [])).catch(() => {}) }, [])

  const horizons = [10, 20, 30, 40, 60]
  const lstmSeries = versions.map((v, i) => ({ idx: i + 1, val_loss: v.lstm?.val_loss }))
  const maeSeries = versions.map((v, i) => {
    const h = v.validation?.mae_by_horizon_new || {}
    const row = { idx: i + 1 }
    horizons.forEach(hz => { row[`+${hz}m`] = h[String(hz)] })
    return row
  })
  const aucSeries = versions.map((v, i) => ({ idx: i + 1, auc: v.intensification?.auc }))

  function Chart({ title, data, lines }) {
    return (
      <div className="card mb-4">
        <h3 className="text-lg font-medium mb-2">{title}</h3>
        <ResponsiveContainer width="100%" height={250}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="idx" />
            <YAxis />
            <Tooltip />
            <Legend />
            {lines.map(l => <Line key={l} type="monotone" dataKey={l} stroke="#2563eb" dot={{ r: 3 }} connectNulls />)}
          </LineChart>
        </ResponsiveContainer>
      </div>
    )
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Lernfortschritt</h1>
      <Chart title="LSTM val_loss" data={lstmSeries} lines={['val_loss']} />
      <Chart title="LightGBM MAE pro Horizont (px)" data={maeSeries} lines={horizons.map(h => `+${h}m`)} />
      <Chart title="Intensification AUC" data={aucSeries} lines={['auc']} />
      <div className="card">
        <h3 className="text-lg font-medium mb-2">Versionen</h3>
        <table className="w-full text-sm">
          <thead><tr className="border-b">
            <th className="text-left p-1">Timestamp</th><th className="text-left p-1">Samples</th>
            <th className="text-left p-1">MAE total</th><th className="text-left p-1">Status</th>
          </tr></thead>
          <tbody>
            {versions.map((v, i) => (
              <tr key={i} className="border-b">
                <td className="p-1">{v.timestamp_utc}</td>
                <td className="p-1">{v.num_samples}</td>
                <td className="p-1">{v.validation?.mae_new?.toFixed?.(4) ?? '—'}</td>
                <td className="p-1">{v.validation?.status ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
