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

function HelpPanel() {
  const [open, setOpen] = React.useState(false)
  return (
    <div className="mt-3 border border-blue-200 rounded-lg bg-blue-50 text-sm">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-2 text-blue-800 font-medium hover:bg-blue-100 rounded-lg transition-colors"
      >
        <span>ℹ️ Was ist diese Seite? Wie funktioniert das?</span>
        <span className="text-blue-500 text-xs">{open ? '▲ Schließen' : '▼ Erklärung anzeigen'}</span>
      </button>

      {open && (
        <div className="px-4 pb-4 pt-1 space-y-4 text-gray-700">

          {/* Was sind HSV-Filter? */}
          <section>
            <h3 className="font-semibold text-blue-900 mb-1">🎨 Was sind HSV-Filter?</h3>
            <p>
              Das Radarbild wird in Farbbereiche aufgeteilt (HSV = Farbton/Helligkeit/Sättigung).
              Jeder Filter definiert einen Farbbereich, der als „Zelle erkannt" gilt.
              <strong className="text-blue-800"> H</strong> = Farbton (0–179),{' '}
              <strong className="text-blue-800">S</strong> = Sättigung (0–255),{' '}
              <strong className="text-blue-800">V</strong> = Helligkeit (0–255).
              Die Farbvorschau (kleines Quadrat) zeigt den Mittelpunkt des Filters.
            </p>
          </section>

          {/* Was bedeutet Human-in-the-Loop? */}
          <section>
            <h3 className="font-semibold text-blue-900 mb-1">🧑‍💻 Was bedeutet „Human-in-the-Loop"?</h3>
            <p>
              Der Algorithmus erkennt Zellen automatisch — aber er kann Farbbereiche übersehen,
              die auf dem konkreten Radarbild erscheinen. Über die Karte kannst du solche
              übersehenen Bereiche <em>mit einem Polygon markieren</em>. Das System misst die
              HSV-Werte im markierten Bereich, schlägt einen Filter vor, und du bestätigst oder
              verwirfst ihn. So lernt das System schrittweise — ohne Neutraining.
            </p>
          </section>

          {/* Was bedeuten die Badges? */}
          <section>
            <h3 className="font-semibold text-blue-900 mb-1">🏷️ Was bedeuten die Farb-Badges?</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
              <div className="bg-amber-50 border border-amber-300 rounded p-2">
                <span className="font-semibold text-amber-800">Manuell</span>
                <p className="text-xs mt-1">Du hast diesen Filter durch Polygon-Markierung auf der Karte erstellt.</p>
              </div>
              <div className="bg-purple-50 border border-purple-300 rounded p-2">
                <span className="font-semibold text-purple-800">KI</span>
                <p className="text-xs mt-1">Claude hat diesen Filter aus deinen Polygon-PNGs vorgeschlagen und du hast ihn übernommen.</p>
              </div>
              <div className="bg-gray-100 border border-gray-300 rounded p-2">
                <span className="font-semibold text-gray-700">Migration</span>
                <p className="text-xs mt-1">Dieser Filter wurde beim ersten Start aus der alten Konfiguration (config.py / runtime_overrides.json) übernommen.</p>
              </div>
            </div>
          </section>

          {/* Was sind Polygon-PNGs? */}
          <section>
            <h3 className="font-semibold text-blue-900 mb-1">🖼️ Was sind Polygon-PNGs?</h3>
            <p>
              Beim manuellen Markieren schneidet das System einen <em>Ausschnitt aus dem Radarbild</em>
              aus (mit gelber Umrandung des Polygons) und speichert ihn als PNG.
              Diese PNGs werden beim KI-Analyse-Button an Claude gesendet — Claude „sieht" die Bilder
              und kann weitere passende HSV-Bereiche vorschlagen.
              Karten-Filter ohne PNG (z.B. Migration-Filter) zeigen nur die Farbvorschau.
            </p>
          </section>

          {/* Typischer Workflow */}
          <section>
            <h3 className="font-semibold text-blue-900 mb-1">📋 Typischer Arbeitsablauf</h3>
            <ol className="list-decimal list-inside space-y-1 text-xs">
              <li><strong>Karte öffnen</strong> unter <em>/map</em> → „✏️ Zelle markieren" aktivieren</li>
              <li><strong>Polygon zeichnen</strong> um eine vom Algorithmus übersehene Zelle (Klick = Punkt, Doppelklick = fertig)</li>
              <li><strong>Filter bestätigen</strong> im Dialog → Filter wird aktiviert, PNG gespeichert</li>
              <li><strong>KI analysieren</strong> (optional) → Button „Mit KI analysieren" sendet PNGs an Claude, Vorschläge erscheinen unten</li>
              <li><strong>Vorschläge übernehmen</strong> → Einzeln oder „Alle übernehmen"</li>
            </ol>
          </section>

          {/* KI-Analyse Erklärung */}
          <section>
            <h3 className="font-semibold text-blue-900 mb-1">🤖 Was macht der KI-Analyse-Button?</h3>
            <p>
              Die letzten gespeicherten Polygon-PNGs (max. {' '}
              <code className="bg-blue-100 px-1 rounded">HITL_MAX_PNGS_FOR_AI</code> = 5 Stück)
              werden zusammen mit den aktiven Filtern an Claude gesendet.
              Claude analysiert die Bilder und schlägt <em>zusätzliche</em> HSV-Bereiche vor
              (Modus <code className="bg-blue-100 px-1 rounded">expand_only</code> —
              bestehende Filter bleiben unverändert). Die Vorschläge erscheinen danach in der
              Galerie und müssen einzeln bestätigt werden.
            </p>
            <p className="mt-1 text-xs text-orange-700">
              ⚠️ Für die KI-Analyse wird ein <em>ANTHROPIC_API_KEY</em> in der .env-Datei
              benötigt und verursacht API-Kosten.
            </p>
          </section>

          {/* Filter de-/aktivieren */}
          <section>
            <h3 className="font-semibold text-blue-900 mb-1">⚙️ Deaktivieren vs. Löschen</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
              <div className="bg-yellow-50 border border-yellow-200 rounded p-2">
                <span className="font-semibold">Deaktivieren</span>
                <p className="mt-1">Filter wird nicht mehr für die Zellen-Erkennung verwendet,
                bleibt aber gespeichert. Das Polygon-PNG steht weiterhin für KI-Analysen zur Verfügung.
                Jederzeit wieder aktivierbar.</p>
              </div>
              <div className="bg-red-50 border border-red-200 rounded p-2">
                <span className="font-semibold">Löschen</span>
                <p className="mt-1">Filter und zugehöriges Polygon-PNG werden dauerhaft entfernt.
                Dieser Schritt ist <em>nicht rückgängig</em> zu machen.</p>
              </div>
            </div>
          </section>

        </div>
      )}
    </div>
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

        {/* Aufklappbares Hilfe-Panel */}
        <HelpPanel />
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
