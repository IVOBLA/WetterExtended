// frontend/src/pages/MapFullscreen.jsx
import React, { useEffect, useState, useRef, useCallback } from 'react'
import {
  MapContainer, TileLayer, CircleMarker,
  Polyline, Polygon, Circle, Popup, ImageOverlay, Tooltip,
} from 'react-leaflet'
import {
  MAP_CENTER_KAERNTEN,
  MAP_ZOOM_FULLSCREEN,
  MAP_ZOOM_MIN,
  MAP_ZOOM_MAX,
  MAP_TILE_URL,
  MAP_TILE_ATTRIBUTION,
} from '../constants/mapDefaults.js'
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
  const [radarTs,        setRadarTs]        = useState(0)
  const [lightning,      setLightning]      = useState([])
  const [showLightning,  setShowLightning]  = useState(true)
  const [lightningAge,   setLightningAge]   = useState(30)  // Minuten
  const [frames,       setFrames]       = useState([])
  const [currentIdx,   setCurrentIdx]   = useState(-1)
  const [playing,      setPlaying]      = useState(false)
  const [speed,        setSpeed]        = useState(500)
  const [panelOpen,    setPanelOpen]    = useState(false)
  const [loading,      setLoading]      = useState(false)

  const timerRef       = useRef(null)
  const pollRef        = useRef(null)
  const lastImgRef     = useRef(null)
  const frameLoadTimer = useRef(null)

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

      // Schritt 2: Frame-Timestamp bestimmen, objects/forecast synchron laden
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

  // Frame-Sync für Animation: bei Scrubbing objects/forecast für den
  // angezeigten Frame laden. 200ms Debounce verhindert API-Flood.
  useEffect(() => {
    if (!frames.length || currentIdx < 0) return
    const frame = frames[currentIdx]
    if (!frame?.ts) return
    if (frameLoadTimer.current) clearTimeout(frameLoadTimer.current)
    frameLoadTimer.current = setTimeout(() => {
      Promise.all([
        api.get(`/api/objects?ts=${frame.ts}`),
        api.get(`/api/forecast?ts=${frame.ts}`),
      ]).then(([objs, fc]) => {
        setObjects(objs)
        setForecast(fc)
      }).catch(() => {})
    }, 200)
    return () => { if (frameLoadTimer.current) clearTimeout(frameLoadTimer.current) }
  }, [currentIdx, frames])

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
            <label style={{ display:'flex', alignItems:'center', gap:4, cursor:'pointer' }}>
              <input type="checkbox" checked={showLightning}
                onChange={e => setShowLightning(e.target.checked)}
                style={{ accentColor: '#fbbf24' }} />
              <span>⚡ Blitze</span>
              <select value={lightningAge}
                onChange={e => setLightningAge(Number(e.target.value))}
                style={{ fontSize:11, padding:'0 2px', border:'1px solid #555',
                         background:'#1a1a2e', color:'#fff', borderRadius:3 }}>
                {[10, 20, 30, 60].map(m => (
                  <option key={m} value={m}>{m} min</option>
                ))}
              </select>
            </label>

            {lastTs && (
              <div style={{ color: '#aaa', fontSize: 11 }}>Stand: {lastTs}</div>
            )}
          </div>
        )}
      </div>

      <MapContainer
        center={MAP_CENTER_KAERNTEN}
        zoom={MAP_ZOOM_FULLSCREEN}
        minZoom={MAP_ZOOM_MIN}
        maxZoom={MAP_ZOOM_MAX}
        style={{ width: '100%', height: '100%' }}
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

        {(currentIdx === frames.length - 1 || frames.length === 0) && objects.map(o => {
          if (!o.contour_geo || o.contour_geo.length < 3) return null
          const outerPos    = o.contour_geo.map(p => [p[1], p[0]])
          const borderColor = lineageColor[o.lineage] || '#888'
          return (
            <React.Fragment key={'cell_' + o.id}>
              <Polygon
                positions={outerPos}
                pathOptions={{ color: borderColor, weight: 2, fillColor: '#ff8800', fillOpacity: 0.25, interactive:true }}
                eventHandlers={{ click: (e) => { e.target.openPopup() } }}
              >
                <Popup autoPan={true} keepInView={true}>
                  <div><b>{o.id}</b> ({o.lineage})</div>
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
            const q10Lat = p.forecast_lat_q10
            const q10Lon = p.forecast_lon_q10
            const q90Lat = p.forecast_lat_q90
            const q90Lon = p.forecast_lon_q90
            const hasQ = q10Lat != null && q10Lon != null && q90Lat != null && q90Lon != null

            return (
              <React.Fragment key={'arrow_grp_' + i}>
                <Polyline
                  positions={[[a[1], a[0]], [b[1], b[0]]]}
                  pathOptions={pathOpts}>
                  <Popup>
                    <div>Zelle: <strong>{p.cell_id || p.id}</strong></div>
                    <div>+{p.horizon} min {isKinematic ? '(Schätzung)' : '(KI)'}</div>
                    {p.speed_kmh != null && <div>{p.speed_kmh} km/h</div>}
                    {p.hail_warning && <div className="text-red-600 font-bold">🧊 Hagelwarnung</div>}
                  </Popup>
                </Polyline>

                {hasQ && !isKinematic && (
                  <>
                    <Polyline positions={[[a[1],a[0]],[q10Lat,q10Lon]]} pathOptions={{ color: pathOpts.color, weight:1, dashArray:'3,5', opacity:0.45 }} />
                    <Polyline positions={[[a[1],a[0]],[q90Lat,q90Lon]]} pathOptions={{ color: pathOpts.color, weight:1, dashArray:'3,5', opacity:0.45 }} />
                  </>
                )}

                {hasQ && !isKinematic && (
                  <Polygon positions={[[b[1],b[0]],[q10Lat,q10Lon],[q90Lat,q90Lon]]} pathOptions={{ color: pathOpts.color, weight:0.5, fillColor:pathOpts.color, fillOpacity:0.10, dashArray:'2,4' }} />
                )}
              </React.Fragment>
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
