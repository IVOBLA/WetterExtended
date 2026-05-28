import React, { useEffect, useState, useRef, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  MapContainer, TileLayer, CircleMarker, Polyline,
  Polygon, Circle, Popup, ImageOverlay, Tooltip,
  useMapEvents, Rectangle, useMap,
} from 'react-leaflet'
import api from '../api.js'
import {
  MAP_CENTER_KAERNTEN,
  MAP_ZOOM_DEFAULT,
  MAP_ZOOM_MIN,
  MAP_ZOOM_MAX,
  MAP_TILE_URL,
  MAP_TILE_ATTRIBUTION,
} from '../constants/mapDefaults.js'

const lineageColor = {
  new: 'green', continued: 'blue', merged: 'orange', split: 'magenta',
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
        <span style={{fontSize:10}}>CB > 10.000</span>
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
  const [locations,    setLocations]    = useState({ watchlist: [], hits: [], colors: {} })
  const [horizons,     setHorizons]     = useState({ horizons: [10,20,30,40,60], colors: {}, styles: {} })
  const [radarTiming,  setRadarTiming]  = useState(null)
  const [radarBounds,  setRadarBounds]  = useState(null)
  const [radarOpacity, setRadarOpacity] = useState(0.65)
  const [showRadar,    setShowRadar]    = useState(true)
  const [radarTs,        setRadarTs]        = useState(0)
  const [lightning,      setLightning]      = useState([])
  const [showLightning,  setShowLightning]  = useState(true)
  const [showRisk,      setShowRisk]      = useState(true)
  const [showIrCells,   setShowIrCells]   = useState(false)
  const [riskGrid,      setRiskGrid]      = useState([])
  const [riskGridError, setRiskGridError] = useState(false)
  const [irCells,       setIrCells]       = useState([])
  const [lightningAge,   setLightningAge]   = useState(30)  // Minuten

  // Animation
  const [frames,     setFrames]     = useState([])
  const [currentIdx, setCurrentIdx] = useState(-1)
  const [playing,    setPlaying]    = useState(false)
  const [speed,      setSpeed]      = useState(500)
  const timerRef        = useRef(null)
  const frameLoadTimer  = useRef(null)
  const frameDataCache  = useRef({})

  // ── Manuelles Zell-Markieren ──────────────────────────────────────────────
  const [cellMarkActive,   setCellMarkActive]   = useState(false)
  const [hitlLoading,      setHitlLoading]      = useState(false)
  const [hitlResult,       setHitlResult]       = useState(null)   // API-Antwort
  const [hitlConfirmed,    setHitlConfirmed]    = useState(false)

  const currentFrame = frames[currentIdx] ?? null
  const radarUrl = currentFrame
    ? `/api/radar_image?ts=${currentFrame.ts}`
    : `/api/radar_image?t=${radarTs}`

  // Frames vorausladen
  useEffect(() => {
    frames.forEach(f => {
      const img = new window.Image()
      img.src = `/api/radar_image?ts=${f.ts}`
    })
  }, [frames])

  // Auto-Play
  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current)
    if (!playing || frames.length === 0) return
    timerRef.current = setInterval(() => {
      setCurrentIdx(i => (i + 1) % frames.length)
    }, speed)
    return () => clearInterval(timerRef.current)
  }, [playing, speed, frames.length])

  const handlePlay  = useCallback(() => setPlaying(true),  [])
  const handlePause = useCallback(() => setPlaying(false), [])

  async function load() {
    frameDataCache.current = {}
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
      if (timing) setRadarTiming(timing)
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
        setCurrentIdx(latestIdx)
      }
      const [objs, fc] = await Promise.all([
        api.get(latestTs ? `/api/objects?ts=${latestTs}` : '/api/objects'),
        api.get(latestTs ? `/api/forecast?ts=${latestTs}` : '/api/forecast'),
      ])
      setObjects(objs)
      setForecast(fc)
      setRadarTs(Date.now())
    } catch (e) { console.error(e) }
  }

  useEffect(() => {
    load()
    const t = setInterval(load, 60000)
    return () => clearInterval(t)
  }, [showIrCells])

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
          const irOnly = (Array.isArray(d) ? d : (d.objects || []))
            .filter(o => o._type === 'ir_cell')
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
            {[10, 20, 30, 60].map(m => (
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
            title="CB > 10.000 m: Cumulonimbus-Wolkentops über 10.000 m MSL (BT < 230 K, MSG IR108). Rot = Overshooting Top (BT < 215 K, > 12.300 m)."
          />
          <span>🛰 CB &gt; 10.000</span>
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
          const borderColor = lineageColor[o.lineage] || '#888'
          return (
            <React.Fragment key={'cell_' + o.id}>
              <Polygon
                positions={outerPos}
                pathOptions={{ color:borderColor, weight:2, fillColor:'#ff8800', fillOpacity:0.25, interactive:true }}
                eventHandlers={{ click: (e) => { e.target.openPopup(e.latlng) } }}
                pane="tooltipPane"
              >
                <Popup autoPan={true} keepInView={true}>
                  <div><strong>{o.id}</strong> ({o.lineage})</div>
                  {o.first_seen && (
                    <div style={{fontSize:'0.8em',color:'#666'}}>
                      Erstmals: {(() => { try {
                        const d = new Date(o.first_seen.replace(/_/g,'-').replace(/(\d{4}-\d{2}-\d{2})-(\d{2})-(\d{2})-(\d{2})/, '$1T$2:$3:$4'))
                        return d.toLocaleTimeString('de-AT', {hour:'2-digit',minute:'2-digit'})
                      } catch { return o.first_seen } })()}
                    </div>
                  )}
                  {o.active_frames != null && (
                    <div style={{fontSize:'0.8em',color:'#666'}}>
                      Aktiv: {o.active_frames} Frames (~{Math.round(o.active_frames * 2)} min)
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

        {/* Vorhersage-Pfeile nur beim neuesten Frame */}
        {(currentIdx === frames.length - 1 || frames.length === 0) &&
          (forecast.features||[])
            .filter(f => f.properties?.has_arrow !== false)
            .map((f,i) => {
              const [a,b] = f.geometry.coordinates
              const p = f.properties || {}
              const isKin = p.forecast_mode === 'kinematic'
              // is_slow_arrow: Zelle bewegt sich langsam → transparenter Pfeil statt ausblenden
              const slowOpacity = p.is_slow_arrow ? 0.35 : undefined
              const pathOpts = isKin
                ? { color:'#888888', weight:1.5, dashArray:'6,5', opacity: slowOpacity ?? 0.7 }
                : { color:p.color||'#888', weight:p.weight||2, dashArray: p.is_slow_arrow ? '2,6' : (p.dash||''), opacity: slowOpacity ?? 1.0 }
              const q10Lat = p.forecast_lat_q10
              const q10Lon = p.forecast_lon_q10
              const q90Lat = p.forecast_lat_q90
              const q90Lon = p.forecast_lon_q90
              const hasQ = q10Lat != null && q10Lon != null && q90Lat != null && q90Lon != null

              return (
                <React.Fragment key={'arrow_grp_'+i}>
                  {/* Hauptpfeil */}
                  <Polyline positions={[[a[1],a[0]],[b[1],b[0]]]} pathOptions={pathOpts}>
                    <Popup>
                      <div>Zelle: <strong>{p.cell_id}</strong></div>
                      <div>+{p.horizon} min {isKin ? '(Schätzung)' : '(KI)'}</div>
                      {p.speed_kmh != null && <div>{p.speed_kmh} km/h</div>}
                      {p.hail_warning && <div className="text-red-600 font-bold">🧊 Hagelwarnung</div>}
                    </Popup>
                  </Polyline>

                  {/* q10/q90 alternative Pfeile (F25) */}
                  {hasQ && !isKin && (
                    <>
                      <Polyline
                        positions={[[a[1],a[0]],[q10Lat,q10Lon]]}
                        pathOptions={{ color: pathOpts.color, weight:1, dashArray:'3,5', opacity:0.45 }} />
                      <Polyline
                        positions={[[a[1],a[0]],[q90Lat,q90Lon]]}
                        pathOptions={{ color: pathOpts.color, weight:1, dashArray:'3,5', opacity:0.45 }} />
                    </>
                  )}

                  {/* Unsicherheitskorridor als Dreieck q10→zentrum→q90 (F23) */}
                  {hasQ && !isKin && (
                    <Polygon
                      positions={[[b[1],b[0]],[q10Lat,q10Lon],[q90Lat,q90Lon]]}
                      pathOptions={{
                        color: pathOpts.color, weight:0.5, fillColor: pathOpts.color,
                        fillOpacity: 0.10, dashArray:'2,4'
                      }} />
                  )}
                </React.Fragment>
              )
            })
        }

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

                {forecastHits.length > 0 && (
                  <div style={{ marginTop: 4, fontSize: 11 }}>
                    {forecastHits.map(([hz, entry]) => (
                      <div key={hz}>
                        +{hz} min · ID {entry.cell_id} ·{' '}
                        {entry.distance_km} km ·{' '}
                        {entry.speed_kmh} km/h
                        {entry.hit_type === 'slow_approach' && ' 🌧'}
                      </div>
                    ))}
                  </div>
                )}
              </Popup>
            </CircleMarker>
          )
        })}
        {/* Gewitterrisiko-Grid — farbige Flaechen ohne Rand, Hovertext mit Indizes.
            Tooltip wird unterdrueckt wenn unter dem Quadrat bereits eine
            Sturmzelle liegt — sonst Konflikt mit Zellen-Popup. */}
        {showRisk && riskGrid.map((cell, i) => {
          // Pruefen ob eine markierte Zelle in diesem Grid-Rechteck liegt
          const hasCellHere = objects.some(o => {
            // Polygon-BBOX prüfen statt nur Zentrum:
            // Alle Grid-Rechtecke INNERHALB des Cell-Polygons werden non-interactive,
            // damit Klick-Events das Cell-Polygon darunter erreichen.
            if (o.contour_geo && o.contour_geo.length >= 3) {
              const cLons = o.contour_geo.map(p => p[0])
              const cLats = o.contour_geo.map(p => p[1])
              const bboxMinLat = Math.min(...cLats) - 0.025
              const bboxMaxLat = Math.max(...cLats) + 0.025
              const bboxMinLon = Math.min(...cLons) - 0.025
              const bboxMaxLon = Math.max(...cLons) + 0.025
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
                return `☁ Atmosphärische Instabilität${info.li != null ? ` · LI ${info.li} °C` : ''}`
              case 'ir_cell':
                return `🛰 IR-Vorläufer (Cumulonimbus)${info.ir_bt_min_k != null ? ` · ${info.ir_bt_min_k} K` : ''}${info.ir_cell_dist_km != null ? ` · ${info.ir_cell_dist_km} km` : ''}`
              default:
                return ''
            }
          })()
          return (
            <Rectangle
              key={'risk_' + i}
              bounds={[
                [cell.lat - 0.025, cell.lon - 0.025],
                [cell.lat + 0.025, cell.lon + 0.025],
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
                <Tooltip direction="top" sticky opacity={0.95} className="risk-tooltip">
                  <div style={{ fontSize: 11, lineHeight: 1.35, minWidth: 140 }}>
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

        {showIrCells && irCells.map((ir, i) => (
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
                  🛰 CB &gt; 10.000 — {ir.ir_id}
                </div>
                <div>Trend: <b>
                  {ir.bt_trend_k_per_min < -1.5
                    ? <span style={{color:'#dc2626'}}>↑ Intensiviert ⚡</span>
                    : ir.bt_trend_k_per_min > 0.5
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
        ))}


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
