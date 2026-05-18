import React, { useEffect, useState } from 'react'
import {
  MapContainer, TileLayer, CircleMarker,
  Polyline, Polygon, Circle, Popup
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
  const [lastTs,    setLastTs]    = useState(null)

  async function load() {
    try {
      const [a, b, c, d] = await Promise.all([
        api.get('/api/objects'),
        api.get('/api/forecast'),
        api.get('/api/locations'),
        api.get('/api/horizons'),
      ])
      setObjects(a); setForecast(b); setLocations(c); setHorizons(d)
      setLastTs(new Date().toLocaleTimeString('de-AT'))
    } catch (e) { console.error(e) }
  }

  useEffect(() => {
    load()
    const t = setInterval(load, 60000)
    return () => clearInterval(t)
  }, [])

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 0 }}>
      <MapContainer
        center={[46.62, 14.31]}
        zoom={8}
        style={{ width: '100%', height: '100%' }}
      >
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution="© OpenStreetMap"
        />

        {objects.map(o => {
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

        {(forecast.features || [])
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

      {/* Overlay: Legende + Status oben links */}
      <div style={{
        position: 'absolute', top: 12, left: 12, zIndex: 1000,
        background: 'rgba(255,255,255,0.90)', borderRadius: 8,
        padding: '8px 12px', fontSize: 12, boxShadow: '0 2px 8px rgba(0,0,0,.2)',
        maxWidth: 340,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <strong style={{ fontSize: 13 }}>WetterExtended</strong>
          {lastTs && (
            <span style={{ color: '#666', fontSize: 11 }}>Stand: {lastTs}</span>
          )}
          <a href="/map" style={{ marginLeft: 'auto', color: '#1d4ed8', fontSize: 11 }}>
            ← Admin
          </a>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 10px' }}>
          {horizons.horizons.map(h => {
            const c = horizons.colors[h] || horizons.colors[String(h)] || '#888'
            return (
              <span key={h} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <span style={{ display: 'inline-block', width: 14, height: 3, background: c, borderRadius: 2 }} />
                <span>+{h} min</span>
              </span>
            )
          })}
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ display: 'inline-block', width: 14, height: 3, background: '#aaa', borderRadius: 2 }} />
            <span style={{ color: '#888' }}>kinematisch</span>
          </span>
        </div>
        {objects.filter(o => (o.missing ?? 0) === 0).length > 0 && (
          <div style={{ marginTop: 4, color: '#c2410c', fontWeight: 600 }}>
            ⛈ {objects.filter(o => (o.missing ?? 0) === 0).length} aktive Zelle(n)
          </div>
        )}
      </div>
    </div>
  )
}
