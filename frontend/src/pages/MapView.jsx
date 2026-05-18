import React, { useEffect, useState } from 'react'
import {
  MapContainer, TileLayer, CircleMarker, Polyline,
  Polygon, Circle, Popup, ImageOverlay,
} from 'react-leaflet'
import api from '../api.js'

const lineageColor = {
  new: 'green', continued: 'blue', merged: 'orange', split: 'magenta',
}

function Legend({ horizons, colors }) {
  return (
    <div className="bg-white border rounded p-2 mb-2 shadow-sm text-sm flex flex-wrap gap-3 items-center">
      <strong>Horizonte:</strong>
      {horizons.map(h => (
        <span key={h} className="flex items-center gap-1">
          <span style={{
            display: 'inline-block', width: 16, height: 3,
            background: colors[h] || colors[String(h)] || '#888',
          }} />
          +{h} min
        </span>
      ))}
      <span className="ml-2 flex items-center gap-1">
        <span style={{
          display: 'inline-block', width: 16, height: 3,
          background: '#888', border: '1px dashed #666',
        }} />
        Kinematik
      </span>
    </div>
  )
}

export default function MapView() {
  const [objects,      setObjects]      = useState([])
  const [forecast,     setForecast]     = useState({ features: [] })
  const [locations,    setLocations]    = useState({ watchlist: [], hits: [], colors: {} })
  const [horizons,     setHorizons]     = useState({ horizons: [10, 20, 30, 40, 60], colors: {}, styles: {} })
  const [radarTiming,  setRadarTiming]  = useState(null)
  const [radarBounds,  setRadarBounds]  = useState(null)
  const [radarOpacity, setRadarOpacity] = useState(0.65)
  const [showRadar,    setShowRadar]    = useState(true)
  const [radarTs,      setRadarTs]      = useState(0)

  async function load() {
    try {
      const [a, b, c, d, timing, bounds] = await Promise.all([
        api.get('/api/objects'),
        api.get('/api/forecast'),
        api.get('/api/locations'),
        api.get('/api/horizons'),
        api.get('/api/radar_timing').catch(() => null),
        api.get('/api/radar_bounds').catch(() => null),
      ])
      setObjects(a)
      setForecast(b)
      setLocations(c)
      setHorizons(d)
      if (timing) setRadarTiming(timing)
      if (bounds?.bounds) setRadarBounds(bounds.bounds)
      setRadarTs(Date.now())
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

  return (
    <div>
      <h1 className="text-2xl font-bold mb-3">Live-Karte</h1>

      {/* Radar-Timing Info-Bar */}
      {radarTiming && (
        <div className="flex flex-wrap gap-4 text-xs text-gray-600 bg-blue-50
                        border border-blue-200 rounded px-3 py-1.5 mb-2">
          <span>🛰 Letztes Radar: <strong>{fmtTime(radarTiming.last_radar_image_utc)}</strong></span>
          <span>⏱ Nächste Abfrage: <strong>{fmtTime(radarTiming.next_fetch_estimated_utc)}</strong></span>
          <span className={radarTiming.cells_active ? 'text-red-600 font-semibold' : 'text-gray-400'}>
            {radarTiming.cells_active ? '⚡ Zellen aktiv' : '✓ Keine aktiven Zellen'}
          </span>
        </div>
      )}

      <Legend horizons={horizons.horizons} colors={horizons.colors} />

      {/* Radar-Overlay Steuerung */}
      <div className="flex flex-wrap items-center gap-4 mb-2 text-sm
                      bg-gray-50 border rounded px-3 py-2">
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={showRadar}
            onChange={e => setShowRadar(e.target.checked)}
          />
          <span className="font-medium">Radar-Overlay</span>
        </label>
        {showRadar && (
          <label className="flex items-center gap-2">
            <span className="text-gray-500">Deckkraft:</span>
            <input
              type="range" min="0" max="100"
              value={Math.round(radarOpacity * 100)}
              onChange={e => setRadarOpacity(Number(e.target.value) / 100)}
              className="w-28 accent-blue-600"
            />
            <span className="w-8 text-right font-mono text-xs">
              {Math.round(radarOpacity * 100)}%
            </span>
          </label>
        )}
        <button
          onClick={load}
          className="text-xs text-blue-600 hover:text-blue-800 underline ml-auto"
        >
          ↺ Neu laden
        </button>
      </div>

      <MapContainer
        center={[46.62, 14.31]}
        zoom={8}
        style={{ height: '70vh', borderRadius: 8 }}
      >
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution="© OpenStreetMap"
        />

        {/* Radar-Overlay: auf BBOX zugeschnittenes ARSO-Bild mit transparentem BG */}
        {showRadar && radarBounds && (
          <ImageOverlay
            key={radarTs}
            url={`/api/radar_image?t=${radarTs}`}
            bounds={radarBounds}
            opacity={radarOpacity}
            zIndex={200}
          />
        )}

        {/* Gewitterzellen — nur aktive (missing === 0, bereits durch API gefiltert) */}
        {objects.map(o => {
          if (!o.contour_geo || o.contour_geo.length < 3) return null
          const outerPos    = o.contour_geo.map(p => [p[1], p[0]])
          const borderColor = lineageColor[o.lineage] || '#888'
          return (
            <React.Fragment key={'cell_' + o.id}>
              <Polygon
                positions={outerPos}
                pathOptions={{
                  color: borderColor, weight: 2,
                  fillColor: '#ff8800', fillOpacity: 0.15,
                }}
              >
                <Popup>
                  <div><strong>{o.id}</strong> ({o.lineage})</div>
                  <div>core_ratio: {(o.core_ratio || 0).toFixed(2)}</div>
                  {o.cape != null && <div>CAPE: {o.cape?.toFixed(0)} J/kg</div>}
                  {o.lightning_count_10km > 0 &&
                    <div>⚡ {o.lightning_count_10km} Blitze &lt;10 km</div>}
                  {o.intensification_prob != null &&
                    <div>Intensivierung: {(o.intensification_prob * 100).toFixed(0)}%</div>}
                </Popup>
              </Polygon>

              {/* Intensitätszonen (orange/rot/violett) */}
              {(o.intensity_zones || []).map((zone, zi) => (
                <Polygon
                  key={'z_' + o.id + '_' + zi}
                  positions={zone.coords.map(p => [p[1], p[0]])}
                  pathOptions={{
                    color: zone.color, weight: 1,
                    fillColor: zone.color,
                    fillOpacity:
                      zone.band === 'violett' ? 0.75
                      : (zone.band === 'rot' || zone.band === 'rot_wrap') ? 0.60
                      : 0.45,
                  }}
                />
              ))}

              {o.lat && o.lon && (
                <CircleMarker
                  center={[o.lat, o.lon]}
                  radius={3}
                  pathOptions={{
                    color: borderColor, fillColor: borderColor,
                    fillOpacity: 1, weight: 1,
                  }}
                />
              )}
            </React.Fragment>
          )
        })}

        {/* Vorhersage-Pfeile — nur bei echter Bewegung (has_arrow !== false) */}
        {(forecast.features || [])
          .filter(f => f.properties?.has_arrow !== false)
          .map((f, i) => {
            const [a, b] = f.geometry.coordinates
            const p = f.properties || {}
            const isKinematic = p.forecast_mode === 'kinematic'
            const pathOpts = isKinematic
              ? { color: '#888888', weight: 1.5, dashArray: '6,5', opacity: 0.7 }
              : { color: p.color || '#888', weight: p.weight || 2, dashArray: p.dash || '' }
            return (
              <Polyline
                key={'a' + i}
                positions={[[a[1], a[0]], [b[1], b[0]]]}
                pathOptions={pathOpts}
              >
                <Popup>
                  <div>Zelle: <strong>{p.cell_id}</strong></div>
                  <div>Horizont: +{p.horizon} min</div>
                  {p.speed_kmh != null && <div>Geschwindigkeit: {p.speed_kmh} km/h</div>}
                  <div>Modus: {isKinematic ? 'Kinematik' : 'KI-Vorhersage'}</div>
                </Popup>
              </Polyline>
            )
          })}

        {/* Ortschaften-Watchlist */}
        {(locations.watchlist || []).map((loc, i) => (
          <Circle
            key={'loc_' + i}
            center={[loc.lat, loc.lon]}
            radius={(loc.radius_km || 5) * 1000}
            pathOptions={{ color: '#0066cc', weight: 1, fillOpacity: 0.04 }}
          >
            <Popup>{loc.name}</Popup>
          </Circle>
        ))}

        {/* Betroffene Ortschaften hervorheben */}
        {(locations.hits || []).map((hit, i) => (
          <Circle
            key={'hit_' + i}
            center={[hit.lat, hit.lon]}
            radius={3000}
            pathOptions={{ color: '#ff0000', weight: 2, fillColor: '#ff0000', fillOpacity: 0.2 }}
          >
            <Popup>
              <strong>⚠️ {hit.name}</strong>
              <div>Zelle {hit.cell_id} in {hit.eta_min} min erwartet</div>
            </Popup>
          </Circle>
        ))}
      </MapContainer>
    </div>
  )
}
