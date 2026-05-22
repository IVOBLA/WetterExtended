import React, { useEffect, useState } from 'react'
import api from '../api.js'

const SOURCE_BADGE = {
  manual_polygon: { label: 'Manuell',     color: 'bg-amber-100 text-amber-800 border-amber-300' },
  ai_suggestion:  { label: 'KI',          color: 'bg-purple-100 text-purple-800 border-purple-300' },
  migration:      { label: 'Migration',   color: 'bg-gray-100 text-gray-700 border-gray-300' },
}

function HsvSwatch({ hsvRange }) {
  // Mittelwert der HSV-Range als RGB-Hintergrund für Schnellvorschau
  if (!hsvRange || hsvRange.length !== 2) return null
  const [lo, hi] = hsvRange
  const h = ((lo[0] + hi[0]) / 2) / 179 * 360
  const s = ((lo[1] + hi[1]) / 2) / 255 * 100
  const v = ((lo[2] + hi[2]) / 2) / 255 * 100
  // HSV → HSL Konvertierung (vereinfacht, für Vorschau ausreichend)
  const l = v * (1 - s / 200)
  const sl = l === 0 || l === 100 ? 0 : ((v - l) / Math.min(l, 100 - l)) * 100
  return (
    <div className="w-10 h-10 rounded border-2 border-gray-300 shrink-0"
         style={{ background: `hsl(${h.toFixed(0)}, ${sl.toFixed(0)}%, ${l.toFixed(0)}%)` }}
         title={`H${lo[0]}-${hi[0]}  S${lo[1]}-${hi[1]}  V${lo[2]}-${hi[2]}`} />
  )
}

function FilterCard({ entry, onToggle, onDelete }) {
  const badge = SOURCE_BADGE[entry.source] || SOURCE_BADGE.manual_polygon
  const [lo, hi] = entry.hsv_range || [[0, 0, 0], [0, 0, 0]]
  const meta = entry.polygon_meta || {}

  return (
    <div className={`border rounded-lg p-3 bg-white shadow-sm
                     ${entry.active ? '' : 'opacity-60'}`}>
      <div className="flex gap-3 items-start">
        {/* PNG-Thumbnail oder HSV-Swatch */}
        {entry.polygon_png ? (
          <img src={`/api/cell_filters/${entry.id}/png`}
               alt={entry.label}
               className="w-28 h-28 object-cover rounded border border-gray-300 shrink-0"
               loading="lazy" />
        ) : (
          <HsvSwatch hsvRange={entry.hsv_range} />
        )}

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <strong className="text-sm truncate" title={entry.label}>
              {entry.label || 'unbenannt'}
            </strong>
            <span className={`text-xs px-2 py-0.5 rounded border ${badge.color}`}>
              {badge.label}
            </span>
            {!entry.active && (
              <span className="text-xs px-2 py-0.5 rounded border bg-gray-100 text-gray-700">
                inaktiv
              </span>
            )}
          </div>

          <div className="font-mono text-xs text-gray-700 leading-snug">
            <div>H {lo[0]}–{hi[0]}</div>
            <div>S {lo[1]}–{hi[1]}</div>
            <div>V {lo[2]}–{hi[2]}</div>
          </div>

          <div className="text-xs text-gray-500 mt-1">
            {entry.created_at?.replace('T', ' ').slice(0, 16) || '—'}
            {meta.zoom_level != null && <> · Zoom {meta.zoom_level}</>}
          </div>

          <div className="flex gap-2 mt-2">
            <button
              onClick={() => onToggle(entry.id, !entry.active)}
              className={`text-xs px-2 py-1 rounded border
                          ${entry.active
                            ? 'bg-yellow-50 border-yellow-300 text-yellow-800 hover:bg-yellow-100'
                            : 'bg-green-50 border-green-300 text-green-800 hover:bg-green-100'}`}>
              {entry.active ? 'Deaktivieren' : 'Aktivieren'}
            </button>
            <button
              onClick={() => onDelete(entry.id)}
              className="text-xs px-2 py-1 rounded border border-red-300
                         bg-red-50 text-red-700 hover:bg-red-100">
              Löschen
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function AiSuggestionCard({ sug, onAccept }) {
  if (sug.accepted) {
    return (
      <div className="border rounded-lg p-3 bg-green-50 border-green-300">
        <div className="text-sm font-medium text-green-900 mb-1">
          ✓ KI-Vorschlag übernommen
        </div>
        <div className="text-xs text-gray-600">
          {sug.created_at?.replace('T', ' ').slice(0, 16)} ·
          {' '}{sug.created_filter_ids?.length || 0} Filter angelegt
        </div>
      </div>
    )
  }
  const ranges = sug.suggested_ranges || []
  if (ranges.length === 0) {
    return (
      <div className="border rounded-lg p-3 bg-gray-50 border-gray-300">
        <div className="text-sm text-gray-600">
          KI hat keine Erweiterungs-Vorschläge geliefert ({sug.created_at?.slice(0, 16)})
        </div>
      </div>
    )
  }
  return (
    <div className="border rounded-lg p-3 bg-purple-50 border-purple-300">
      <div className="flex justify-between items-start mb-2">
        <div>
          <div className="text-sm font-semibold text-purple-900">
            🤖 {ranges.length} KI-Vorschlag{ranges.length > 1 ? 'e' : ''}
          </div>
          <div className="text-xs text-purple-700">
            {sug.model} · {sug.created_at?.replace('T', ' ').slice(0, 16)}
          </div>
        </div>
        <button onClick={() => onAccept(sug.id)}
                className="text-xs px-3 py-1 rounded bg-purple-600 text-white
                           hover:bg-purple-700 font-medium">
          Alle übernehmen
        </button>
      </div>
      <div className="space-y-2">
        {ranges.map((r, i) => {
          const [lo, hi] = r.hsv_range || [[0,0,0],[0,0,0]]
          return (
            <div key={i} className="bg-white rounded p-2 border border-purple-200 text-xs">
              <div className="font-medium mb-0.5">{r.label}</div>
              <div className="font-mono text-gray-700">
                H {lo[0]}–{hi[0]} · S {lo[1]}–{hi[1]} · V {lo[2]}–{hi[2]}
              </div>
              {r.rationale && (
                <div className="text-gray-600 italic mt-1">{r.rationale}</div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function CellFilters() {
  const [filters,        setFilters]        = useState([])
  const [aiSuggestions,  setAiSuggestions]  = useState([])
  const [padding,        setPadding]        = useState(50)
  const [paddingPending, setPaddingPending] = useState(50)
  const [aiLoading,      setAiLoading]      = useState(false)
  const [aiMsg,          setAiMsg]          = useState('')
  const [error,          setError]          = useState('')
  const [models,         setModels]         = useState([])
  const [selectedModel,  setSelectedModel]  = useState('claude-sonnet-4-6')

  async function reload() {
    try {
      const d = await api.get('/api/cell_filters')
      setFilters(d.active_filters || [])
      setAiSuggestions(d.ai_suggestions || [])
      setPadding(d.padding_px || 50)
      setPaddingPending(d.padding_px || 50)
      setError('')
    } catch (e) {
      setError(e.message || String(e))
    }
  }

  useEffect(() => {
    reload()
    api.get('/api/ai_analysis/models')
       .then(d => setModels(d.models || []))
       .catch(() => {})
  }, [])

  async function handleToggle(id, active) {
    try {
      await api.patch(`/api/cell_filters/${id}`, { active })
      reload()
    } catch (e) { alert('Fehler: ' + e.message) }
  }

  async function handleDelete(id) {
    if (!window.confirm('Filter inklusive Polygon-PNG endgültig löschen?')) return
    try {
      await api.delete(`/api/cell_filters/${id}`)
      reload()
    } catch (e) { alert('Fehler: ' + e.message) }
  }

  async function handlePaddingSave() {
    try {
      await api.post('/api/cell_filters/padding', { padding_px: paddingPending })
      setPadding(paddingPending)
    } catch (e) { alert('Fehler: ' + e.message) }
  }

  async function handleAiAnalyze() {
    setAiLoading(true)
    setAiMsg('')
    try {
      const r = await api.post('/api/cell_filters/ai_analyze', { model: selectedModel })
      if (r.ok) {
        setAiMsg(`✓ KI-Analyse fertig: ${r.pngs_sent} PNGs gesendet, ` +
                 `${r.suggestions?.length || 0} Vorschläge`)
        reload()
      } else {
        setAiMsg('Fehler: ' + (r.error || 'unbekannt'))
      }
    } catch (e) {
      setAiMsg('Fehler: ' + e.message)
    } finally {
      setAiLoading(false)
    }
  }

  async function handleAcceptSuggestion(sugId) {
    try {
      const r = await api.post(`/api/cell_filters/ai_suggestions/${sugId}/accept`, {})
      if (r.ok) {
        setAiMsg(`✓ ${r.count} Filter aus KI-Vorschlag übernommen`)
        reload()
      } else {
        alert('Fehler beim Übernehmen')
      }
    } catch (e) { alert('Fehler: ' + e.message) }
  }

  const pngCount     = filters.filter(f => f.polygon_png).length
  const activeCount  = filters.filter(f => f.active).length
  const pendingAi    = aiSuggestions.filter(s => !s.accepted &&
                                                  (s.suggested_ranges || []).length > 0)

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">🔬 Filter-Galerie (Human-in-the-Loop)</h1>
        <p className="text-sm text-gray-600 mt-1">
          Alle vom Benutzer markierten und von der KI vorgeschlagenen HSV-Filter zur Sturmzellen-Erkennung.
        </p>
      </div>

      {error && (
        <div className="card border-red-300 bg-red-50 text-red-800 text-sm">
          {error}
        </div>
      )}

      {/* Kennzahlen + Padding */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="card">
          <div className="text-2xl font-bold">{activeCount}</div>
          <div className="text-xs text-gray-500">Aktive Filter</div>
        </div>
        <div className="card">
          <div className="text-2xl font-bold">{pngCount}</div>
          <div className="text-xs text-gray-500">mit Polygon-PNG</div>
        </div>
        <div className="card">
          <div className="text-xs text-gray-500 mb-1">
            PNG-Padding: <strong>{paddingPending} px</strong>
            {paddingPending !== padding && (
              <span className="text-amber-600 ml-2">(ungespeichert)</span>
            )}
          </div>
          <input type="range" min="5" max="500" step="5"
                 value={paddingPending}
                 onChange={e => setPaddingPending(parseInt(e.target.value))}
                 className="w-full" />
          <button onClick={handlePaddingSave}
                  disabled={paddingPending === padding}
                  className="mt-1 text-xs px-2 py-1 rounded bg-blue-600 text-white
                             hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed">
            Speichern
          </button>
        </div>
      </div>

      {/* KI-Analyse */}
      <div className="card">
        <h2 className="text-base font-semibold mb-3">🤖 KI-Analyse — Filter erweitern</h2>
        <p className="text-xs text-gray-600 mb-3">
          Sendet die letzten gespeicherten Polygon-PNGs zusammen mit den aktiven Filtern an
          Claude und erhält Vorschläge für <em>zusätzliche</em> HSV-Bereiche (Modus
          „expand_only" — bestehende Filter bleiben unverändert).
        </p>
        <div className="flex flex-wrap gap-3 items-center">
          <label className="flex items-center gap-2 text-sm">
            Modell:
            <select className="border rounded px-2 py-1 text-sm"
                    value={selectedModel}
                    onChange={e => setSelectedModel(e.target.value)}>
              {models.length === 0
                ? <option value="claude-sonnet-4-6">claude-sonnet-4-6</option>
                : models.map(m => (
                    <option key={m.id} value={m.id}>{m.label}</option>
                  ))}
            </select>
          </label>
          <button onClick={handleAiAnalyze}
                  disabled={aiLoading || pngCount === 0}
                  className="px-4 py-2 rounded bg-purple-600 text-white text-sm
                             hover:bg-purple-700 disabled:opacity-40 disabled:cursor-not-allowed">
            {aiLoading ? 'Analysiere...' : `Mit KI analysieren (${pngCount} PNGs)`}
          </button>
          {pngCount === 0 && (
            <span className="text-xs text-amber-700">
              Markiere zuerst Zellen auf der Karte.
            </span>
          )}
        </div>
        {aiMsg && (
          <div className="mt-3 text-sm text-gray-700">{aiMsg}</div>
        )}
      </div>

      {/* KI-Vorschläge */}
      {pendingAi.length > 0 && (
        <div>
          <h2 className="text-base font-semibold mb-2">Offene KI-Vorschläge</h2>
          <div className="space-y-3">
            {pendingAi.map(s => (
              <AiSuggestionCard key={s.id} sug={s}
                                onAccept={handleAcceptSuggestion} />
            ))}
          </div>
        </div>
      )}

      {/* Filter-Galerie */}
      <div>
        <h2 className="text-base font-semibold mb-2">
          Filter ({filters.length})
        </h2>
        {filters.length === 0 ? (
          <div className="card text-sm text-gray-500">
            Noch keine Filter vorhanden. Markiere eine Zelle auf der Karte.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {filters.map(entry => (
              <FilterCard key={entry.id} entry={entry}
                          onToggle={handleToggle} onDelete={handleDelete} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
