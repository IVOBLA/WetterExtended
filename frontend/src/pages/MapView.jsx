import React, { useEffect, useState, useRef, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  MapContainer, TileLayer, CircleMarker, Polyline,
  Polygon, Circle, Popup, ImageOverlay, Tooltip,
  useMapEvents, Rectangle, useMap,
} from 'react-leaflet'
import api, { abortApiRequests } from '../api.js'
import { formatCbIrLabel, getCbThresholdState } from '../utils/cbThreshold.js'
import {
  MAP_CENTER_KAERNTEN,
  MAP_ZOOM_DEFAULT,
  MAP_ZOOM_MIN,
  MAP_ZOOM_MAX,
  MAP_TILE_URL,
  MAP_TILE_ATTRIBUTION,
} from '../constants/mapDefaults.js'

/**
 * B112: first_seen-Timestamps kommen als Europe/Vienna-Lokalzeit, NICHT UTC.
 * Kein 'Z' anhängen – Browser interpretiert ISO ohne Offset als lokale Zeit.
 * Format-Beispiele: '2026-06-09_13-41-02' oder '2026-06-09T13:41:02'
 */
function parseViennaLocalTimestamp(ts) {
  if (!ts) return null
  // Normalize: Unterstriche → T, letztes Bindestrich-Paar → Doppelpunkte
  const iso = ts
    .replace(/_(\d{2})-(\d{2})-(\d{2})$/, 'T$1:$2:$3')
    .replace(/_/g, 'T')
  // KEIN 'Z' hinzufügen: Server liefert Vienna-Lokalzeit
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : d
}

// ── B93: Tendenz-Anzeige (Intensität & Größe) im Zell-Popup ──────────────────
// Liest intensity_tendency / size_tendency / tendency_source (gesetzt vom Backend
// in prediction.py, B92). Fallback-Quelle ("kinematic") wird grau dargestellt.
function CellTendency({ obj }) {
  if (!obj) return null
  const it = obj.intensity_tendency
  const st = obj.size_tendency
  if (!it && !st) return null
  const isMl = obj.tendency_source === 'ml'

  const intMap = {
    staerker:   { sym: '↑', txt: 'verstärkt sich', color: '#dc2626' },
    schwaecher: { sym: '↓', txt: 'schwächt ab',    color: '#2563eb' },
    stabil:     { sym: '→', txt: 'stabil',          color: '#6b7280' },
  }
  const sizeMap = {
    waechst:   { sym: '⤢', txt: 'wächst',    color: '#dc2626' },
    schrumpft: { sym: '⤡', txt: 'schrumpft', color: '#2563eb' },
    stabil:    { sym: '◻', txt: 'stabil',     color: '#6b7280' },
  }
  const i = intMap[it] || intMap.stabil
  const s = sizeMap[st] || sizeMap.stabil

  return (
    <div style={{ marginTop: 6, fontSize: 14, lineHeight: 1.5,
                  opacity: isMl ? 1 : 0.7 }}>
      <div style={{ fontWeight: 600, color: '#374151' }}>Tendenz</div>
      <div>
        <span style={{ color: i.color, fontWeight: 700 }}>{i.sym} Intensität:</span>{' '}
        {i.txt}
      </div>
      <div>
        <span style={{ color: s.color, fontWeight: 700 }}>{s.sym} Größe:</span>{' '}
        {s.txt}
      </div>
      <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 2 }}>
        {isMl ? 'ML-Prognose' : 'aus Verlauf (kinematisch)'}
      </div>
    </div>
  )
}

const lineageColor = {
  new: 'green', continued: 'blue', merged: 'orange', split: 'magenta',
}

const CELL_POLYGON_COLOR = '#0b1f5e'
const CELL_POLYGON_FILL_OPACITY = 0.25

// B118: Merged-Zellen deutlich hervorheben. Alle aktuellen Zellpolygone nutzen
// dieselbe dunkelblaue Farbe; lineage bleibt nur über Strichstärke/-muster sichtbar.
// merged → dicker (4) + auffällig gestrichelt; split → 3 + fein gestrichelt;
// new/continued → unverändert durchgezogen (2).
function cellStroke(lineage) {
  if (lineage === 'merged') return { color: CELL_POLYGON_COLOR, weight: 4, dashArray: '10,6' }
  if (lineage === 'split')  return { color: CELL_POLYGON_COLOR, weight: 3, dashArray: '4,4' }
  return { color: CELL_POLYGON_COLOR, weight: 2, dashArray: undefined }
}

// FlyToCell: Liest URL-Parameter lat/lon/zoom aus und zentriert die Karte.
// Muss als Kind-Komponente innerhalb von <MapContainer> eingebunden werden
// (benötigt den Leaflet-Karten-Context via useMap()).
function FlyToCell() {
  const map = useMap()
  const [searchParams] = useSearchParams()
  useEffect(() => {
    const lat  = parseFloat(searchParams.get('lat'))
    const lon  = parseFloat(searchParams.get('lon'))
    const zoom = parseInt(searchParams.get('zoom') || '12', 10)
    if (!isNaN(lat) && !isNaN(lon)) {
      map.setView([lat, lon], isNaN(zoom) ? 12 : zoom, { animate: true })
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}

// ── Animations-Steuerleiste ──────────────────────────────────────────────────
function AnimationBar({ frames, currentIdx, playing, speed,
  onSetIdx, onPlay, onPause, onSpeed }) {
  const cur = frames[currentIdx]
  if (!frames.length) return null
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <button onClick={() => { onPause(); onSetIdx(Math.max(0, currentIdx - 1)) }}
        className="px-2 py-0.5 border rounded hover:bg-gray-100 select-none">◀</button>
      <button onClick={playing ? onPause : onPlay}
        className="px-3 py-0.5 border rounded bg-blue-50 hover:bg-blue-100 font-medium select-none">
        {playing ? '⏸' : '▶'}
      </button>
      <button onClick={() => { onPause(); onSetIdx(Math.min(frames.length - 1, currentIdx + 1)) }}
        className="px-2 py-0.5 border rounded hover:bg-gray-100 select-none">▶</button>
      <input type="range" min="0" max={frames.length - 1} value={currentIdx}
        onChange={e => { onPause(); onSetIdx(Number(e.target.value)) }}
        className="w-28 accent-blue-600" />
      <span className="font-mono text-xs font-semibold w-10 text-center">
        {cur?.label ?? '—'}
      </span>
      {cur?.gap_min != null && cur.gap_min > 7 && (
        <span title={`Zeitsprung: ${cur.gap_min} min seit letztem Frame`}
          style={{ fontSize: 10, color: '#f59e0b', fontWeight: 700 }}>
          ⏱+{Math.round(cur.gap_min)}m
        </span>
      )}
      {[500, 300, 150].map(s => (
        <button key={s} onClick={() => onSpeed(s)}
          className={`text-xs px-1.5 py-0.5 border rounded select-none ${
            speed === s ? 'bg-blue-600 text-white border-blue-600' : 'hover:bg-gray-100'}`}>
          {s === 500 ? '1×' : s === 300 ? '2×' : '4×'}
        </button>
      ))}
    </div>
  )
}

// ── Forecast-Ghost-Layer ─────────────────────────────────────────────────────
// Verschiebt die Zell-Kontur entlang des vorhergesagten Pfades und zeigt sie
// als gestricheltes, halbtransparentes "Prognose"-Polygon. Rein clientseitig.
function _forecastPoints(o, forecast) {
  // Robust gegen verschiedene Forecast-Strukturen: Objekt traegt Felder selbst,
  // ODER forecast ist nach ID gekeyt, ODER forecast ist ein Array mit id.
  const horizons = [10, 20, 30, 40, 60]
  let src = o
  if (forecast) {
    if (!Number.isNaN(Number(forecast?.[o.id]?.lat ?? NaN)) || forecast?.[o.id]) src = forecast[o.id]
    else if (Array.isArray(forecast)) {
      const f = forecast.find(x => String(x.id) === String(o.id))
      if (f) src = f
    } else if (Array.isArray(forecast?.objects)) {
      const f = forecast.objects.find(x => String(x.id) === String(o.id))
      if (f) src = f
    }
  }
  const pts = { 0: [o.lat, o.lon] }
  horizons.forEach(h => {
    const la = src?.[`forecast_lat_${h}`]
    const lo = src?.[`forecast_lon_${h}`]
    if (la != null && lo != null) pts[h] = [Number(la), Number(lo)]
  })
  return pts
}

function _interpDelta(o, forecast, leadMin) {
  // Liefert [dLat, dLon] der Schwerpunktverschiebung bei leadMin Minuten.
  const pts = _forecastPoints(o, forecast)
  const keys = Object.keys(pts).map(Number).sort((a, b) => a - b)
  if (keys.length < 2 || o.lat == null || o.lon == null) return null
  const maxH = keys[keys.length - 1]
  const L = Math.min(leadMin, maxH)
  let lo = keys[0], hi = keys[keys.length - 1]
  for (let i = 0; i < keys.length - 1; i++) {
    if (L >= keys[i] && L <= keys[i + 1]) { lo = keys[i]; hi = keys[i + 1]; break }
  }
  const [laLo, loLo] = pts[lo]
  const [laHi, loHi] = pts[hi]
  const t = hi === lo ? 0 : (L - lo) / (hi - lo)
  const la = laLo + (laHi - laLo) * t
  const ln = loLo + (loHi - loLo) * t
  return [la - o.lat, ln - o.lon]
}

function ForecastGhostLayer({ objects, forecast, leadMin }) {
  if (!leadMin || leadMin <= 0) return null
  return (
    <>
      {objects.map(o => {
        if (!o.contour_geo || o.contour_geo.length < 3) return null
        const d = _interpDelta(o, forecast, leadMin)
        if (!d) return null
        const [dLat, dLon] = d
        // contour_geo ist [lon, lat] -> Leaflet braucht [lat, lon]
        const shifted = o.contour_geo.map(p => [p[1] + dLat, p[0] + dLon])
        const frac = Math.min(leadMin / 60, 1)
        const opacity = 0.30 * (1 - 0.6 * frac)   // weiter in Zukunft = blasser
        return (
          <Polygon
            key={'ghost_' + o.id}
            positions={shifted}
            pathOptions={{
              color: '#6a1b9a', weight: 2, dashArray: '6,5',
              fillColor: '#9c27b0', fillOpacity: opacity, interactive: false,
            }}
            pane="overlayPane"
          >
            <Tooltip direction="top" opacity={0.9}>
              <span>Prognose +{leadMin} min · Zelle {o.id}</span>
            </Tooltip>
          </Polygon>
        )
      })}
    </>
  )
}

function Legend({ horizons, colors }) {
  return (
    <div className="bg-white border rounded p-2 mb-2 shadow-sm text-sm flex flex-wrap gap-4 items-center">
      <strong>Horizonte:</strong>
      {horizons.map(h => (
        <span key={h} className="flex items-center gap-1">
          <span style={{ display:'inline-block', width:16, height:3,
            background: colors[h] || colors[String(h)] || '#888' }} />
          +{h} min
        </span>
      ))}
      <span className="border-l pl-3 flex items-center gap-2 text-xs text-gray-500">
        <strong>Intensität:</strong>
        <span className="flex items-center gap-1">
          <span style={{ display:'inline-block', width:12, height:12, borderRadius:2, background:'#6a1b9a', opacity:0.85 }}/>
          Sehr stark
        </span>
        <span className="flex items-center gap-1">
          <span style={{ display:'inline-block', width:12, height:12, borderRadius:2, background:'#c62828', opacity:0.75 }}/>
          Stark
        </span>
        <span className="flex items-center gap-1">
          <span style={{ display:'inline-block', width:12, height:12, borderRadius:2, background:'#f9a825', opacity:0.65 }}/>
          Mittel
        </span>
      </span>
      <span className="border-l pl-3 flex items-center gap-2 text-xs text-gray-500">
        <span style={{ display:'inline-block', width:8, height:8, borderRadius:'50%', background:'#fbbf24' }}/>
        Blitz (−)
        <span style={{ display:'inline-block', width:8, height:8, borderRadius:'50%', background:'#f97316' }}/>
        Blitz (+)
      </span>
      <span className="border-l pl-3 flex items-center gap-2 text-xs text-gray-500">
        <span style={{ display:'inline-block', width:16, height:2, background:'#888', borderTop:'2px dashed #888' }}/>
        Schätzpfeil
        <span style={{ display:'inline-block', width:16, height:2, borderTop:'2px dashed #6a1b9a' }}/>
        Unsicherheit
        <span className="text-purple-700 font-bold text-base leading-none">⊕</span>
        Stationär
        <span className="text-red-600 font-bold">🧊</span>
        Hagel
      </span>
      <span style={{display:'flex',alignItems:'center',gap:3}}>
        <span style={{width:12,height:12,borderRadius:'50%',border:'2px dashed #a855f7',display:'inline-block'}}/>
        <span style={{fontSize:10}}>CB / IR-Vorläufer</span>
      </span>
      <span className="border-l pl-3 flex items-center gap-2 text-xs text-gray-500">
        <strong>Zelltyp:</strong>
        <span className="flex items-center gap-1">
          <span style={{ display:'inline-block', width:18, height:0, borderTop:'4px dashed orange' }}/>
          merged
        </span>
        <span className="flex items-center gap-1">
          <span style={{ display:'inline-block', width:18, height:0, borderTop:'3px dashed magenta' }}/>
          split
        </span>
        <span className="flex items-center gap-1">
          <span style={{ display:'inline-block', width:18, height:0, borderTop:'2px solid blue' }}/>
          fortgeführt
        </span>
        <span className="flex items-center gap-1">
          <span style={{ display:'inline-block', width:18, height:0, borderTop:'2px solid green' }}/>
          neu
        </span>
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Manuelles Zell-Markieren — Polygon-Zeichner (Human-in-the-Loop)
// ---------------------------------------------------------------------------

/**
 * PolygonDrawer: Sammelt Klick-Punkte auf der Karte und ruft onComplete auf.
 * - Einfachklick: Punkt hinzufügen
 * - Doppelklick:  Polygon abschließen (mind. 3 Punkte erforderlich)
 * - ESC-Taste:    Zeichnen abbrechen
 */
function MapStateProbe({ targetRef }) {
  const map = useMap()
  React.useEffect(() => {
    if (!map || !targetRef) return
    const update = () => {
      try {
        const b = map.getBounds()
        targetRef.current = {
          zoom: map.getZoom(),
          bounds: {
            south: b.getSouth(),
            west: b.getWest(),
            north: b.getNorth(),
            east: b.getEast(),
          },
        }
      } catch { /* no-op */ }
    }
    update()
    map.on('zoomend', update)
    map.on('moveend', update)
    return () => {
      map.off('zoomend', update)
      map.off('moveend', update)
    }
  }, [map, targetRef])
  return null
}

function PolygonDrawer({ active, onComplete, onCancel }) {
  const [pts, setPts] = React.useState([])

  // ESC bricht ab
  React.useEffect(() => {
    if (!active) { setPts([]); return }
    const handler = e => { if (e.key === 'Escape') { setPts([]); onCancel() } }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [active, onCancel])

  useMapEvents({
    click(e) {
      if (!active) return
      setPts(prev => [...prev, [e.latlng.lat, e.latlng.lng]])
    },
    dblclick(e) {
      if (!active || pts.length < 3) return
      e.originalEvent.preventDefault()
      e.originalEvent.stopPropagation()
      const closed = [...pts, pts[0]]
      setPts([])
      onComplete(closed)
    },
  })

  if (!active || pts.length === 0) return null

  return (
    <>
      {pts.map((p, i) => (
        <CircleMarker key={`pm-${i}`} center={p} radius={5}
          pathOptions={{ color: '#f59e0b', fillColor: '#fbbf24',
            fillOpacity: 1, weight: 2 }} />
      ))}
      {pts.length >= 2 && (
        <Polyline positions={pts}
          pathOptions={{ color: '#f59e0b', weight: 2, dashArray: '6,4' }} />
      )}
    </>
  )
}

/**
 * HitlModal: Human-in-the-Loop Dialog nach Polygon-Analyse.
 * Zeigt HSV-Messwerte, Farbvorschau, vorgeschlagenen Filter.
 * Benutzer bestätigt oder verwirft.
 */
function HitlModal({ loading, result, onConfirm, onClose }) {
  if (!loading && !result) return null

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: 9999, padding: 16,
    }}>
      <div style={{
        background: '#fff', borderRadius: 12, padding: 24,
        maxWidth: 480, width: '100%',
        boxShadow: '0 8px 32px rgba(0,0,0,0.28)',
      }}>
        {/* Ladeindikator */}
        {loading && (
          <div style={{ textAlign: 'center', padding: '32px 0' }}>
            <div style={{ fontSize: 40, marginBottom: 12,
              animation: 'spin 1s linear infinite' }}>🔍</div>
            <p style={{ color: '#6b7280' }}>Radarbild wird analysiert...</p>
          </div>
        )}

        {/* Fehler */}
        {result && !result.ok && (
          <>
            <h2 style={{ color: '#dc2626', marginBottom: 8 }}>Analyse fehlgeschlagen</h2>
            <p style={{ fontSize: 13, color: '#374151',
              fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>
              {result.error}
            </p>
            <button onClick={onClose}
              style={{ marginTop: 16, width: '100%', padding: '8px 0',
                background: '#f3f4f6', border: '1px solid #d1d5db',
                borderRadius: 8, cursor: 'pointer' }}>
              Schließen
            </button>
          </>
        )}

        {/* Erfolg */}
        {result?.ok && (
          <>
            <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 16 }}>
              🔬 Zell-Analyse — Filter vorschlagen
            </h2>

            {/* Farbvorschau + Statistik */}
            <div style={{ display: 'flex', gap: 12, marginBottom: 16,
              alignItems: 'flex-start' }}>
              <div style={{
                width: 56, height: 56, borderRadius: 8, flexShrink: 0,
                border: '2px solid #d1d5db',
                background: `rgb(${result.preview_rgb.join(',')})`,
              }} />
              <div style={{ fontSize: 13 }}>
                <p style={{ fontWeight: 600 }}>
                  {result.pixel_count} Pixel analysiert
                </p>
                <p style={{ color: '#6b7280', marginTop: 2 }}>
                  Label:{' '}
                  <span style={{ fontFamily: 'monospace',
                    background: '#f3f4f6',
                    padding: '1px 5px', borderRadius: 4 }}>
                    {result.suggested_label}
                  </span>
                </p>
                <p style={{ color: '#9ca3af', fontSize: 11, marginTop: 2 }}>
                  Bild: {result.radar_path}
                </p>
              </div>
            </div>

            {/* HSV-Messwerte */}
            <div style={{ background: '#f9fafb', borderRadius: 8,
              padding: '10px 14px', marginBottom: 12,
              fontFamily: 'monospace', fontSize: 12 }}>
              <p style={{ fontWeight: 700, color: '#374151',
                marginBottom: 4 }}>HSV-Messwerte im Polygon:</p>
              <p>Hue: {result.hsv_stats.h_min}–{result.hsv_stats.h_max}
                <span style={{ color: '#9ca3af' }}>
                  {' '}(Ø {result.hsv_stats.h_mean})
                </span>
              </p>
              <p>Sat: {result.hsv_stats.s_min}–{result.hsv_stats.s_max}</p>
              <p>Val: {result.hsv_stats.v_min}–{result.hsv_stats.v_max}</p>
            </div>

            {/* Vorgeschlagener Filter */}
            <div style={{
              background: '#fffbeb', border: '1px solid #fcd34d',
              borderRadius: 8, padding: '10px 14px', marginBottom: 16,
            }}>
              <p style={{ fontWeight: 700, color: '#92400e',
                fontSize: 13, marginBottom: 4 }}>
                📐 Vorgeschlagener HSV-Filter (±5 Toleranz, 5./95. Perzentil):
              </p>
              <p style={{ fontFamily: 'monospace', fontSize: 12,
                color: '#78350f' }}>
                Lower: [{result.suggested_range[0].join(', ')}]<br/>
                Upper: [{result.suggested_range[1].join(', ')}]
              </p>
              {result.already_covered && (
                <p style={{ color: '#065f46', fontSize: 12, marginTop: 6 }}>
                  ✅ Dieser Bereich ist bereits im aktiven Filter abgedeckt.
                </p>
              )}
            </div>

            {/* Buttons */}
            {result.already_covered ? (
              <div>
                <p style={{ fontSize: 12, color: '#065f46', marginBottom: 12 }}>
                  Die Zelle sollte bereits erkannt werden. Falls sie trotzdem
                  fehlt, kann der Wert zusätzlich ergänzt werden.
                </p>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button onClick={onClose}
                    style={{ flex: 1, padding: '9px 0', background: '#f3f4f6',
                      border: '1px solid #d1d5db', borderRadius: 8,
                      cursor: 'pointer', fontSize: 13 }}>
                    Schließen
                  </button>
                  <button onClick={onConfirm}
                    style={{ flex: 1, padding: '9px 0', background: '#f59e0b',
                      border: 'none', borderRadius: 8, color: '#fff',
                      cursor: 'pointer', fontSize: 13, fontWeight: 600 }}>
                    Trotzdem ergänzen
                  </button>
                </div>
              </div>
            ) : (
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={onClose}
                  style={{ flex: 1, padding: '9px 0', background: '#f3f4f6',
                    border: '1px solid #d1d5db', borderRadius: 8,
                    cursor: 'pointer', fontSize: 13 }}>
                  Abbrechen
                </button>
                <button onClick={onConfirm}
                  style={{ flex: 1, padding: '9px 0', background: '#2563eb',
                    border: 'none', borderRadius: 8, color: '#fff',
                    cursor: 'pointer', fontSize: 14, fontWeight: 700 }}>
                  ✅ Filter übernehmen
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

export default function MapView() {
  const [objects,      setObjects]      = useState([])
  const [forecast,     setForecast]     = useState({ features: [] })
  const [showGhosts, setShowGhosts] = useState(true)
  const [ghostLead, setGhostLead] = useState(30)
  const [locations,    setLocations]    = useState({ watchlist: [], hits: [], colors: {} })
  const [horizons,     setHorizons]     = useState({ horizons: [10,20,30,40,60], colors: {}, styles: {} })
  const [radarTiming,  setRadarTiming]  = useState(null)
  const [radarBounds,  setRadarBounds]  = useState(null)
  const [radarOpacity, setRadarOpacity] = useState(0.65)
  const [showRadar,    setShowRadar]    = useState(true)
  const [radarTs,        setRadarTs]        = useState(0)
  const [lightning,      setLightning]      = useState([])
  const [showLightning,  setShowLightning]  = useState(true)
  const [showRisk,      setShowRisk]      = useState(false)
  const [showIrCells,   setShowIrCells]   = useState(true)
  const [riskGrid,      setRiskGrid]      = useState([])
  const [riskGridStep, setRiskGridStep] = useState(0.05)
  const [riskGridError, setRiskGridError] = useState(false)
  const [irCells,       setIrCells]       = useState([])
  const [lightningAge,   setLightningAge]   = useState(15)  // Minuten

  // Animation
  const [frames,     setFrames]     = useState([])
  const [currentIdx, setCurrentIdx] = useState(-1)
  const [playing,    setPlaying]    = useState(false)
  const [speed,      setSpeed]      = useState(500)
  const timerRef        = useRef(null)
  const frameLoadTimer  = useRef(null)
  const frameDataCache  = useRef({})
  const playingRef      = useRef(false)
  const pollRef         = useRef(null)   // B90: schedulePoll-Timer
  const isLoadingRef    = useRef(false)
  const lastImgRef      = useRef(null)   // B90: letzter Radar-Timestamp

  // ── Manuelles Zell-Markieren ──────────────────────────────────────────────
  const [cellMarkActive,   setCellMarkActive]   = useState(false)
  const [hitlLoading,      setHitlLoading]      = useState(false)
  const [hitlResult,       setHitlResult]       = useState(null)   // API-Antwort
  const [hitlConfirmed,    setHitlConfirmed]    = useState(false)

  const currentFrame = frames[currentIdx] ?? null
  const radarUrl = currentFrame
    ? `/api/radar_image?ts=${currentFrame.ts}`
    : `/api/radar_image?t=${radarTs}`

  // Frames begrenzt vorausladen: aktueller Frame ±3, nicht alle Frames parallel.
  useEffect(() => {
    if (!frames.length) return
    const center = currentIdx >= 0 ? currentIdx : (frames.length - 1)
    const subset = frames.slice(Math.max(0, center - 3), Math.min(frames.length, center + 4))
    const imgs = subset.map(f => {
      const img = new window.Image()
      img.src = `/api/radar_image?ts=${f.ts}`
      return img
    })
    return () => { imgs.forEach(img => { img.src = '' }) }
  }, [frames, currentIdx])

  // Auto-Play
  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current)
    if (!playing || frames.length === 0) return
    timerRef.current = setInterval(() => {
      setCurrentIdx(i => (i + 1) % frames.length)
    }, speed)
    return () => clearInterval(timerRef.current)
  }, [playing, speed, frames.length])

  const handlePlay  = useCallback(() => { setPlaying(true);  playingRef.current = true  }, [])
  const handlePause = useCallback(() => { setPlaying(false); playingRef.current = false }, [])

  // B90: Intelligenter Poll — wartet bis kurz nach next_fetch_estimated_utc
  const schedulePoll = useCallback((timing) => {
    if (pollRef.current) clearTimeout(pollRef.current)
    let delayMs = 60000
    if (timing?.next_fetch_estimated_utc) {
      const nextFetch = new Date(timing.next_fetch_estimated_utc).getTime()
      const now       = Date.now()
      const msUntil   = nextFetch - now
      delayMs = msUntil <= 0 ? 22000 : Math.min(msUntil + 5000, 90000)
    }
    pollRef.current = setTimeout(() => load(), delayMs)
  }, [])

  async function load() {
    if (isLoadingRef.current) return
    isLoadingRef.current = true
    try {
      // Schritt 1: Metadaten + Frames parallel laden
      const [c, d, timing, bounds, framesData, lightningData] = await Promise.all([
        api.get('/api/locations'),
        api.get('/api/horizons'),
        api.get('/api/radar_timing').catch(() => null),
        api.get('/api/radar_bounds').catch(() => null),
        api.get('/api/radar_frames').catch(() => null),
        api.get(`/api/lightning?max_age_min=${lightningAge}`).catch(() => null),
      ])
      setLocations(c); setHorizons(d)
      if (timing) {
        setRadarTiming(timing)
        // B90: neues Radarbild erkannt → Timestamp-Vergleich
        const newTs = timing.last_radar_image_utc
        if (newTs && newTs !== lastImgRef.current) {
          lastImgRef.current = newTs
          setRadarTs(Date.now())
        }
        schedulePoll(timing)
      } else {
        schedulePoll(null)
      }
      if (bounds?.bounds) setRadarBounds(bounds.bounds)
      if (lightningData?.strikes) setLightning(lightningData.strikes)

      // Schritt 2: Frame-Timestamp bestimmen, objects/forecast synchron laden.
      // Auch ohne Animation wird immer der neueste Frame-Timestamp verwendet —
      // garantiert dass angezeigte Zellen zum angezeigten Radarbild passen.
      let latestTs = null
      if (framesData?.frames?.length) {
        const latestIdx = framesData.latest_idx ?? framesData.frames.length - 1
        latestTs = framesData.frames[latestIdx]?.ts ?? null
        setFrames(framesData.frames)
        if (!playingRef.current) setCurrentIdx(latestIdx)
      }
      const [objs, fc] = await Promise.all([
        api.get(latestTs ? `/api/objects?ts=${latestTs}` : '/api/objects'),
        api.get(latestTs ? `/api/forecast?ts=${latestTs}` : '/api/forecast'),
      ])
      if (!playingRef.current) {
        setObjects(objs)
        setForecast(fc)
      }
      setRadarTs(Date.now())
    } catch (e) {
      if (e?.name !== 'AbortError') console.error(e)
    } finally {
      isLoadingRef.current = false
    }
  }

  // B90: kein starres Intervall mehr — schedulePoll übernimmt das Timing
  useEffect(() => {
    load()
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current)
      abortApiRequests()
    }
  }, [])

  // Frame-Sync für Animation: bei Scrubbing objects/forecast für den
  // angezeigten Frame laden.
  // Cache verhindert Re-Fetch bei Animation (sonst ~8 Req/s bei Auto-Play).
  useEffect(() => {
    if (!frames.length || currentIdx < 0) return
    const frame = frames[currentIdx]
    if (!frame?.ts) return
    const cached = frameDataCache.current[frame.ts]
    if (cached) {
      setObjects(cached.objects)
      setForecast(cached.forecast)
      return
    }
    if (frameLoadTimer.current) clearTimeout(frameLoadTimer.current)
    frameLoadTimer.current = setTimeout(() => {
      Promise.all([
        api.get(`/api/objects?ts=${frame.ts}`),
        api.get(`/api/forecast?ts=${frame.ts}`),
      ]).then(([objs, fc]) => {
        frameDataCache.current[frame.ts] = { objects: objs, forecast: fc }
        setObjects(objs)
        setForecast(fc)
      }).catch(() => {})
    }, 200)
    return () => { if (frameLoadTimer.current) clearTimeout(frameLoadTimer.current) }
  }, [currentIdx, frames])

  const fmtTime = utcStr => utcStr
    ? new Date(utcStr).toLocaleTimeString('de-AT', { hour:'2-digit', minute:'2-digit' })
    : '—'

  // ── Capture aktueller Map-Status (Zoom + Bounds) beim Polygon-Abschluss ──
  const mapStateRef = React.useRef({ zoom: 11, bounds: null })

  // ── Handler: Polygon abgeschlossen → Analyse aufrufen ────────────────────
  const handlePolygonComplete = React.useCallback(async (latlngPoints) => {
    setCellMarkActive(false)
    setHitlLoading(true)
    setHitlResult(null)
    try {
      // GeoJSON-Konvention: [lon, lat]
      const coords = latlngPoints.map(([lat, lng]) => [lng, lat])
      const { zoom, bounds } = mapStateRef.current || {}
      const payload = { coordinates: coords }
      if (typeof zoom === 'number') payload.zoom_level = zoom
      if (bounds) payload.map_bounds = bounds
      const res = await api.post('/api/analyze_cell_polygon', payload)
      setHitlResult(res)
    } catch (e) {
      setHitlResult({ ok: false, error: e.message ?? String(e) })
    } finally {
      setHitlLoading(false)
    }
  }, [showIrCells])

  // ── Handler: Benutzer bestätigt Filter-Übernahme ──────────────────────────
  const handleHitlConfirm = React.useCallback(async () => {
    if (!hitlResult?.suggested_range) return
    try {
      const { zoom } = mapStateRef.current || {}
      await api.post('/api/thresholds/add_range', {
        range: hitlResult.suggested_range,
        label: hitlResult.suggested_label,
        polygon_px: hitlResult.polygon_px || [],
        radar_filename: hitlResult.radar_filename || hitlResult.radar_path,
        zoom_level: typeof zoom === 'number' ? zoom : undefined,
      })
      setHitlConfirmed(true)
      setTimeout(() => {
        setHitlResult(null)
        setHitlConfirmed(false)
      }, 2500)
    } catch (e) {
      alert('Fehler beim Speichern: ' + (e.message ?? String(e)))
    }
  }, [hitlResult])

  const handleHitlClose = React.useCallback(() => {
    setHitlResult(null)
    setHitlLoading(false)
  }, [])

  // Risiko-Grid laden — alle 60 s, unabhaengig von frames/lightning
  useEffect(() => {
    function loadRisk() {
      api.get('/api/risk_grid')
        .then(d => {
          setRiskGrid(d.cells || [])
          setRiskGridStep(typeof d.grid_step === 'number' && d.grid_step > 0
            ? d.grid_step : 0.05)
          setRiskGridError(false)
        })
        .catch((err) => {
          console.error('Risk grid failed', err)
          setRiskGrid([])
          setRiskGridError(true)
        })
    }
    if (showIrCells) {
      fetch('/api/objects?include_ir=1')
        .then(r => r.json())
        .then(d => {
          const items = Array.isArray(d) ? d : (d.objects || [])
          const radarCellIds = new Set(items
            .filter(o => o.cell_id && o._type !== 'ir_precursor_cell' && o._type !== 'ir_cell')
            .map(o => String(o.cell_id)))
          const irOnly = items
            .filter(o => (o._type === 'ir_precursor_cell' || o._type === 'ir_cell') && Number(o.ir_only_precursor ?? 0) === 1 && o.display_as_precursor !== false && o.radar_confirmed !== true && (!o.cell_id || !radarCellIds.has(String(o.cell_id))))
          setIrCells(irOnly)
        })
        .catch(() => setIrCells([]))
    } else {
      setIrCells([])
    }
    loadRisk()
    const t = setInterval(loadRisk, 60_000)
    return () => clearInterval(t)
  }, [showIrCells])

  return (
    <div>
      <h1 className="text-2xl font-bold mb-3">Live-Karte</h1>

      {/* Timing Info-Bar */}
      {radarTiming && (
        <div className="flex flex-wrap gap-4 text-xs text-gray-600 bg-blue-50
                        border border-blue-200 rounded px-3 py-1.5 mb-2">
          <span>🛰 Letztes Radar:{' '}
            <strong>{currentFrame?.label ?? fmtTime(radarTiming.last_radar_image_utc)}</strong>
          </span>
          <span>⏱ Nächste Abfrage:{' '}
            <strong>
              {radarTiming.next_fetch_estimated_utc
                ? fmtTime(radarTiming.next_fetch_estimated_utc)
                : `~${Math.round((radarTiming.loop_interval_s || 120) / 60)} min`}
            </strong>
          </span>
          <span className={radarTiming.cells_active ? 'text-red-600 font-semibold' : 'text-gray-400'}>
            {radarTiming.cells_active ? '⚡ Zellen aktiv' : '✓ Keine aktiven Schwergewitter-Zellen'}
          </span>
          {showRisk && riskGridError && (
            <span className="text-red-500 font-semibold">
              ⚠ Risikozonen nicht verfügbar
            </span>
          )}
          {showRisk && !riskGridError && riskGrid.length === 0 && (
            <span className="text-gray-400">
              — Keine Risikozonen
            </span>
          )}
        </div>
      )}

      <Legend horizons={horizons.horizons} colors={horizons.colors} />


      {/* Overlay-Steuerung + Animation */}
      <div className="flex flex-wrap items-center gap-4 mb-2 text-sm bg-gray-50 border rounded px-3 py-2">
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input type="checkbox" checked={showRadar} onChange={e => setShowRadar(e.target.checked)} />
          <span className="font-medium">Radar</span>
        </label>
        {showRadar && (
          <label className="flex items-center gap-2">
            <span className="text-gray-500">Deckkraft:</span>
            <input type="range" min="0" max="100"
              value={Math.round(radarOpacity * 100)}
              onChange={e => setRadarOpacity(Number(e.target.value) / 100)}
              className="w-24 accent-blue-600" />
            <span className="font-mono text-xs w-8 text-right">{Math.round(radarOpacity * 100)}%</span>
          </label>
        )}
        {showRadar && frames.length > 0 && (
          <AnimationBar
            frames={frames} currentIdx={currentIdx} playing={playing} speed={speed}
            onSetIdx={setCurrentIdx} onPlay={handlePlay} onPause={handlePause} onSpeed={setSpeed}
          />
        )}
        <label className="flex items-center gap-1 cursor-pointer select-none text-xs">
          <input type="checkbox" checked={showLightning}
            onChange={e => setShowLightning(e.target.checked)}
            className="accent-yellow-500" />
          <span>⚡ Blitze</span>
          <select value={lightningAge}
            onChange={e => setLightningAge(Number(e.target.value))}
            className="text-xs border rounded px-1 py-0 ml-1"
            title="Blitze der letzten N Minuten anzeigen">
            {[5, 10, 15, 30].map(m => (
              <option key={m} value={m}>{m} min</option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1 cursor-pointer select-none text-xs">
          <input type="checkbox" checked={showRisk}
            onChange={e => setShowRisk(e.target.checked)}
            className="accent-red-500" />
          <span>🌩 Risikozonen</span>
        </label>
        <label className="flex items-center gap-1 cursor-pointer select-none text-xs">
          <input
            type="checkbox"
            checked={showIrCells}
            onChange={e => setShowIrCells(e.target.checked)}
            className="accent-purple-600"
            title="IR-Vorläufer / CB: Hohe Konvektionswolken aus MSG IR108 (Erkennungsschwelle BT < 230 K ≈ > 10.000 m MSL). Angezeigte Wolkentop-Höhe kann abweichen. Rot = Overshooting Top (BT < 215 K, typ. > 12.300 m)."
          />
          <span>🛰 CB / IR-Vorläufer</span>
        </label>
        <button onClick={load}
          className="text-xs text-blue-600 hover:text-blue-800 underline ml-auto">↺ Neu laden</button>
        {/* Manuelles Zell-Markieren */}
        <button
          onClick={() => {
            setCellMarkActive(v => !v)
            setHitlResult(null)
          }}
          className={`text-xs px-2 py-1 rounded border select-none ${
            cellMarkActive
              ? 'bg-amber-400 border-amber-500 text-white font-semibold'
              : 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50'
          }`}
          title="Zelle manuell einzeichnen: Klicken = Punkt setzen, Doppelklick = abschließen, ESC = abbrechen"
        >
          {cellMarkActive
            ? '✏️ Zeichnen… (Dblklick = fertig, ESC = abbrechen)'
            : '✏️ Zelle markieren'}
        </button>
      </div>

      <div className="flex items-center gap-3 text-sm mb-2 bg-white border rounded p-2 shadow-sm">
        <label className="flex items-center gap-1 select-none">
          <input type="checkbox" checked={showGhosts}
            onChange={e => setShowGhosts(e.target.checked)} />
          🔮 Zell-Prognose
        </label>
        <span className="text-gray-600">+{ghostLead} min</span>
        <input type="range" min="0" max="60" step="5" value={ghostLead}
          disabled={!showGhosts}
          onChange={e => setGhostLead(Number(e.target.value))}
          className="w-40 accent-purple-600" />
        <span className="text-xs text-gray-400">
          gestricheltes violettes Polygon = vorhergesagte Zellposition (keine Messung)
        </span>
      </div>

      <MapContainer
        center={MAP_CENTER_KAERNTEN}
        zoom={MAP_ZOOM_DEFAULT}
        minZoom={MAP_ZOOM_MIN}
        maxZoom={MAP_ZOOM_MAX}
        style={{ height:'70vh', borderRadius:8 }}>
        <TileLayer url={MAP_TILE_URL} attribution={MAP_TILE_ATTRIBUTION} />

        {showRadar && radarBounds && (
          <ImageOverlay
            key={radarUrl}
            url={radarUrl}
            bounds={radarBounds}
            opacity={radarOpacity}
            zIndex={200}
          />
        )}

        {/* Zellen: frame-synchron — objects enthält bereits nur Zellen des angezeigten Frames */}
        {objects.map(o => {
          if (!o.contour_geo || o.contour_geo.length < 3) return null
          const outerPos    = o.contour_geo.map(p => [p[1], p[0]])
          const stroke      = cellStroke(o.lineage)
          const borderColor = lineageColor[o.lineage] || '#888'
          return (
            <React.Fragment key={'cell_' + o.id}>
              <Polygon
                positions={outerPos}
                pathOptions={{ color:stroke.color, weight:stroke.weight, dashArray:stroke.dashArray, fillColor:CELL_POLYGON_COLOR, fillOpacity:CELL_POLYGON_FILL_OPACITY, interactive:true }}
                eventHandlers={{ click: (e) => { e.target.openPopup(e.latlng) } }}
                pane="tooltipPane"
              >
                <Popup autoPan={true} keepInView={true}>
                  <div><strong>{o.id}</strong> ({o.lineage})</div>
                  {o.severity && (
                    <div style={{fontSize:'0.8em', marginTop:2}}>
                      <span style={{
                        display:'inline-block', padding:'1px 5px', borderRadius:3, color:'#fff',
                        background: o.severity.level >= 4 ? '#6a1b9a'
                                  : o.severity.level === 3 ? '#c62828'
                                  : o.severity.level === 2 ? '#f9a825' : '#9e9e9e'
                      }}>Schwere {o.severity.level}/4</span>
                      <div style={{marginTop:2,color:'#444'}}>
                        🌧 {o.severity.rain_mm_h} mm/h · 💨 {o.severity.gust_kmh} km/h
                        {o.severity.hail_cat !== 'keiner' && <> · 🧊 {o.severity.hail_cat} ({Math.round(o.severity.hail_prob*100)}%)</>}
                      </div>
                    </div>
                  )}
                  {o.first_seen && (
                    <div style={{fontSize:'0.8em',color:'#666'}}>
                      Erstmals: {(() => { try {
                        const d = parseViennaLocalTimestamp(o.first_seen)
                        return d.toLocaleTimeString('de-AT', {hour:'2-digit',minute:'2-digit'})
                      } catch { return o.first_seen } })()}
                    </div>
                  )}
                  {o.total_active_frames != null && (
                    <div style={{fontSize:'0.8em',color:'#666'}}>
                      {(() => {
                        const tf = o.total_active_frames ?? 0
                        let minStr = ''
                        if (o.first_seen) {
                          try {
                            const fs = parseViennaLocalTimestamp(o.first_seen)
                            const diffMin = Math.round((Date.now() - fs.getTime()) / 60000)
                            if (diffMin >= 0 && diffMin < 1440) minStr = ` (~${diffMin} min)`
                          } catch (_) {}
                        }
                        if (!minStr) minStr = ` (~${Math.round(tf * 2)} min)`
                        return `Aktiv: ${tf} ${tf === 1 ? 'Frame' : 'Frames'}${minStr}`
                      })()}
                    </div>
                  )}
                  {o.speed_kmh != null && (
                    <div style={{fontSize:'0.85em'}}>
                      🧭 {o.speed_kmh} km/h
                      {o.direction_deg != null && (
                        ' ' + ['N','NNO','NO','ONO','O','OSO','SO','SSO',
                                'S','SSW','SW','WSW','W','WNW','NW','NNW'][
                          Math.round(o.direction_deg / 22.5) % 16
                        ]
                      )}
                    </div>
                  )}
                  <div>core_ratio: {(o.core_ratio||0).toFixed(2)}</div>
                  {o.cape != null && <div>CAPE: {o.cape?.toFixed(0)} J/kg</div>}
                  {o.lightning_count_10km > 0 && <div>⚡ {o.lightning_count_10km} Blitze &lt;10km</div>}
                  {o.gust_warning && <div className="font-bold text-orange-600">💨 Böenwarnung ({o.nowcast_ffx_kmh || o.wind_gust_10m_kmh} km/h)</div>}
                  {o.heavy_rain_warning && <div className="font-bold text-blue-700">🌧 Starkregen ({o.nowcast_rain_rate_1h} mm/h)</div>}
                  {o.lpi > 5 && <div className="text-yellow-600">⚡ LPI: {o.lpi?.toFixed(1)}</div>}
                  {o.tawes_max_gust_kmh > 30 && <div className="text-gray-500 text-xs">Station-Böe: {o.tawes_max_gust_kmh} km/h</div>}
                  <CellTendency obj={o} />
                </Popup>
              </Polygon>
              {(o.intensity_zones||[]).map((zone,zi) => (
                <Polygon key={'z_'+o.id+'_'+zi}
                  positions={zone.coords.map(p=>[p[1],p[0]])}
                  pathOptions={{ color:zone.color, weight:1, fillColor:zone.color,
                    fillOpacity: zone.band==='violett'?0.75:(zone.band==='rot'||zone.band==='rot_wrap')?0.60:0.45 }} />
              ))}
              {o.lat && o.lon && (
                <CircleMarker center={[o.lat,o.lon]} radius={3}
                  pathOptions={{ color:borderColor, fillColor:borderColor, fillOpacity:1, weight:1 }} />
              )}

              {/* Vergangene Zugbahn (F24) — letzte bis zu 6 Positionen */}
              {(o.history || []).length >= 2 && (() => {
                const pts = (o.history || [])
                  .filter(h => h.lat != null && h.lon != null)
                  .slice(-6)
                  .map(h => [h.lat, h.lon])
                if (pts.length < 2) return null
                return (
                  <Polyline key={'hist_'+o.id}
                    positions={pts}
                    pathOptions={{ color:'#999', weight:1.5, dashArray:'3,4', opacity:0.5 }} />
                )
              })()}

              {/* Stationär-Marker (F28): Kreuz-Symbol für stationary_risk >= Schwellwert */}
              {o.stationary_marker && o.lat && o.lon && (
                <CircleMarker center={[o.lat, o.lon]} radius={14}
                  pathOptions={{ color:'#b45309', weight:2, fillColor:'#fef3c7', fillOpacity:0.6, dashArray:'4,3' }}>
                  <Tooltip permanent direction="top" offset={[0,-14]}
                    className="text-xs font-bold text-amber-800 bg-transparent border-0 shadow-none">
                    ⊕
                  </Tooltip>
                </CircleMarker>
              )}

              {/* Hagelwarnung (F43): roter Rahmen wenn hail_prob hoch */}
              {o.hail_warning && o.lat && o.lon && (
                <CircleMarker center={[o.lat, o.lon]} radius={18}
                  pathOptions={{ color:'#dc2626', weight:3, fillOpacity:0, dashArray:'6,3' }}>
                  <Tooltip permanent direction="top" offset={[0,-18]}
                    className="text-xs font-bold text-red-700 bg-transparent border-0 shadow-none">
                    🧊 Hagel {o.hail_prob != null ? (o.hail_prob*100).toFixed(0)+'%' : ''}
                  </Tooltip>
                </CircleMarker>
              )}
            </React.Fragment>
          )
        })}

        {/* B128: Durchgehende Zugbahn statt radialem Pfaecher */}
        {(currentIdx === frames.length - 1 || frames.length === 0) && (() => {
          const _groups = {}
          ;(forecast.features || [])
            .filter(f => f?.properties?.has_arrow !== false)
            .forEach(f => {
              const c = f.geometry?.coordinates
              const p = f.properties || {}
              if (!c || c.length < 2) return
              const a = c[0], b = c[1]
              const key = String(p.cell_id ?? p.id ?? 'x')
              const g = _groups[key] || (_groups[key] = {
                origin: [a[1], a[0]], isKin: true, color: '#888888',
                cell_id: p.cell_id ?? p.id, pts: [],
              })
              const h = Number(p.horizon)
              const q10 = (p.forecast_lat_q10 != null && p.forecast_lon_q10 != null)
                ? [p.forecast_lat_q10, p.forecast_lon_q10] : null
              const q90 = (p.forecast_lat_q90 != null && p.forecast_lon_q90 != null)
                ? [p.forecast_lat_q90, p.forecast_lon_q90] : null
              if (Number.isFinite(h)) g.pts.push({ h, ll: [b[1], b[0]], speed: p.speed_kmh, q10, q90 })
              if (p.forecast_mode !== 'kinematic') { g.isKin = false; g.color = p.color || g.color }
            })
          return Object.values(_groups).map((g, gi) => {
            const sorted = g.pts.slice().sort((x, y) => x.h - y.h)
            if (sorted.length === 0) return null
            const line = [g.origin, ...sorted.map(s => s.ll)]
            const opts = g.isKin
              ? { color: '#888888', weight: 2, dashArray: '6,5', opacity: 0.8 }
              : { color: g.color, weight: 2.5, opacity: 0.9 }
            const last = sorted[sorted.length - 1]
            // B130: Unsicherheitskorridor (q10/q90) als EIN sich verbreiterndes Polygon.
            const _qpts = sorted.filter(s => s.q10 && s.q90)
            const corridor = (!g.isKin && _qpts.length >= 1)
              ? [g.origin, ..._qpts.map(s => s.q10), ..._qpts.slice().reverse().map(s => s.q90)]
              : null
            // B176: Horizont-wachsender Unsicherheitskegel als Fallback, wenn KEIN
            // Quantil-Korridor vorliegt (kinematische Vorhersage ODER ML ohne q10/q90).
            // Halbbreite r(h) = CONE_BASE_KM + CONE_GROWTH_KM_PER_MIN * h; Offsets entlang
            // der festen Achse Ursprung→letzter Stützpunkt → robust, keine Selbst-
            // überschneidung. Macht lange/unsichere Horizonte transparent statt scheingenau.
            const cone = corridor ? null : (() => {
              const CONE_BASE_KM = 3.0
              const CONE_GROWTH_KM_PER_MIN = 0.3
              const center = [g.origin, ...sorted.map(s => s.ll)]
              const hs = [0, ...sorted.map(s => s.h)]
              if (center.length < 2) return null
              const lat0 = g.origin[0]
              const cosLat = Math.max(Math.cos(lat0 * Math.PI / 180), 1e-6)
              const KM_PER_DEG = 111.32
              const toKm = ([la, lo]) => [lo * cosLat * KM_PER_DEG, la * KM_PER_DEG]
              const toLL = (x, y) => [y / KM_PER_DEG, x / (cosLat * KM_PER_DEG)]
              const oKm = toKm(g.origin)
              const lastKm = toKm(center[center.length - 1])
              let ax = lastKm[0] - oKm[0], ay = lastKm[1] - oKm[1]
              const alen = Math.hypot(ax, ay)
              if (alen < 1e-6) { ax = 0; ay = 1 } else { ax /= alen; ay /= alen }
              const px = -ay, py = ax   // Perpendikular-Einheitsvektor (km-Frame)
              const left = [], right = []
              center.forEach((c, i) => {
                const r = CONE_BASE_KM + CONE_GROWTH_KM_PER_MIN * Math.max(hs[i], 0)
                const ck = toKm(c)
                left.push(toLL(ck[0] + px * r, ck[1] + py * r))
                right.push(toLL(ck[0] - px * r, ck[1] - py * r))
              })
              return [...left, ...right.reverse()]
            })()
            return (
              <React.Fragment key={'track_' + gi}>
                {corridor && (
                  <Polygon positions={corridor} pathOptions={{
                    color: opts.color, weight: 0.5, dashArray: '2,4',
                    fillColor: opts.color, fillOpacity: 0.10, interactive: false,
                  }} />
                )}
                {cone && (
                  <Polygon positions={cone} pathOptions={{
                    color: opts.color, weight: 0.5, dashArray: '2,4',
                    fillColor: opts.color, fillOpacity: 0.08, interactive: false,
                  }} />
                )}
                <Polyline positions={line} pathOptions={opts}>
                  <Popup>
                    <div>Zelle: <strong>{g.cell_id}</strong></div>
                    <div>Zugbahn {g.isKin ? '(Schaetzung)' : '(KI)'} bis +{last.h} min</div>
                    {last.speed != null && <div>{last.speed} km/h</div>}
                  </Popup>
                </Polyline>
                {sorted.map((s, si) => (
                  <CircleMarker key={'tp_' + gi + '_' + si} center={s.ll}
                    radius={si === sorted.length - 1 ? 5 : 3}
                    pathOptions={{ color: opts.color, fillColor: opts.color, fillOpacity: 1, weight: 1 }}>
                    <Tooltip direction="top" offset={[0, -4]}>+{s.h} min</Tooltip>
                  </CircleMarker>
                ))}
              </React.Fragment>
            )
          })
        })()}
        {(locations.watchlist||[]).map((loc,i) => (
          <Circle key={'loc_'+i} center={[loc.lat,loc.lon]}
            radius={(loc.radius_km||5)*1000}
            pathOptions={{ color:'#0066cc', weight:1, fillOpacity:0.04 }}>
            <Popup>{loc.name}</Popup>
          </Circle>
        ))}
        {(locations.hits || []).map((loc, i) => {
          const hitEntries = Object.entries(loc.hits || {})
          if (hitEntries.length === 0) return null

          // Bedrohungstyp mit höchster Priorität bestimmen
          const allTypes = hitEntries.map(([, v]) => v.hit_type)
          const hasCurrent      = allTypes.includes('current')
          const hasSlowApproach = allTypes.includes('slow_approach')

          // Darstellung nach Priorität:
          //   current       → rot, groß, solide    (Zelle JETZT im Ort)
          //   slow_approach → orange, mittel        (langsam ziehend, Starkregen)
          //   forecast      → Horizont-Farbe, klein (Pfad trifft Ort)
          const markerColor  = hasCurrent ? '#dc2626'
                             : hasSlowApproach ? '#f97316'
                             : (hitEntries.find(([k]) => Number(k) > 0)?.[1]?.color || '#e33')
          const markerRadius = hasCurrent ? 14 : hasSlowApproach ? 12 : 10
          const markerWeight = hasCurrent ? 4  : hasSlowApproach ? 3  : 2
          const markerFill   = hasCurrent ? 0.80 : hasSlowApproach ? 0.65 : 0.60

          // Forecast-Hits für Popup (Horizon > 0)
          const forecastHits = hitEntries
            .filter(([k]) => Number(k) > 0)
            .sort(([a], [b]) => Number(a) - Number(b))

          const currentHit      = hitEntries.find(([k]) => Number(k) === 0)?.[1]
          const slowApproachHit = hitEntries.find(([, v]) => v.hit_type === 'slow_approach')?.[1]

          return (
            <CircleMarker key={'h' + i} center={[loc.lat, loc.lon]}
              radius={markerRadius}
              pathOptions={{
                color:       markerColor,
                fillColor:   markerColor,
                fillOpacity: markerFill,
                weight:      markerWeight,
              }}>
              <Popup>
                <b>{loc.name}</b>
                {loc.first_contact_min != null && (
                  <div style={{ marginTop: 4, fontWeight: 'bold', color: '#b45309' }}>
                    ⏱ Radius erstmals berührt{' '}
                    {loc.first_contact_min <= 0
                      ? 'jetzt'
                      : `in ~${Math.round(loc.first_contact_min)} min`}
                  </div>
                )}

                {currentHit && (
                  <div style={{ color: '#dc2626', fontWeight: 'bold', marginTop: 4 }}>
                    ⚠ Zelle JETZT im Ort
                    <div style={{ fontWeight: 'normal', fontSize: 11 }}>
                      ID: {currentHit.cell_id} · {currentHit.distance_km} km ·{' '}
                      {currentHit.speed_kmh} km/h
                    </div>
                  </div>
                )}

                {!currentHit && slowApproachHit && (
                  <div style={{ color: '#ea580c', fontWeight: 'bold', marginTop: 4 }}>
                    🌧 Langsam ziehende Zelle ({slowApproachHit.speed_kmh} km/h)
                    <div style={{ fontWeight: 'normal', fontSize: 11 }}>
                      Erhöhtes Starkregenpotential · erweiterter Warnradius aktiv
                    </div>
                  </div>
                )}

                {forecastHits.length > 0 && (() => {
                  // B91: nur frühesten Horizont anzeigen
                  const [hz, entry] = forecastHits[0]
                  return (
                    <div style={{ marginTop: 4, fontSize: 11 }}>
                      <div>
                        +{hz} min · ID {entry.cell_id} ·{' '}
                        {entry.distance_km} km ·{' '}
                        {entry.speed_kmh} km/h
                        {entry.hit_type === 'slow_approach' && ' 🌧'}
                      </div>
                      {forecastHits.length > 1 && (
                        <div style={{ color: '#9ca3af', fontSize: 10, marginTop: 2 }}>
                          + {forecastHits.length - 1} weitere Horizon{forecastHits.length - 1 > 1 ? 'te' : 't'}
                        </div>
                      )}
                    </div>
                  )
                })()}
              </Popup>
            </CircleMarker>
          )
        })}
        {/* Gewitterrisiko-Grid — farbige Flaechen ohne Rand, Hovertext mit Indizes.
            Tooltip wird unterdrueckt wenn unter dem Quadrat bereits eine
            Sturmzelle liegt — sonst Konflikt mit Zellen-Popup. */}
        {showGhosts && (
          <ForecastGhostLayer objects={objects} forecast={forecast} leadMin={ghostLead} />
        )}

        {showRisk && riskGrid.map((cell, i) => {
          // Pruefen ob eine markierte Zelle in diesem Grid-Rechteck liegt
          const hasCellHere = objects.some(o => {
            // Polygon-BBOX prüfen statt nur Zentrum:
            // Alle Grid-Rechtecke INNERHALB des Cell-Polygons werden non-interactive,
            // damit Klick-Events das Cell-Polygon darunter erreichen.
            if (o.contour_geo && o.contour_geo.length >= 3) {
              const cLons = o.contour_geo.map(p => p[0])
              const cLats = o.contour_geo.map(p => p[1])
              const bboxMinLat = Math.min(...cLats) - riskGridStep * 0.502
              const bboxMaxLat = Math.max(...cLats) + riskGridStep * 0.502
              const bboxMinLon = Math.min(...cLons) - riskGridStep * 0.502
              const bboxMaxLon = Math.max(...cLons) + riskGridStep * 0.502
              return cell.lat >= bboxMinLat && cell.lat <= bboxMaxLat &&
                     cell.lon >= bboxMinLon && cell.lon <= bboxMaxLon
            }
            // Fallback: Zentrum ±0.15° (ca. 15 km Buffer)
            return o?.lat != null && o?.lon != null &&
              Math.abs(o.lat - cell.lat) < 0.15 &&
              Math.abs(o.lon - cell.lon) < 0.15
          })
          const info = cell.info || {}
          const riskLabel = cell.risk === 3 ? 'Hoch'
                          : cell.risk === 2 ? 'Maessig'
                          : 'Niedrig'
          const dominantLabel = (() => {
            switch (info.dominant) {
              case 'cell':
                return `🌩 Aktive Zelle in der Nähe${info.cell_dist_km != null ? ` (${info.cell_dist_km} km)` : ''}`
              case 'track':
                return `📍 In berechneter Zugbahn${info.cell_id != null ? ` von Zelle #${info.cell_id}` : ''}`
              case 'lightning':
                return `⚡ Blitzaktivität${info.lightning_count > 0 ? ` — ${info.lightning_count} Blitze < 10 km` : ''}`
              case 'atm':
                return `☁ Atmosphärische Instabilität`
              case 'ir_cell':
                return `Cumulonimbus${info.ir_cell_dist_km != null ? ` — ${info.ir_cell_dist_km} km entfernt` : ''}`
              default:
                return ''
            }
          })()
          // B83 — Severity-Proxy aus verfügbaren atmosphärischen Feldern (kein ML)
          const _sevCap = info.cape ?? 0
          const _sevPW  = info.pw  ?? 0
          const _sevShp = info.ship ?? 0
          const _sevLps = info.lapse_700_500 ?? 0
          const sevRain = _sevCap > 0 && _sevPW > 0
            ? Math.round(Math.min(_sevPW, 50) * Math.min(_sevCap / 1500, 2) * 1.2 * 10) / 10
            : null
          const sevGust = _sevCap > 0
            ? Math.round((10 + Math.min(_sevCap / 100, 40) * (_sevLps > 0 ? _sevLps / 7 : 0)) * 10) / 10
            : null
          const sevHI   = _sevShp > 0 ? Math.round(Math.min(_sevShp, 3) * 100) / 100 : null
          const sevHCat = sevHI != null
            ? (sevHI >= 1.5 ? 'gross' : sevHI >= 0.8 ? 'klein' : 'kein')
            : null
          return (
            <Rectangle
              key={'risk_' + i}
              bounds={[
                [cell.lat - riskGridStep * 0.502, cell.lon - riskGridStep * 0.502],
                [cell.lat + riskGridStep * 0.502, cell.lon + riskGridStep * 0.502],
              ]}
              pathOptions={{
                weight:      0,
                stroke:      false,
                fillColor:   cell.color,
                fillOpacity: cell.risk === 3 ? 0.55
                           : cell.risk === 2 ? 0.40
                           : 0.25,
                interactive: !hasCellHere,
              }}
            >
              {!hasCellHere && (
                <Tooltip direction="top" sticky opacity={0.95}
                  className="risk-tooltip" pane="tooltipPane"
                  permanent={false} interactive={false}>
                  <div style={{ fontSize: 14, lineHeight: 1.6, minWidth: 180 }}>
                    <div style={{ fontWeight: 700, marginBottom: 2 }}>
                      <span style={{
                        display: 'inline-block', width: 10, height: 10,
                        background: cell.color, borderRadius: 2, marginRight: 5,
                      }}/>
                      Risiko: {riskLabel}
                    </div>
                    {dominantLabel && (
                      <div style={{ color: '#555', marginBottom: 2 }}>{dominantLabel}</div>
                    )}
                    {info.in_forecast_track && info.dominant !== 'track' && (
                      <div style={{ color: '#dc2626', fontWeight: 600 }}>
                        ⚠ In berechneter Zugbahn
                      </div>
                    )}
                    {info.cell_id != null && (
                      <div>Zelle: <b>{info.cell_id}</b></div>
                    )}
                    {/* B83 Regen / Böe / Hagel */}
                    {sevRain != null && (
                      <div>🌧 Regen: <b>{sevRain}</b> mm/h</div>
                    )}
                    {sevGust != null && (
                      <div>💨 Böe: ~<b>{sevGust}</b> km/h</div>
                    )}
                    {sevHCat != null && (
                      <div>🧊 Hagel: <b>{sevHCat}</b>
                        {sevHI != null && (
                          <span style={{ color: '#888', marginLeft: 3 }}>(Index {sevHI})</span>
                        )}
                      </div>
                    )}
                    {info.ship != null && (
                      <div>SHIP: <b>{info.ship}</b>
                        <span style={{ color: '#888' }}>{info.ship >= 1.0 ? ' (signifikant)' : ''}</span>
                      </div>
                    )}
                    {info.cape != null && (
                      <div>
                        CAPE: <b>{info.cape}</b> J/kg
                        <span style={{ color: '#888', marginLeft: 3 }}>
                          {info.cape > 3000 ? '(extrem)' : info.cape > 1500 ? '(stark)' : info.cape > 500 ? '(mäßig)' : '(schwach)'}
                        </span>
                      </div>
                    )}
                    {info.li != null && (
                      <div>
                        LI: <b>{info.li}</b> °C
                        <span style={{ color: '#888', marginLeft: 3 }}>
                          {info.li < -3 ? '(sehr instabil)' : info.li < -1 ? '(instabil)' : '(stabil)'}
                        </span>
                      </div>
                    )}
                    {info.lapse_700_500 != null && (
                      <div>
                        Lapse 700–500: <b>{info.lapse_700_500}</b> °C/km
                        <span style={{ color: '#888', marginLeft: 3 }}>
                          {info.lapse_700_500 > 7 ? '(labil)' : info.lapse_700_500 > 6 ? '(mäßig labil)' : ''}
                        </span>
                      </div>
                    )}
                    {info.lightning_count > 0 && (
                      <div style={{ color: '#d97706' }}>
                        ⚡ Blitze in 10 km: <b>{info.lightning_count}</b>
                      </div>
                    )}
                    {info.ir_cell_id != null && info.dominant !== 'ir_cell' && (
                      <div style={{ color: '#9333ea' }}>
                        🛰 IR-Vorläufer: <b>{info.ir_cell_id}</b>
                        {info.ir_bt_min_k != null && <span style={{ color: '#888', marginLeft: 3 }}>({info.ir_bt_min_k} K)</span>}
                        {info.ir_cell_dist_km != null && <span style={{ color: '#888', marginLeft: 3 }}>{info.ir_cell_dist_km} km</span>}
                      </div>
                    )}
                    {info.cin != null && info.cin < -50 && (
                      <div>
                        CIN: <b>{info.cin}</b> J/kg
                        <span style={{ color: '#888', marginLeft: 3 }}>
                          {info.cin < -200 ? '(starke Deckelung)' : '(Deckelung)'}
                        </span>
                      </div>
                    )}
                    {info.pw != null && info.pw > 25 && (
                      <div>
                        PW: <b>{info.pw}</b> mm
                        <span style={{ color: '#888', marginLeft: 3 }}>
                          {info.pw > 40 ? '(sehr hoch)' : '(erhöht)'}
                        </span>
                      </div>
                    )}
                    {info.cloud_height_m != null && (
                      <div>
                        Wolkentop: <b>{info.cloud_height_m?.toLocaleString('de-AT')}</b> m
                      </div>
                    )}
                    {info.score != null && (
                      <div style={{ color: '#aaa', fontSize: 10, marginTop: 3, borderTop: '1px solid #eee', paddingTop: 2 }}>
                        Score: {info.score}
                      </div>
                    )}
                  </div>
                </Tooltip>
              )}
            </Rectangle>
          )
        })}

        {showIrCells && irCells.map((ir, i) => {
          const cbThresholdState = getCbThresholdState(ir)
          return (
          <CircleMarker
            key={'ir_' + i}
            center={[ir.lat, ir.lon]}
            radius={Math.max(6, Math.min(20, (ir.area_px || 30) / 10))}
            pathOptions={{
              color:       ir.overshooting_top ? '#a855f7' : '#6b7280',
              fillColor:   ir.overshooting_top ? '#dc2626' : '#9ca3af',
              fillOpacity: ir.overshooting_top ? 0.40 : 0.25,
              weight: 2,
              dashArray: '5,4',
            }}
          >
            <Tooltip direction="top" sticky opacity={0.95}>
              <div style={{ fontSize: 11, lineHeight: 1.4, minWidth: 150 }}>
                <div style={{ fontWeight: 700, color: '#7c3aed' }}>
                  {formatCbIrLabel(cbThresholdState)} — {ir.ir_id}
                </div>
                <div>Trend: <b>
                  {ir.bt_trend_k_per_min < -0.1
                    ? <span style={{color:'#dc2626'}}>↑ Intensiviert ⚡</span>
                    : ir.bt_trend_k_per_min > 0.1
                      ? <span style={{color:'#6b7280'}}>↓ Löst sich auf</span>
                      : <span>→ Stabil</span>}
                </b></div>
                <div>Alter: {ir.cloud_age_min?.toFixed(0)} min</div>
                {ir.overshooting_top === 1.0 && (
                  <div style={{color:'#dc2626', fontWeight:600}}>⚠ Overshooting Top</div>
                )}
                {ir.cloud_height_m > 0 && (
                  <div style={{ marginTop: 2 }}>
                    Wolkentop: <b>{Math.round(ir.cloud_height_m).toLocaleString('de-AT')} m</b>
                  </div>
                )}
              </div>
            </Tooltip>
          </CircleMarker>
          )
        })}


        {/* Blitz-Layer (F50) — deaktivierbar, nur letzter Frame */}
        {showLightning && (currentIdx === frames.length - 1 || frames.length === 0) &&
          lightning.map((s, i) => {
            const isNeg = (s.pol ?? -1) < 0
            // Negativ (häufig, cloud-to-ground): gelb
            // Positiv (selten, stark): orange-rot
            const color = isNeg ? '#fbbf24' : '#f97316'
            return (
              <CircleMarker key={'bolt_' + i}
                center={[s.lat, s.lon]}
                radius={4}
                pathOptions={{
                  color,
                  fillColor: color,
                  fillOpacity: 0.85,
                  weight: 1,
                }}>
                <Tooltip direction="top" offset={[0, -4]} opacity={0.9}>
                  <div className="text-xs">
                    <div>⚡ {isNeg ? 'Negativ' : 'Positiv'}</div>
                    <div>{s.timestamp}</div>
                    {s.alt > 0 && <div>{s.alt} m</div>}
                  </div>
                </Tooltip>
              </CircleMarker>
            )
          })
        }
        {/* Manuelles Zell-Markieren — Polygon-Zeichner */}
        <PolygonDrawer
          active={cellMarkActive}
          onComplete={handlePolygonComplete}
          onCancel={() => setCellMarkActive(false)}
        />
        <FlyToCell />
        <MapStateProbe targetRef={mapStateRef} />
      </MapContainer>

      {/* Human-in-the-Loop Modal */}
      {hitlConfirmed ? (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          zIndex: 9999,
        }}>
          <div style={{ background: '#fff', borderRadius: 12, padding: 32,
            textAlign: 'center', boxShadow: '0 8px 32px rgba(0,0,0,0.2)' }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>✅</div>
            <p style={{ fontWeight: 700, color: '#065f46', fontSize: 16 }}>
              Filter gespeichert!
            </p>
            <p style={{ color: '#6b7280', fontSize: 13, marginTop: 4 }}>
              Polygon-PNG abgelegt, Filter wirkt im nächsten Live-Loop (≤ 120 s).
            </p>
            <p style={{ color: '#9ca3af', fontSize: 11, marginTop: 8 }}>
              Verwaltung &amp; KI-Analyse: <em>Filter-Galerie</em>
            </p>
          </div>
        </div>
      ) : (
        <HitlModal
          loading={hitlLoading}
          result={hitlResult}
          onConfirm={handleHitlConfirm}
          onClose={handleHitlClose}
        />
      )}
    </div>
  )
}
