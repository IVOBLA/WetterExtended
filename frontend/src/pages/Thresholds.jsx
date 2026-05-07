import React, { useEffect, useState } from 'react'
import api from '../api.js'

export default function Thresholds() {
  const [filterText, setFilterText] = useState('')
  const [coreText, setCoreText] = useState('')
  const [labels, setLabels] = useState([])
  const [msg, setMsg] = useState('')

  useEffect(() => {
    api.get('/api/thresholds').then(d => {
      setFilterText(JSON.stringify(d.FILTER_CONFIG, null, 2))
      setCoreText(JSON.stringify(d.CORE_HSV_RANGES, null, 2))
      setLabels(d.HSV_BAND_LABELS || [])
    }).catch(() => {})
  }, [])

  async function save() {
    try {
      const fc = JSON.parse(filterText)
      const cr = JSON.parse(coreText)
      await api.post('/api/thresholds', { FILTER_CONFIG: fc, CORE_HSV_RANGES: cr })
      setMsg('Gespeichert. Wirkt im nächsten Live-Loop-Zyklus.')
    } catch (e) { setMsg('Fehler: ' + e.message) }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">HSV-Schwellwerte (Radarsegmentierung)</h1>
      {msg && <div className="bg-blue-100 border border-blue-300 text-blue-900 p-2 rounded mb-3 text-sm">{msg}</div>}
      <p className="text-sm text-gray-600 mb-2">Bänder: {labels.join(', ')}</p>

      <label className="label">FILTER_CONFIG (allowed_hsv_ranges, min_object_area)</label>
      <textarea className="input font-mono" rows="10" value={filterText} onChange={e => setFilterText(e.target.value)} />

      <label className="label mt-4">CORE_HSV_RANGES (Kern-HSV-Bereiche)</label>
      <textarea className="input font-mono" rows="10" value={coreText} onChange={e => setCoreText(e.target.value)} />

      <button className="btn-primary mt-4" onClick={save}>Speichern</button>
    </div>
  )
}
