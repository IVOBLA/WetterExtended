import React, { useEffect, useState, useRef, useCallback } from 'react'
import {
  MapContainer, TileLayer, CircleMarker,
  Polyline, Polygon, Circle, Popup, ImageOverlay,
} from 'react-leaflet'
import api from '../api.js'

const lineageColor = {
  new: 'green', continued: 'blue', merged: 'orange', split: 'magenta'
}

export default function MapFullscreen() {
  const [objects,   setObjects]   = useState([])
  const [forecast,  setForecast]  = useState({ features: [] })
  const [locations, setLocations] = useState({ watchlist: [], hits: [], colors: {} })
  const [horizons,  setHorizons]  = useState({ horizons: [10, 20, 30, 40, 60], colors: {}, styles: {} })
  const [lastTs,       setLastTs]       = useState(null)
  const [radarBounds,  setRadarBounds]  = useState(null)
  const [radarOpacity, setRadarOpacity] = useState(0.65)
  const [showRadar,    setShowRadar]    = useState(true)
  const [radarTiming,  setRadarTiming]  = useState(null)
  const [radarTs,      setRadarTs]      = useState(0)
  // Animation
  const [frames,       setFrames]       = useState([])
  const [currentIdx,   setCurrentIdx]   = useState(-1)
  const [playing,      setPlaying]      = useState(false)
  const [speed,        setSpeed]        = useState(500)
  const timerRef = useRef(null)

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

  async function load() {
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
      if (timing) setRadarTiming(timing)
      if (bounds?.bounds) setRadarBounds(bounds.bounds)
      if (framesData?.frames) {
        setFrames(framesData.frames)
        setCurrentIdx(framesData.latest_idx ?? framesData.frames.length - 1)
      }
      setRadarTs(Date.now())
      setLastTs(new Date().toLocaleTimeString('de-AT'))
    } catch (e) { console.error(e) }
  }

  useEffect(() => {
    load()
    const t = setInterval(load, 60000)
    return () => clearInterval(t)
  }, [])

  const fmtTime = utcStr => utcStr
    ? new Date(utcStr).toLocaleTimeString('de-AT', { hour: '2-digit', minute: '2-digit' })
    : '—'

  const btnStyle = {
    padding: '1px 6px', border: '1px solid #d1d5db', borderRadius: 4,
    cursor: 'pointer', fontSize: 11, background: '#f9fafb', userSelect: 'none',
  }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 0 }}>

      {/* Overlay-Panel: Radar-Timing + Deckkraft-Slider — fixiert oben links */}
      <div style={{
        position: 'absolute', top: 10, left: 60, zIndex: 1000,
        background: 'rgba(255,255,255,0.93)', borderRadius: 8,
        padding: '8px 14px', fontSize: 12,
        boxShadow: '0 2px 6px rgba(0,0,0,0.20)',
        display: 'flex', flexDirection: 'column', gap: 5, minWidth: 230,
      }}>
        {radarTiming && (
          <>
            <div>
              🛰 Letztes Radar:{' '}
              <strong>{fmtTime(radarTiming.last_radar_image_utc)}</strong>
            </div>
            <div>
              ⏱ Nächste Abfrage:{' '}
              <strong>
                {radarTiming.next_fetch_estimated_utc
                  ? fmtTime(radarTiming.next_fetch_estimated_utc)
                  : `~${Math.round((radarTiming.loop_interval_s || 120) / 60)} min`}
              </strong>
            </div>
            <div style={{ color: radarTiming.cells_active ? '#cc0000' : '#999' }}>
              {radarTiming.cells_active ? '⚡ Zellen aktiv' : '✓ Keine aktiven Zellen'}
            </div>
          </>
        )}
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
          <input
            type="checkbox"
            checked={showRadar}
            onChange={e => setShowRadar(e.target.checked)}
          />
          <span style={{ fontWeight: 500 }}>Radar-Overlay</span>
        </label>
        {showRadar && (
          <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ color: '#666' }}>Deckkraft:</span>
            <input
              type="range" min="0" max="100"
              value={Math.round(radarOpacity * 100)}
              onChange={e => setRadarOpacity(Number(e.target.value) / 100)}
              style={{ width: 80 }}
            />
            <span style={{ fontFamily: 'monospace', minWidth: 28, textAlign: 'right' }}>
              {Math.round(radarOpacity * 100)}%
            </span>
          </label>
        )}
        {frames.length > 0 && showRadar && (
          <div style={{ marginTop: 6, paddingTop: 6, borderTop: '1px solid #eee' }}>
            <div style={{ display:'flex', alignItems:'center', gap:4, flexWrap:'wrap' }}>
              <button onClick={() => { handlePause(); setCurrentIdx(i => Math.max(0,i-1)) }}
                style={btnStyle}>◀</button>
              <button onClick={playing ? handlePause : handlePlay}
                style={{ ...btnStyle, background:'#dbeafe', fontWeight:600 }}>
                {playing ? '⏸' : '▶'}
              </button>
              <button onClick={() => { handlePause(); setCurrentIdx(i => Math.min(frames.length-1,i+1)) }}
                style={btnStyle}>▶</button>
              <input type="range" min="0" max={frames.length-1} value={currentIdx}
                onChange={e => { handlePause(); setCurrentIdx(Number(e.target.value)) }}
                style={{ width:70, accentColor:'#2563eb' }} />
              <span style={{ fontFamily:'monospace', fontSize:12, fontWeight:700, minWidth:34 }}>
                {frames[currentIdx]?.label ?? '—'}
              </span>
            </div>
            <div style={{ display:'flex', gap:3, marginTop:4 }}>
              {[500,300,150].map(s => (
                <button key={s} onClick={() => setSpeed(s)}
                  style={{ ...btnStyle, background: speed===s?'#2563eb':'', color: speed===s?'#fff':'' }}>
                  {s===500?'1×':s===300?'2×':'4×'}
                </button>
              ))}
            </div>
          </div>
        )}
        {lastTs && (
          <div style={{ color: '#aaa', fontSize: 11, marginTop:4 }}>Stand: {lastTs}</div>
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

        {/* Radar-Overlay */}
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
          const outerPos = o.contour_geo.map(p => [p[1], p[0]])
          const borderColor = lineageColor[o.lineage] || '#888'
          return (
            <React.Fragment key={'cell_' + o.id}>
              <Polygon
                positions={outerPos}
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
                               : zone.band === 'rot' || zone.band === 'rot_wrap' ? 0.60
                               : 0.45
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
        })}

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
    </div>
  )
}
