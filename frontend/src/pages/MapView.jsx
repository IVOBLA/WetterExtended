import React, { useEffect, useState } from 'react'
import { MapContainer, TileLayer, CircleMarker, Polyline, Polygon, Circle, Popup } from 'react-leaflet'
import api from '../api.js'

const lineageColor = { new: 'green', continued: 'blue', merged: 'orange', split: 'magenta' }

function Legend({ horizons, colors }) {
  return (
    <div className="bg-white border rounded p-2 mb-2 shadow-sm text-sm">
      <strong className="mr-2">Vorhersage-Horizonte:</strong>
      {horizons.map(h => (
        <span key={h} className="legend-item">
          <span className="swatch" style={{ background: colors[h] || colors[String(h)] || '#888' }} />
          +{h} min
        </span>
      ))}
      <span className="ml-4"><strong>Lineage:</strong></span>
      {Object.entries(lineageColor).map(([k, v]) => (
        <span key={k} className="legend-item">
          <span className="swatch" style={{ background: v }} />{k}
        </span>
      ))}
    </div>
  )
}

export default function MapView() {
  const [objects, setObjects] = useState([])
  const [forecast, setForecast] = useState({ features: [] })
  const [locations, setLocations] = useState({ watchlist: [], hits: [], colors: {} })
  const [horizons, setHorizons] = useState({ horizons: [10, 20, 30, 40, 60], colors: {}, styles: {} })

  async function load() {
    try {
      const [a, b, c, d] = await Promise.all([
        api.get('/api/objects'),
        api.get('/api/forecast'),
        api.get('/api/locations'),
        api.get('/api/horizons'),
      ])
      setObjects(a); setForecast(b); setLocations(c); setHorizons(d)
    } catch (e) { console.error(e) }
  }

  useEffect(() => {
    load()
    const t = setInterval(load, 60000)
    return () => clearInterval(t)
  }, [])

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Live-Karte</h1>
      <Legend horizons={horizons.horizons} colors={horizons.colors} />
      <MapContainer center={[46.62, 14.31]} zoom={8} style={{ height: '70vh', borderRadius: 8 }}>
        <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution="© OpenStreetMap" />

        {objects.map(o => {
          if (!o.contour_geo || o.contour_geo.length < 3) return null
          const outerPos = o.contour_geo.map(p => [p[1], p[0]])
          const borderColor = lineageColor[o.lineage] || '#888'
          return (
            <React.Fragment key={'cell_' + o.id}>
              {/* Äußere Zellkontur */}
              <Polygon
                positions={outerPos}
                pathOptions={{ color: borderColor, weight: 2, fillColor: '#ff8800', fillOpacity: 0.15 }}>
                <Popup>
                  <div><b>{o.id}</b> ({o.lineage})</div>
                  <div>area: {o.area} | core_ratio: {(o.core_ratio||0).toFixed(2)}</div>
                  {o.intensification_prob != null &&
                    <div>intensification: {(o.intensification_prob*100).toFixed(0)}%</div>}
                  {o.parents?.length > 0 && <div>parents: {o.parents.join(', ')}</div>}
                </Popup>
              </Polygon>

              {/* Intensitätszonen innerhalb der Zelle (Orange → Rot → Violett) */}
              {(o.intensity_zones || []).map((zone, zi) => (
                <Polygon key={'z_' + o.id + '_' + zi}
                  positions={zone.coords.map(p => [p[1], p[0]])}
                  pathOptions={{
                    color: zone.color,
                    weight: 1,
                    fillColor: zone.color,
                    fillOpacity: zone.band === 'violett' ? 0.75
                               : zone.band === 'rot' || zone.band === 'rot_wrap' ? 0.60
                               : 0.45
                  }} />
              ))}

              {/* Mittelpunkt-Label */}
              {o.lat && o.lon && (
                <CircleMarker center={[o.lat, o.lon]} radius={3}
                  pathOptions={{ color: borderColor, fillColor: borderColor, fillOpacity: 1, weight: 1 }} />
              )}
            </React.Fragment>
          )
        })}

        {(forecast.features || []).map((f, i) => {
          const [a, b] = f.geometry.coordinates
          const p = f.properties || {}
          const style = horizons.styles[p.horizon] || horizons.styles[String(p.horizon)] || {}
          return (
            <Polyline key={'a' + i}
              positions={[[a[1], a[0]], [b[1], b[0]]]}
              pathOptions={{ color: p.color || '#888', weight: style.weight || 2, dashArray: style.dash || '' }}>
              <Popup>+{p.horizon} min — {p.id}</Popup>
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
          const color = locations.colors[hzs[0]] || locations.colors[String(hzs[0])] || '#888'
          return (
            <CircleMarker key={'h' + i} center={[h.lat, h.lon]} radius={10}
              pathOptions={{ color, fillColor: color, fillOpacity: 0.7, weight: 3 }}>
              <Popup>
                <b>{h.name}</b>
                <div>betroffen ab +{hzs[0]} min</div>
                {hzs.map(hz => <div key={hz}>+{hz}m: {h.hits[hz].cell_id} ({h.hits[hz].distance_km} km)</div>)}
              </Popup>
            </CircleMarker>
          )
        })}
      </MapContainer>
    </div>
  )
}
