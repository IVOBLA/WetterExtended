// frontend/src/pages/MapFullscreen.jsx
import React, { useEffect, useState, useRef, useCallback } from 'react'
import {
  MapContainer, TileLayer, CircleMarker,
  Polyline, Polygon, Circle, Popup, ImageOverlay, Tooltip, Rectangle,
} from 'react-leaflet'
import {
  MAP_CENTER_KAERNTEN,
  MAP_ZOOM_FULLSCREEN,
  MAP_ZOOM_MIN,
  MAP_ZOOM_MAX,
  MAP_TILE_URL,
  MAP_TILE_ATTRIBUTION,
} from '../constants/mapDefaults.js'
import api, { abortApiRequests } from '../api.js'
import { formatCbIrLabel, getCbThresholdState } from '../utils/cbThreshold.js'

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
    staerker:   { sym: '↑', txt: 'verstärkt sich',      color: '#dc2626' },
    schwaecher: { sym: '↓', txt: 'schwächt ab',         color: '#2563eb' },
    stabil:     { sym: '→', txt: 'stabil',              color: '#6b7280' },
    kompakt:    { sym: '◉', txt: 'konzentriert sich',   color: '#f97316' },
    konzentriert: { sym: '◉', txt: 'konzentriert sich', color: '#f97316' },
    unsicher:   { sym: '?', txt: 'Trend unsicher',      color: '#9ca3af' },
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
        <span style={{ color: i.color, fontWeight: 700 }}>{i.sym} Kern:</span>{' '}
        {i.txt}
      </div>
      <div>
        <span style={{ color: s.color, fontWeight: 700 }}>{s.sym} Fläche:</span>{' '}
        {s.txt}
      </div>
      <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 2 }}>
        {isMl ? 'ML-Prognose' : 'aus Verlauf (kinematisch)'}
      </div>
    </div>
  )
}

const lineageColor = {
  new: 'green', continued: 'blue', merged: 'orange', split: 'magenta'
}

const CELL_POLYGON_COLOR = '#0b1f5e'
const CELL_POLYGON_FILL_OPACITY = 0.25

// B118: Merged-Zellen deutlich hervorheben (identisch zu MapView.cellStroke).
// Alle aktuellen Zellpolygone nutzen dieselbe dunkelblaue Farbe; lineage bleibt
// nur über Strichstärke/-muster sichtbar.
// merged → dicker (4) + auffällig gestrichelt; split → 3 + fein gestrichelt;
// new/continued → unverändert durchgezogen (2).
function cellStroke(lineage, trackingState) {
  if (trackingState === 'inactive_rain') return { color: CELL_POLYGON_COLOR, weight: 2, dashArray: '7,6', opacity: 0.55, fillOpacity: 0.10 }
  if (lineage === 'merged') return { color: CELL_POLYGON_COLOR, weight: 4, dashArray: '10,6', opacity: 1, fillOpacity: CELL_POLYGON_FILL_OPACITY }
  if (lineage === 'split')  return { color: CELL_POLYGON_COLOR, weight: 3, dashArray: '4,4', opacity: 1, fillOpacity: CELL_POLYGON_FILL_OPACITY }
  return { color: CELL_POLYGON_COLOR, weight: 2, dashArray: undefined, opacity: 1, fillOpacity: CELL_POLYGON_FILL_OPACITY }
}

function TBtn({ onClick, active, children, style = {} }) {
  return (
    <button onClick={onClick} style={{
      minWidth: 44, minHeight: 44, padding: '0 12px',
      border: '1px solid #d1d5db', borderRadius: 8,
      cursor: 'pointer', fontSize: 16, fontWeight: active ? 700 : 400,
      background: active ? '#2563eb' : '#f9fafb',
      color: active ? '#fff' : '#222',
      userSelect: 'none', WebkitTapHighlightColor: 'transparent',
      touchAction: 'manipulation',
      flexShrink: 0,
      ...style,
    }}>
      {children}
    </button>
  )
}

function BottomBar({ frames, currentIdx, playing, speed, onSetIdx, onPlay, onPause, onSpeed }) {
  if (!frames.length) return null
  const cur = frames[currentIdx]
  return (
    <div style={{
      position: 'absolute', bottom: 0, left: 0, right: 0, zIndex: 1000,
      background: 'rgba(255,255,255,0.97)',
      borderTop: '1px solid #e5e7eb',
      padding: '4px 8px',
      paddingBottom: 'calc(4px + env(safe-area-inset-bottom, 0px))',
      paddingLeft: 'max(8px, env(safe-area-inset-left, 0px))',
      paddingRight: 'max(8px, env(safe-area-inset-right, 0px))',
      display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'nowrap',
      overflow: 'hidden',
    }}>
      {/* Zurück */}
      <TBtn onClick={() => { onPause(); onSetIdx(i => Math.max(0, i - 1)) }}>◀</TBtn>
      {/* Play/Pause */}
      <TBtn onClick={playing ? onPause : onPlay} active={playing}>
        {playing ? '⏸' : '▶'}
      </TBtn>
      {/* Vor */}
      <TBtn onClick={() => { onPause(); onSetIdx(i => Math.min(frames.length - 1, i + 1)) }}>▶▶</TBtn>
      {/* Slider */}
      <input
        type="range" min="0" max={frames.length - 1} value={currentIdx < 0 ? 0 : currentIdx}
        onChange={e => { onPause(); onSetIdx(Number(e.target.value)) }}
        style={{ flex: 1, minWidth: 40, accentColor: '#2563eb', height: 28,
                 cursor: 'pointer' }}
      />
      {/* Zeitstempel */}
      <span style={{
        fontFamily: 'monospace', fontSize: 13, fontWeight: 700,
        whiteSpace: 'nowrap', flexShrink: 0,
      }}>
        {cur?.label ?? '—'}
      </span>
      {cur?.gap_min != null && cur.gap_min > 7 && (
        <span title={`Zeitsprung: ${cur.gap_min} min seit letztem Frame`}
          style={{ fontSize: 10, color: '#f59e0b', fontWeight: 700 }}>
          ⏱+{Math.round(cur.gap_min)}m
        </span>
      )}
    </div>
  )
}


function isPublicCell(o) {
  const missing = Number(o?.missing || 0)
  return !!o && o.tracking_state !== 'inactive_rain' && o.silent_tracking !== true && (missing === 0 || o.tracking_state === 'reactivated')
}

function isValidForecastFeature(f) {
  const p = f?.properties || {}
  const c = f?.geometry?.coordinates
  const speed = Number(p.forecast_speed_kmh ?? p.speed_kmh ?? 0)
  return p.has_arrow !== false && p.forecast_rejected !== true && Number.isFinite(speed) && speed <= 150 && Array.isArray(c) && c.length >= 2 && c.slice(0, 2).every(pt => Array.isArray(pt) && pt.length >= 2 && Number.isFinite(Number(pt[0])) && Number.isFinite(Number(pt[1])))
}

function forecastModeLabel(p) {
  if (p?.forecast_mode === 'ml') return 'ML'
  if (p?.forecast_mode === 'kinematic_fallback') return `Fallback wegen Plausibilitätsprüfung${p?.forecast_reject_reason ? ': ' + p.forecast_reject_reason : ''}`
  return 'Kinematisch'
}

function hydroFeatureCollection(response) {
  const fc = response?.data || response
  return (fc && Array.isArray(fc.features)) ? fc : { type: 'FeatureCollection', features: [] }
}

function hydroColor(status) {
  if (status === 'confirmed') return '#16a34a'
  if (status === 'ambiguous') return '#a855f7'
  if (status === 'pending') return '#f97316'
  if (status === 'rejected') return '#6b7280'
  return '#0ea5e9'
}

function StatusChip({ radarTiming, fmtTime, onExpand, loading }) {
  const active = radarTiming?.cells_active
  return (
    <button onClick={onExpand} style={{
      display: 'flex', alignItems: 'center', gap: 6,
      background: active ? 'rgba(220,38,38,0.92)' : 'rgba(255,255,255,0.92)',
      color: active ? '#fff' : '#222',
      border: active ? '2px solid #b91c1c' : '1px solid #d1d5db',
      borderRadius: 20, padding: '6px 12px',
      fontSize: 13, fontWeight: 600,
      boxShadow: '0 2px 6px rgba(0,0,0,0.18)',
      cursor: 'pointer', WebkitTapHighlightColor: 'transparent',
      whiteSpace: 'nowrap',
    }}>
      {loading ? '⟳' : (active ? '⚡' : '🛰')}
      <span>{radarTiming ? fmtTime(radarTiming.last_radar_image_utc) : '—'}</span>
      <span style={{ fontSize: 10, opacity: 0.7 }}>▼</span>
    </button>
  )
}

export default function MapFullscreen() {
  const [objects,      setObjects]      = useState([])
  const [forecast,     setForecast]     = useState({ features: [] })
  const [locations,    setLocations]    = useState({ watchlist: [], hits: [], colors: {} })
  const [horizons,     setHorizons]     = useState({ horizons: [10,20,30,40,60], colors: {}, styles: {} })
  const [lastTs,       setLastTs]       = useState(null)
  const [radarBounds,  setRadarBounds]  = useState(null)
  const [radarOpacity, setRadarOpacity] = useState(0.65)
  const [showRadar,    setShowRadar]    = useState(true)
  const [radarTiming,  setRadarTiming]  = useState(null)
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
  const [hydroStations, setHydroStations] = useState({ type:'FeatureCollection', features: [] })
  const [hydroCatchments, setHydroCatchments] = useState({})
  const [frames,       setFrames]       = useState([])
  const [currentIdx,   setCurrentIdx]   = useState(-1)
  const [playing,      setPlaying]      = useState(false)
  const [speed,        setSpeed]        = useState(500)
  const [panelOpen,    setPanelOpen]    = useState(false)
  const [loading,      setLoading]      = useState(false)

  const timerRef       = useRef(null)
  const pollRef        = useRef(null)
  const isLoadingRef   = useRef(false)
  const lastImgRef     = useRef(null)
  const frameLoadTimer = useRef(null)
  const frameDataCache = useRef({})
  const playingRef     = useRef(false)

  const currentFrame = frames[currentIdx] ?? null
  const radarUrl = currentFrame
    ? `/api/radar_image?ts=${currentFrame.ts}`
    : `/api/radar_image?t=${radarTs}`

  useEffect(() => {
    if (!frames.length) return
    const center = currentIdx >= 0 ? currentIdx : (frames.length - 1)
    const subset = frames.slice(Math.max(0, center - 3), Math.min(frames.length, center + 4))
    const imgs = subset.map(f => { const img = new window.Image(); img.src = `/api/radar_image?ts=${f.ts}`; return img })
    return () => { imgs.forEach(img => { img.src = '' }) }
  }, [frames, currentIdx])

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

  const schedulePoll = useCallback((timing) => {
    if (pollRef.current) clearTimeout(pollRef.current)
    let delayMs = 60000
    if (timing?.next_fetch_estimated_utc) {
      const nextFetch = new Date(timing.next_fetch_estimated_utc).getTime()
      const now       = Date.now()
      const msUntil   = nextFetch - now
      if (msUntil <= 0) {
        delayMs = 22000
      } else {
        delayMs = Math.min(msUntil + 5000, 90000)
      }
    }
    pollRef.current = setTimeout(() => load(), delayMs)
  }, [])

  const loadRef = useRef(null)

  async function load() {
    if (isLoadingRef.current) return
    isLoadingRef.current = true
    setLoading(true)
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
      api.get('/api/hydro/stations').then(d => setHydroStations(hydroFeatureCollection(d))).catch(() => setHydroStations({ type:'FeatureCollection', features: [] }))

      // Schritt 2: Frame-Timestamp bestimmen, objects/forecast synchron laden
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
      setLastTs(new Date().toLocaleTimeString('de-AT'))
    } catch (e) {
      if (e?.name !== 'AbortError') console.error(e)
      schedulePoll(null)
    } finally {
      setLoading(false)
      isLoadingRef.current = false
    }
  }

  loadRef.current = load

  useEffect(() => {
    load()
    return () => {
      if (pollRef.current)  clearTimeout(pollRef.current)
      if (timerRef.current) clearInterval(timerRef.current)
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

  const fmtTime = utcStr => utcStr
    ? new Date(utcStr).toLocaleTimeString('de-AT', { hour: '2-digit', minute: '2-digit' })
    : '—'

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 0 }}>

      <div style={{
        position: 'absolute', top: 10, right: 10, zIndex: 1000,
        maxWidth: 'calc(100vw - 20px)',
      }}>
        {!panelOpen ? (
          <StatusChip
            radarTiming={radarTiming}
            fmtTime={fmtTime}
            onExpand={() => setPanelOpen(true)}
            loading={loading}
          />
        ) : (
          <div style={{
            background: 'rgba(255,255,255,0.96)',
            borderRadius: 10, padding: '10px 14px', fontSize: 13,
            boxShadow: '0 3px 12px rgba(0,0,0,0.22)',
            display: 'flex', flexDirection: 'column', gap: 8,
            minWidth: 220, maxWidth: 320,
            overflowY: 'auto',
            maxHeight: 'calc(100dvh - 180px)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <strong style={{ fontSize: 12, color: '#555' }}>WetterExtended</strong>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <button
                  onClick={() => { if (pollRef.current) clearTimeout(pollRef.current); load() }}
                  disabled={loading}
                  style={{
                    background: 'none', border: '1px solid #d1d5db', borderRadius: 6,
                    fontSize: 14, cursor: loading ? 'default' : 'pointer',
                    color: loading ? '#aaa' : '#2563eb', padding: '2px 6px',
                    WebkitTapHighlightColor: 'transparent',
                  }}
                  title="Jetzt aktualisieren"
                >
                  {loading ? '⟳' : '↺'}
                </button>
                <button
                  onClick={() => setPanelOpen(false)}
                  style={{
                    background: 'none', border: 'none', fontSize: 18,
                    cursor: 'pointer', color: '#666', lineHeight: 1,
                    padding: '2px 4px', WebkitTapHighlightColor: 'transparent',
                  }}
                >✕</button>
              </div>
            </div>

            {radarTiming && (
              <>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <div>🛰 Letztes Radar: <strong>{fmtTime(radarTiming.last_radar_image_utc)}</strong></div>
                  <div>⏱ Nächste Prüfung:{' '}
                    <strong>
                      {radarTiming.next_fetch_estimated_utc
                        ? fmtTime(radarTiming.next_fetch_estimated_utc)
                        : `~${Math.round((radarTiming.loop_interval_s || 120) / 60)} min`}
                    </strong>
                  </div>
                  <div style={{
                    color: radarTiming.cells_active ? '#dc2626' : '#6b7280',
                    fontWeight: radarTiming.cells_active ? 700 : 400,
                  }}>
                    {radarTiming.cells_active ? '⚡ Zellen aktiv' : '✓ Keine aktiven Schwergewitter-Zellen'}
                  </div>
                </div>
                <div style={{ borderTop: '1px solid #e5e7eb' }} />
              </>
            )}

            <label style={{ display: 'flex', alignItems: 'center', gap: 12,
                            cursor: 'pointer', minHeight: 44 }}>
              <input
                type="checkbox" checked={showRadar}
                onChange={e => setShowRadar(e.target.checked)}
                style={{ width: 22, height: 22, flexShrink: 0 }}
              />
              <span style={{ fontWeight: 500, fontSize: 15 }}>Radar-Overlay</span>
            </label>

            {showRadar && (
              <label style={{ display: 'flex', alignItems: 'center', gap: 10, minHeight: 44 }}>
                <span style={{ color: '#555', minWidth: 70, fontSize: 14 }}>Deckkraft:</span>
                <input
                  type="range" min="0" max="100"
                  value={Math.round(radarOpacity * 100)}
                  onChange={e => setRadarOpacity(Number(e.target.value) / 100)}
                  style={{ flex: 1, height: 26, accentColor: '#2563eb', cursor: 'pointer' }}
                />
                <span style={{ fontFamily: 'monospace', minWidth: 36, textAlign: 'right', fontSize: 14 }}>
                  {Math.round(radarOpacity * 100)}%
                </span>
              </label>
            )}
            <label style={{ display:'flex', alignItems:'center', gap:10,
                            cursor:'pointer', minHeight: 44 }}>
              <input type="checkbox" checked={showLightning}
                onChange={e => setShowLightning(e.target.checked)}
                style={{ accentColor: '#fbbf24', width: 22, height: 22, flexShrink: 0 }} />
              <span style={{ fontSize: 15 }}>⚡ Blitze</span>
              <select value={lightningAge}
                onChange={e => setLightningAge(Number(e.target.value))}
                style={{ fontSize: 16, padding: '6px 10px',
                         border: '1px solid #555',
                         background: '#1a1a2e', color: '#fff',
                         borderRadius: 6, minWidth: 80, height: 38,
                         touchAction: 'manipulation' }}>
                {[5, 10, 15, 30].map(m => (
                  <option key={m} value={m}>{m} min</option>
                ))}
              </select>
            </label>
            <label style={{ display:'flex', alignItems:'center', gap:10,
                            cursor:'pointer', minHeight: 44 }}>
              <input type="checkbox" checked={showRisk}
                onChange={e => setShowRisk(e.target.checked)}
                style={{ accentColor: '#ef4444', width: 22, height: 22, flexShrink: 0 }} />
              <span style={{ fontSize: 15 }}>🌩 Risikozonen</span>
            </label>
            <label style={{ display:'flex', alignItems:'center', gap:10,
                            cursor:'pointer', minHeight: 44, userSelect: 'none' }}>
              <input
                type="checkbox"
                checked={showIrCells}
                onChange={e => setShowIrCells(e.target.checked)}
                className="accent-purple-600"
                style={{ width: 22, height: 22, flexShrink: 0 }}
                title="CB > 10.000 m: Cumulonimbus-Wolkentops über 10.000 m MSL (BT < 230 K, MSG IR108). Rot = Overshooting Top (BT < 215 K, > 12.300 m)."
              />
              <span style={{ fontSize: 15 }}>🛰 CB &gt; 10.000</span>
            </label>

            {lastTs && (
              <div style={{ color: '#aaa', fontSize: 13 }}>Stand: {lastTs}</div>
            )}
          </div>
        )}
      </div>

      {riskGridError && showRisk && (
        <div style={{
          position: 'absolute', bottom: 60, left: '50%',
          transform: 'translateX(-50%)',
          zIndex: 1100,
          background: 'rgba(220,38,38,0.92)',
          color: '#fff',
          padding: '6px 14px',
          borderRadius: 8,
          fontSize: 13,
          fontWeight: 600,
          pointerEvents: 'none',
        }}>
          ⚠ Risikozonen konnten nicht geladen werden
        </div>
      )}

      <MapContainer
        center={MAP_CENTER_KAERNTEN}
        zoom={MAP_ZOOM_FULLSCREEN}
        minZoom={MAP_ZOOM_MIN}
        maxZoom={MAP_ZOOM_MAX}
        style={{ width: '100%', height: '100%' }}
        tap={false}              // verhindert Leaflet-eigenen Tap-Handler (Konflikt mit Touch-Events)
        tapTolerance={15}        // größere Tap-Toleranz auf touch-Geräten
        touchZoom={true}         // Pinch-to-Zoom explizit aktivieren
        doubleClickZoom={false}  // verhindert versehentliches Zoom bei Doppeltippen
      >
        <TileLayer
          url={MAP_TILE_URL}
          attribution={MAP_TILE_ATTRIBUTION}
        />

        {showRadar && radarBounds && (
          <ImageOverlay
            key={radarUrl}
            url={radarUrl}
            bounds={radarBounds}
            opacity={radarOpacity}
            zIndex={200}
          />
        )}


        {(hydroStations.features || []).map(f => {
          const p = f.properties || {}
          const coords = f.geometry?.coordinates || []
          if (coords.length < 2) return null
          const impact = p.last_hydro_impact || {}
          const color = hydroColor(p.status)
          return (
            <React.Fragment key={'hydro_' + p.station_id}>
              <CircleMarker center={[coords[1], coords[0]]} radius={p.impact_active ? 8 : 5}
                pathOptions={{ color, fillColor: color, fillOpacity: p.impact_active ? 0.9 : 0.65, weight: p.impact_active ? 3 : 1 }}
                eventHandlers={{ click: () => api.get(`/api/hydro/station/${p.station_id}/catchment`).then(d => setHydroCatchments(prev => ({ ...prev, [p.station_id]: hydroFeatureCollection(d) }))).catch(() => {}) }}>
                <Popup>
                  <div><strong>{p.name || p.station_id}</strong></div>
                  <div>Gewässer: {p.river || '—'}</div>
                  <div>Q: {p.q_m3s ?? '—'} m³/s</div>
                  <div>W: {p.w_cm ?? '—'} cm</div>
                  <div>Messzeit: {p.measured_at || '—'}</div>
                  <div>letzter Hydro-Impact: {impact.cell_id ? `${impact.cell_id} (${impact.status})` : '—'}</div>
                  <div>Status: {p.status || '—'}</div>
                </Popup>
              </CircleMarker>
              {impact.relation === 'upstream_catchment_hit' && impact.cell_lat != null && impact.cell_lon != null && impact.station_lat != null && impact.station_lon != null && (
                <Polyline positions={[[coords[1], coords[0]], [impact.cell_lat, impact.cell_lon]]} pathOptions={{ color, weight: 1, dashArray: '4,4' }} />
              )}
              {((hydroCatchments[p.station_id]?.features) || []).map((cf, i) => {
                const ring = cf.geometry?.coordinates?.[0]
                if (!ring || ring.length < 3) return null
                return <Polygon key={`hydro_catch_${p.station_id}_${i}`} positions={ring.map(c => [c[1], c[0]])} pathOptions={{ color, weight: 1, fillOpacity: 0.03 }} />
              })}
            </React.Fragment>
          )
        })}

        {objects.filter(isPublicCell).map(o => {
          if (!isPublicCell(o) || !o.contour_geo || o.contour_geo.length < 3) return null
          const outerPos    = o.contour_geo.map(p => [p[1], p[0]])
          const stroke      = cellStroke(o.lineage, o.tracking_state)
          const borderColor = lineageColor[o.lineage] || '#888'
          return (
            <React.Fragment key={'cell_' + o.id}>
              <Polygon
                positions={outerPos}
                pathOptions={{ color: stroke.color, weight: stroke.weight, dashArray: stroke.dashArray, fillColor: CELL_POLYGON_COLOR, fillOpacity: stroke.fillOpacity, opacity: stroke.opacity, interactive:true }}
                eventHandlers={{ click: (e) => { e.target.openPopup(e.latlng) } }}
                pane="tooltipPane"
              >
                <Popup autoPan={true} keepInView={true}>
                  <div><b>{o.id}</b> ({o.lineage})</div>
                  {o.tracking_state === 'inactive_rain' && (
                    <div style={{fontSize:'0.85em',color:'#0b1f5e',marginTop:3}}>
                      Status: stille Regen-Weiterführung<br />
                      ARSO-Regen vorhanden<br />
                      ID bleibt für Reaktivierung erhalten<br />
                      Inaktiv seit: {o.inactive_age_min ?? 0} Minuten
                    </div>
                  )}
                  {o.tracking_state === 'reactivated' && (
                    <div style={{fontSize:'0.85em',color:'#0b1f5e',marginTop:3}}>
                      Status: reaktiviert<br />
                      vorherige Zell-ID beibehalten
                    </div>
                  )}
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
                  <div>core_ratio: {(o.core_ratio || 0).toFixed(2)}</div>
                  {o.cape != null && <div>CAPE: {o.cape?.toFixed(0)} J/kg</div>}
                  {o.lightning_count_10km > 0 &&
                    <div>⚡ {o.lightning_count_10km} Blitze &lt;10 km</div>}
                  {o.gust_warning && <div className="font-bold text-orange-600">💨 Böenwarnung ({o.nowcast_ffx_kmh || o.wind_gust_10m_kmh} km/h)</div>}
                  {o.heavy_rain_warning && <div className="font-bold text-blue-700">🌧 Starkregen ({o.nowcast_rain_rate_1h} mm/h)</div>}
                  {o.lpi > 5 && <div className="text-yellow-600">⚡ LPI: {o.lpi?.toFixed(1)}</div>}
                  {o.tawes_max_gust_kmh > 30 && <div className="text-gray-500 text-xs">Station-Böe: {o.tawes_max_gust_kmh} km/h</div>}
                  {o.intensification_prob != null &&
                    <div>Intensivierung: {(o.intensification_prob * 100).toFixed(0)}%</div>}
                  <CellTendency obj={o} />
                </Popup>
              </Polygon>
              {(o.intensity_zones || []).map((zone, zi) => (
                <Polygon key={'z_' + o.id + '_' + zi}
                  positions={zone.coords.map(p => [p[1], p[0]])}
                  pathOptions={{
                    color: zone.color, weight: 1, fillColor: zone.color,
                    fillOpacity: zone.band === 'violett' ? 0.75
                               : zone.band === 'rot' || zone.band === 'rot_wrap' ? 0.60 : 0.45
                  }} />
              ))}
              {o.lat && o.lon && (
                <CircleMarker center={[o.lat, o.lon]} radius={3}
                  pathOptions={{ color: borderColor, fillColor: borderColor, fillOpacity: 1, weight: 1 }} />
              )}

              {(o.history || []).length >= 2 && (() => {
                const pts = (o.history || []).filter(h => h.lat != null && h.lon != null).slice(-6).map(h => [h.lat, h.lon])
                if (pts.length < 2) return null
                return <Polyline key={'hist_' + o.id} positions={pts} pathOptions={{ color: '#999', weight: 1.5, dashArray: '3,4', opacity: 0.5 }} />
              })()}

              {o.stationary_marker && o.lat && o.lon && (
                <CircleMarker center={[o.lat, o.lon]} radius={14}
                  pathOptions={{ color:'#b45309', weight:2, fillColor:'#fef3c7', fillOpacity:0.6, dashArray:'4,3' }}>
                  <Tooltip permanent direction="top" offset={[0,-14]}>⊕</Tooltip>
                </CircleMarker>
              )}

              {o.hail_warning && o.lat && o.lon && (
                <CircleMarker center={[o.lat, o.lon]} radius={18}
                  pathOptions={{ color:'#dc2626', weight:3, fillOpacity:0, dashArray:'6,3' }}>
                  <Tooltip permanent direction="top" offset={[0,-18]}>
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
            .filter(isValidForecastFeature)
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
              if (Number.isFinite(h)) g.pts.push({ h, ll: [b[1], b[0]], speed: p.speed_kmh, q10, q90, modeLabel: forecastModeLabel(p), rejectReason: p.forecast_reject_reason })
              if (!['kinematic', 'kinematic_fallback'].includes(p.forecast_mode)) { g.isKin = false; g.color = p.color || g.color }
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
                    <div>Forecast-Modus: {last.modeLabel}</div>
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
        {(locations.watchlist || []).map((w, i) => (
          <Circle key={'w' + i}
            center={[w.lat, w.lon]}
            radius={(w.radius_km || 5) * 1000}
            pathOptions={{ color: '#666', weight: 1, fillOpacity: 0.05 }}>
            <Popup>{w.name}</Popup>
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
                    <div style={{ fontWeight: 'normal', fontSize: 14 }}>
                      ID: {currentHit.cell_id} · {currentHit.distance_km} km ·{' '}
                      {currentHit.speed_kmh} km/h
                    </div>
                  </div>
                )}

                {!currentHit && slowApproachHit && (
                  <div style={{ color: '#ea580c', fontWeight: 'bold', marginTop: 4 }}>
                    🌧 Langsam ziehende Zelle ({slowApproachHit.speed_kmh} km/h)
                    <div style={{ fontWeight: 'normal', fontSize: 14 }}>
                      Erhöhtes Starkregenpotential · erweiterter Warnradius aktiv
                    </div>
                  </div>
                )}

                {forecastHits.length > 0 && (() => {
                  // B91: nur frühesten Horizont anzeigen
                  const [hz, entry] = forecastHits[0]
                  return (
                    <div style={{ marginTop: 6, fontSize: 14 }}>
                      <div>
                        +{hz} min · ID {entry.cell_id} ·{' '}
                        {entry.distance_km} km ·{' '}
                        {entry.speed_kmh} km/h
                        {entry.hit_type === 'slow_approach' && ' 🌧'}
                      </div>
                      {forecastHits.length > 1 && (
                        <div style={{ color: '#9ca3af', fontSize: 12, marginTop: 2 }}>
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
      </MapContainer>

      <BottomBar
        frames={frames}
        currentIdx={currentIdx < 0 ? 0 : currentIdx}
        playing={playing} speed={speed}
        onSetIdx={setCurrentIdx}
        onPlay={handlePlay} onPause={handlePause} onSpeed={setSpeed}
      />
    </div>
  )
}
