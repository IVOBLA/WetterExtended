import React, { useEffect, useState } from 'react'
import api from '../api.js'

export default function Horizons() {
  const [horizons, setHorizons] = useState([10, 20, 30, 40, 60])
  const [colors, setColors] = useState({})
  const [styles, setStyles] = useState({})
  const [cfg, setCfg] = useState({ WARN_MAX_HORIZON_MIN: 20 })
  const [msg, setMsg] = useState('')

  useEffect(() => {
    api.get('/api/horizons').then(d => {
      const hz = d.horizons || [10, 20, 30, 40, 60]
      setHorizons(hz)
      const c = {}; hz.forEach(h => { c[h] = d.colors[h] || d.colors[String(h)] || '#888888' }); setColors(c)
      const s = {}; hz.forEach(h => { s[h] = d.styles[h] || d.styles[String(h)] || { weight: 2, dash: '' } }); setStyles(s)
    }).catch(() => {})
    api.get('/api/config').then(d => {
      setCfg(c => ({ ...c, WARN_MAX_HORIZON_MIN: Number(d.WARN_MAX_HORIZON_MIN ?? 20) }))
    }).catch(() => {})
  }, [])

  function updateHorizon(i, val) {
    const next = [...horizons]; next[i] = parseInt(val) || 0; setHorizons(next)
  }

  async function save() {
    if (horizons.length !== 5) { setMsg('Genau 5 Horizonte erforderlich.'); return }
    try {
      const colorsByH = {}; horizons.forEach(h => { colorsByH[h] = colors[h] || '#888888' })
      const stylesByH = {}; horizons.forEach(h => { stylesByH[h] = styles[h] || { weight: 2, dash: '' } })
      await api.post('/api/horizons', { horizons, colors: colorsByH, styles: stylesByH })
      await api.post('/api/config', { WARN_MAX_HORIZON_MIN: cfg.WARN_MAX_HORIZON_MIN ?? 20 })
      setMsg('Gespeichert. Live-Loop, Karte und Alarm-Vorwarnzeit verwenden die neuen Werte ab dem nächsten Frame.')
    } catch (e) { setMsg('Fehler: ' + e.message) }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Vorhersage-Horizonte (5)</h1>
      {msg && <div className="bg-blue-100 border border-blue-300 text-blue-900 p-2 rounded mb-3 text-sm">{msg}</div>}
      <table className="w-full bg-white border border-gray-200 rounded">
        <thead className="bg-gray-100 text-sm">
          <tr>
            <th className="p-2 text-left">Minuten</th>
            <th className="p-2 text-left">Pfeilfarbe</th>
            <th className="p-2 text-left">Linienstärke</th>
            <th className="p-2 text-left">Strichmuster</th>
          </tr>
        </thead>
        <tbody>
          {horizons.map((h, i) => (
            <tr key={i} className="border-t">
              <td className="p-2"><input className="input" type="number" min="1" value={h} onChange={e => updateHorizon(i, e.target.value)} /></td>
              <td className="p-2 flex items-center gap-2">
                <input type="color" value={colors[h] || '#888888'} onChange={e => setColors({ ...colors, [h]: e.target.value })} />
                <input className="input" value={colors[h] || ''} onChange={e => setColors({ ...colors, [h]: e.target.value })} />
              </td>
              <td className="p-2"><input className="input" type="number" min="1" max="6" value={(styles[h] || {}).weight || 2}
                onChange={e => setStyles({ ...styles, [h]: { ...(styles[h] || {}), weight: parseInt(e.target.value) || 2 } })} /></td>
              <td className="p-2"><input className="input" placeholder="z.B. 4,4 für gepunktet" value={(styles[h] || {}).dash || ''}
                onChange={e => setStyles({ ...styles, [h]: { ...(styles[h] || {}), dash: e.target.value } })} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-4 bg-white border border-gray-200 rounded p-4">
        {/* B91: Vorwarnzeit-Schwelle */}
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Vorwarnzeit — Alarm nur wenn Eintreffzeit ≤ (Minuten)
        </label>
        <input
          type="number"
          min={5} max={60} step={5}
          className="input w-32"
          value={cfg.WARN_MAX_HORIZON_MIN ?? 20}
          onChange={e => setCfg(c => ({
            ...c,
            WARN_MAX_HORIZON_MIN: Math.max(5, Math.min(60, Number(e.target.value)))
          }))}
        />
        <p className="text-xs text-gray-500 mt-1">
          E-Mail/WhatsApp-Alarm wird nur gesendet wenn der nächste berechnete
          Eintreffzeitpunkt ≤ diesem Wert liegt (Standard: 20 min).
          Horizont 0 (Zelle bereits im Ort) löst immer sofort Alarm aus.
        </p>
      </div>
      <button className="btn-primary mt-4" onClick={save}>Speichern</button>
    </div>
  )
}
