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
      setObjects(a)
      setForecast(b)
      setLocations(c)
      setHorizons(d)
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
      </MapContainer>
    </div>
  )
}
