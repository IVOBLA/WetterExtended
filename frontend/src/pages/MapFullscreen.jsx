// frontend/src/pages/MapFullscreen.jsx
import React, { useEffect, useState, useRef, useCallback } from 'react'
import {
  MapContainer, TileLayer, CircleMarker,
  Polyline, Polygon, Circle, Popup, ImageOverlay,
} from 'react-leaflet'
import api from '../api.js'

const lineageColor = {
  new: 'green', continued: 'blue', merged: 'orange', split: 'magenta'
}

function TBtn({ onClick, active, children, style = {} }) {
  return (
    <button onClick={onClick} style={{
      minWidth: 40, minHeight: 36, padding: '0 10px',
      border: '1px solid #d1d5db', borderRadius: 6,
      cursor: 'pointer', fontSize: 13, fontWeight: active ? 700 : 400,
      background: active ? '#2563eb' : '#f9fafb',
      color: active ? '#fff' : '#222',
      userSelect: 'none', WebkitTapHighlightColor: 'transparent',
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
      background: 'rgba(255,255,255,0.95)',
      borderTop: '1px solid #e5e7eb',
      padding: '6px 12px',
      display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
    }}>
      <TBtn onClick={() => { onPause(); onSetIdx(i => Math.max(0, i - 1)) }}>◀</TBtn>
      <TBtn onClick={playing ? onPause : onPlay} active={playing} style={{ minWidth: 44 }}>
        {playing ? '⏸' : '▶'}
      </TBtn>
      <TBtn onClick={() => { onPause(); onSetIdx(i => Math.min(frames.length - 1, i + 1)) }}>▶▶</TBtn>
      <input
        type="range" min="0" max={frames.length - 1} value={currentIdx < 0 ? 0 : currentIdx}
        onChange={e => { onPause(); onSetIdx(Number(e.target.value)) }}
        style={{ flex: 1, minWidth: 80, accentColor: '#2563eb', height: 20 }}
      />
      <span style={{ fontFamily: 'monospace', fontSize: 13, fontWeight: 700, minWidth: 38 }}>
        {cur?.label ?? '—'}
      </span>
      <div style={{ display: 'flex', gap: 4 }}>
        {[500, 300, 150].map(s => (
          <TBtn key={s} onClick={() => onSpeed(s)} active={speed === s}>
            {s === 500 ? '1×' : s === 300 ? '2×' : '4×'}
          </TBtn>
        ))}
      </div>
    </div>
  )
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
  const [radarTs,      setRadarTs]      = useState(0)
  const [frames,       setFrames]       = useState([])
  const [currentIdx,   setCurrentIdx]   = useState(-1)
  const [playing,      setPlaying]      = useState(false)
  const [speed,        setSpeed]        = useState(500)
  const [panelOpen,    setPanelOpen]    = useState(false)
  const [loading,      setLoading]      = useState(false)

  const timerRef   = useRef(null)
  const pollRef    = useRef(null)
  const lastImgRef = useRef(null)

  const currentFrame = frames[currentIdx] ?? null
  const radarUrl = currentFrame
    ? `/api/radar_image?ts=${currentFrame.ts}`
    : `/api/radar_image?t=${radarTs}`

  useEffect(() => {
    frames.forEach(f => { const img = new window.Image(); img.src = `/api/radar_image?ts=${f.ts}` })
  }, [frames])

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
    setLoading(true)
    try {
      const [a, b, c, d, timing, bounds, framesData] = await Promise.all([
        api.get('/api/objects'),
        api.get('/api/forecast'),
        api.get('/api/locations'),
        api.get('/api/horizons'),
        api.get('/api/radar_timing').catch(() => null),
        api.get('/api/radar_bounds').catch(() => null),
        api.get('/api/radar_frames').catch(() => null),
      ])
      setObjects(a); setForecast(b); setLocations(c); setHorizons(d)
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
      if (framesData?.frames) {
        setFrames(framesData.frames)
        setCurrentIdx(framesData.latest_idx ?? framesData.frames.length - 1)
      }
      setLastTs(new Date().toLocaleTimeString('de-AT'))
    } catch (e) {
      console.error(e)
      schedulePoll(null)
    } finally {
      setLoading(false)
    }
  }

  loadRef.current = load

  useEffect(() => {
    load()
    return () => {
      if (pollRef.current)  clearTimeout(pollRef.current)
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [])

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
                    {radarTiming.cells_active ? '⚡ Zellen aktiv' : '✓ Keine aktiven Zellen'}
                  </div>
                </div>
                <div style={{ borderTop: '1px solid #e5e7eb' }} />
              </>
            )}

            <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}>
              <input
                type="checkbox" checked={showRadar}
                onChange={e => setShowRadar(e.target.checked)}
                style={{ width: 18, height: 18 }}
              />
              <span style={{ fontWeight: 500 }}>Radar-Overlay</span>
            </label>

            {showRadar && (
              <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ color: '#555', minWidth: 62, fontSize: 12 }}>Deckkraft:</span>
                <input
                  type="range" min="0" max="100"
                  value={Math.round(radarOpacity * 100)}
                  onChange={e => setRadarOpacity(Number(e.target.value) / 100)}
                  style={{ flex: 1, height: 20, accentColor: '#2563eb' }}
                />
                <span style={{ fontFamily: 'monospace', minWidth: 32, textAlign: 'right', fontSize: 12 }}>
                  {Math.round(radarOpacity * 100)}%
                </span>
              </label>
            )}

            {lastTs && (
              <div style={{ color: '#aaa', fontSize: 11 }}>Stand: {lastTs}</div>
            )}
          </div>
        )}
      </div>

      <MapContainer
        center={[46.62, 14.31]}
        zoom={8}
        style={{ width: '100%', height: '100%' }}
      >
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution="© OpenStreetMap"
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

        {(currentIdx === frames.length - 1 || frames.length === 0) && objects.map(o => {
          if (!o.contour_geo || o.contour_geo.length < 3) return null
          const outerPos    = o.contour_geo.map(p => [p[1], p[0]])
          const borderColor = lineageColor[o.lineage] || '#888'
          return (
            <React.Fragment key={'cell_' + o.id}>
              <Polygon positions={outerPos}
                pathOptions={{ color: borderColor, weight: 2, fillColor: '#ff8800', fillOpacity: 0.15 }}>
                <Popup>
                  <div><b>{o.id}</b> ({o.lineage})</div>
                  <div>core_ratio: {(o.core_ratio || 0).toFixed(2)}</div>
                  {o.cape != null && <div>CAPE: {o.cape?.toFixed(0)} J/kg</div>}
                  {o.lightning_count_10km > 0 &&
                    <div>⚡ {o.lightning_count_10km} Blitze &lt;10 km</div>}
                  {o.intensification_prob != null &&
                    <div>Intensivierung: {(o.intensification_prob * 100).toFixed(0)}%</div>}
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
            </React.Fragment>
          )
        })}

        {(currentIdx === frames.length - 1 || frames.length === 0) &&
         (forecast.features || [])
          .filter(f => f.properties?.has_arrow !== false)
          .map((f, i) => {
            const [a, b] = f.geometry.coordinates
            const p = f.properties || {}
            const isKinematic = p.forecast_mode === 'kinematic'
            const style = horizons.styles[p.horizon] || horizons.styles[String(p.horizon)] || {}
            const pathOpts = isKinematic
              ? { color: '#888888', weight: 1.5, dashArray: '6,5', opacity: 0.7 }
              : { color: p.color || '#888', weight: style.weight || 2, dashArray: style.dash || '' }
            return (
              <Polyline key={'a' + i}
                positions={[[a[1], a[0]], [b[1], b[0]]]}
                pathOptions={pathOpts}>
                <Popup>
                  {isKinematic
                    ? `Bewegungsschätzung (${p.kinematic_source || '?'}) — ${p.id}`
                    : `+${p.horizon} min KI — ${p.cell_id || p.id}`}
                  <div>{p.speed_kmh != null ? `${p.speed_kmh} km/h` : ''}</div>
                </Popup>
              </Polyline>
            )
          })
        }

        {(locations.watchlist || []).map((w, i) => (
          <Circle key={'w' + i}
            center={[w.lat, w.lon]}
            radius={(w.radius_km || 5) * 1000}
            pathOptions={{ color: '#666', weight: 1, fillOpacity: 0.05 }}>
            <Popup>{w.name}</Popup>
          </Circle>
        ))}

        {(locations.hits || []).map((h, i) => {
          const hzs = Object.keys(h.hits || {}).map(Number).sort((a, b) => a - b)
          const color = locations.colors[hzs[0]] || locations.colors[String(hzs[0])] || '#e33'
          return (
            <CircleMarker key={'h' + i} center={[h.lat, h.lon]} radius={10}
              pathOptions={{ color, fillColor: color, fillOpacity: 0.7, weight: 3 }}>
              <Popup>
                <b>{h.name}</b>
                <div>⚠ betroffen ab +{hzs[0]} min</div>
                {hzs.map(hz => (
                  <div key={hz}>+{hz}m: {h.hits[hz].cell_id} ({h.hits[hz].distance_km} km)</div>
                ))}
              </Popup>
            </CircleMarker>
          )
        })}
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
