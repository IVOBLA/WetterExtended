import React, { useEffect, useState } from 'react'
import api from '../api.js'

const PRIORITY_COLOR = {
  high: 'bg-red-100 border-red-400 text-red-800',
  medium: 'bg-yellow-100 border-yellow-400 text-yellow-800',
  low: 'bg-blue-100 border-blue-400 text-blue-800',
}
const CATEGORY_ICON = {
  accuracy: '🎯', api: '🌐', model: '🤖',
  data: '📊', system: '💻', config: '⚙️',
}
const STATUS_COLOR = {
  ok: 'text-green-700', warning: 'text-yellow-700', critical: 'text-red-700',
}

export default function AiSuggestions() {
  const [cfg, setCfg] = useState({
    enabled: false, cron_hour: 6, cron_minute: 0,
    since_hours: 24, max_tokens: 1500,
  })
  const [suggestions, setSuggestions] = useState([])
  const [running, setRunning] = useState(false)
  const [msg, setMsg] = useState('')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    api.get('/api/ai_analysis/config').then(setCfg).catch(() => {})
    api.get('/api/ai_analysis/suggestions?n=5').then(d => {
      setSuggestions(d.suggestions || [])
    }).catch(() => {})
  }, [])

  async function saveCfg() {
    try {
      await api.post('/api/ai_analysis/config', cfg)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (e) { setMsg('Fehler: ' + e.message) }
  }

  async function runNow() {
    setRunning(true)
    setMsg('')
    try {
      const r = await api.post('/api/ai_analysis/run', {})
      if (r.ok) {
        setMsg('Analyse abgeschlossen.')
        api.get('/api/ai_analysis/suggestions?n=5').then(d => {
          setSuggestions(d.suggestions || [])
        }).catch(() => {})
      } else {
        setMsg('Fehler: ' + (r.error || 'unbekannt'))
      }
    } catch (e) {
      setMsg('Fehler: ' + e.message)
    }
    setRunning(false)
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">KI-Analyse (Anthropic)</h1>

      {msg && (
        <div className="bg-blue-50 border border-blue-300 text-blue-900 p-2 rounded mb-4 text-sm">
          {msg}
        </div>
      )}

      <div className="card mb-6">
        <h2 className="text-lg font-semibold mb-3">Konfiguration</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="flex items-center gap-3">
            <label className="label mb-0">Aktiviert</label>
            <button
              onClick={() => setCfg({ ...cfg, enabled: !cfg.enabled })}
              className={`px-4 py-1 rounded font-medium text-sm transition-colors ${
                cfg.enabled ? 'bg-green-600 text-white' : 'bg-gray-300 text-gray-700'
              }`}
            >
              {cfg.enabled ? 'EIN' : 'AUS'}
            </button>
          </div>
          <div>
            <label className="label">Datenfenster (Stunden)</label>
            <input className="input" type="number" min="1" max="168"
              value={cfg.since_hours}
              onChange={e => setCfg({ ...cfg, since_hours: parseInt(e.target.value) || 24 })} />
          </div>
          <div>
            <label className="label">Analyse-Uhrzeit (Stunde, 0–23)</label>
            <input className="input" type="number" min="0" max="23"
              value={cfg.cron_hour}
              onChange={e => setCfg({ ...cfg, cron_hour: parseInt(e.target.value) || 6 })} />
          </div>
          <div>
            <label className="label">Analyse-Uhrzeit (Minute)</label>
            <input className="input" type="number" min="0" max="59"
              value={cfg.cron_minute}
              onChange={e => setCfg({ ...cfg, cron_minute: parseInt(e.target.value) || 0 })} />
          </div>
          <div>
            <label className="label">Max. Tokens pro Analyse</label>
            <input className="input" type="number" min="500" max="4000" step="100"
              value={cfg.max_tokens}
              onChange={e => setCfg({ ...cfg, max_tokens: parseInt(e.target.value) || 1500 })} />
          </div>
        </div>
        <div className="flex gap-3 mt-4">
          <button className="btn-primary" onClick={saveCfg}>Speichern</button>
          <button className="btn-secondary" onClick={runNow} disabled={running}>
            {running ? 'Analyse läuft…' : 'Jetzt analysieren'}
          </button>
          {saved && <span className="text-green-700 text-sm self-center">✓ Gespeichert</span>}
        </div>
      </div>

      <div>
        <h2 className="text-lg font-semibold mb-3">Letzte Analysen ({suggestions.length})</h2>
        {suggestions.length === 0 ? (
          <div className="card text-sm text-gray-500">Noch keine Analyse-Ergebnisse vorhanden.</div>
        ) : (
          suggestions.map((entry, ei) => (
            <div key={ei} className="card mb-4">
              <div className="flex justify-between items-start mb-3">
                <div>
                  <span className={`font-semibold ${STATUS_COLOR[entry.overall_status] || ''}`}>
                    ● {entry.overall_status?.toUpperCase() || '?'}
                  </span>
                </div>
              </div>
              {(entry.suggestions || []).length === 0 ? (
                <div className="text-sm text-green-700">✓ Keine Probleme erkannt.</div>
              ) : (
                <div className="space-y-2">
                  {(entry.suggestions || []).map((s, si) => (
                    <div key={si} className={`border-l-4 p-3 rounded text-sm ${PRIORITY_COLOR[s.priority] || 'bg-gray-100'}`}>
                      <div className="flex gap-2 items-center font-medium mb-1">
                        <span>{CATEGORY_ICON[s.category] || '•'}</span>
                        <span>[{s.priority?.toUpperCase()}] {s.title}</span>
                      </div>
                      <div className="text-xs mb-1">{s.description}</div>
                      <div className="text-xs font-medium">→ {s.action}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
