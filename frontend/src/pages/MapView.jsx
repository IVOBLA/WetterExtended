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

        {objects.map(o => o.contour_geo && o.contour_geo.length > 0 && (
          <Polygon key={'p' + o.id}
            positions={o.contour_geo.map(p => [p[1], p[0]])}
            pathOptions={{ color: lineageColor[o.lineage] || 'gray', fillOpacity: 0.3, weight: 2 }} />
        ))}

        {objects.map(o => o.lat && o.lon && (
          <CircleMarker key={'m' + o.id}
            center={[o.lat, o.lon]}
            radius={Math.max(4, Math.sqrt(o.area || 0) / 8)}
            pathOptions={{ color: '#0d6efd' }}>
            <Popup>
              <div><b>{o.id}</b> ({o.lineage})</div>
              <div>parents: {(o.parents || []).join(',') || '—'}</div>
              <div>area: {o.area}</div>
              <div>core_ratio: {o.core_ratio}</div>
              {o.intensification_prob != null && <div>intensification: {(o.intensification_prob * 100).toFixed(0)}%</div>}
            </Popup>
          </CircleMarker>
        ))}

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
