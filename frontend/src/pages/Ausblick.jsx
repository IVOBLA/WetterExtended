import React, { useEffect, useMemo, useState } from 'react'
import { MapContainer, TileLayer, Rectangle, Tooltip } from 'react-leaflet'
import api from '../api.js'
import {
  MAP_CENTER_KAERNTEN, MAP_ZOOM_DEFAULT, MAP_ZOOM_MIN, MAP_ZOOM_MAX,
  MAP_TILE_URL, MAP_TILE_ATTRIBUTION,
} from '../constants/mapDefaults.js'

const RISK_LABEL = { 1: 'Niedrig', 2: 'Mäßig', 3: 'Hoch' }
const DOMINANT_LABEL = {
  hagel: '🧊 Hagel', regen: '🌧 Starkregen', boe: '💨 Böen', instabilitaet: '☁ Instabilität',
}

export default function Ausblick() {
  const [data, setData] = useState({ hours: [] })
  const [hour, setHour] = useState(1)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let alive = true
    api.get('/api/outlook')
      .then(d => { if (alive) { setData(d || { hours: [] }); setLoading(false) } })
      .catch(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [])

  const hoursAvail = data.hours?.map(h => h.offset_h) ?? []
  const maxHour = hoursAvail.length ? Math.max(...hoursAvail) : 1

  const current = useMemo(
    () => data.hours?.find(h => h.offset_h === hour) ?? null,
    [data, hour],
  )

  const step = data.grid_step || 0.05
  const half = step / 2

  const fmtValid = iso => {
    if (!iso) return ''
    try {
      return new Date(iso.length <= 16 ? iso : iso)
        .toLocaleString('de-AT', { weekday: 'short', hour: '2-digit', minute: '2-digit' })
    } catch { return iso }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-2">12-Stunden-Ausblick</h1>
      <div className="card mb-3 bg-amber-50 border-amber-200 text-sm text-amber-900">
        Zutatenbasierter Konvektions-Ausblick (CAPE/LI/Scherung/Gefriergrenze) mit klimatologischem
        Attraktor-Prior. <b>Kein Zell-Tracking</b> — zeigt <i>wo und wann</i> Risikozonen entstehen
        können und deren mögliche Schwere. Nicht mit dem 0–60-min-Nowcast verwechseln.
      </div>

      {/* Zeit-Slider */}
      <div className="card mb-3 flex flex-wrap items-center gap-3 text-sm">
        <button className="px-2 py-0.5 border rounded hover:bg-gray-100"
          onClick={() => setHour(h => Math.max(1, h - 1))}>◀</button>
        <input type="range" min="1" max={Math.max(1, maxHour)} value={hour}
          onChange={e => setHour(Number(e.target.value))} className="w-48 accent-amber-600" />
        <button className="px-2 py-0.5 border rounded hover:bg-gray-100"
          onClick={() => setHour(h => Math.min(maxHour, h + 1))}>▶</button>
        <span className="font-mono font-semibold">+{hour} h</span>
        {current?.valid && <span className="text-gray-500">gültig {fmtValid(current.valid)}</span>}
        {loading && <span className="text-gray-400">lädt…</span>}
        {!loading && !hoursAvail.length &&
          <span className="text-gray-500">Noch kein Ausblick berechnet (Scheduler-Job outlook_compute).</span>}
      </div>

      {/* Legende */}
      <div className="bg-white border rounded p-2 mb-2 shadow-sm text-sm flex flex-wrap gap-4 items-center">
        <strong>Risiko:</strong>
        <span className="flex items-center gap-1"><span style={{ width: 14, height: 14, background: '#facc15', display: 'inline-block', borderRadius: 2 }} /> Niedrig</span>
        <span className="flex items-center gap-1"><span style={{ width: 14, height: 14, background: '#f97316', display: 'inline-block', borderRadius: 2 }} /> Mäßig</span>
        <span className="flex items-center gap-1"><span style={{ width: 14, height: 14, background: '#dc2626', display: 'inline-block', borderRadius: 2 }} /> Hoch</span>
        <span className="border-l pl-3 text-xs text-gray-500">Hover zeigt Regen/Böe/Hagel & CAPE/LI</span>
      </div>

      <MapContainer center={MAP_CENTER_KAERNTEN} zoom={MAP_ZOOM_DEFAULT}
        minZoom={MAP_ZOOM_MIN} maxZoom={MAP_ZOOM_MAX} style={{ height: '70vh', borderRadius: 8 }}>
        <TileLayer url={MAP_TILE_URL} attribution={MAP_TILE_ATTRIBUTION} />
        {current?.cells?.map((c, i) => {
          const sev = c.severity || {}; const info = c.info || {}
          return (
            <Rectangle key={'oc_' + i}
              bounds={[[c.lat - half, c.lon - half], [c.lat + half, c.lon + half]]}
              pathOptions={{ weight: 0, stroke: false, fillColor: c.color,
                fillOpacity: c.risk === 3 ? 0.55 : c.risk === 2 ? 0.42 : 0.3 }}>
              <Tooltip sticky>
                <div className="text-xs">
                  <div><b>Risiko: {RISK_LABEL[c.risk] || c.risk}</b> ({DOMINANT_LABEL[info.dominant] || info.dominant})</div>
                  <div>🌧 Regen: {sev.rain_mm_h ?? '–'} mm/h</div>
                  <div>💨 Böe: {sev.gust_kmh ?? '–'} km/h</div>
                  <div>🧊 Hagel: {sev.hail_cat ?? '–'} (Index {sev.hail_index ?? '–'})</div>
                  <div className="text-gray-500 mt-1">CAPE {info.cape ?? '–'} · LI {info.li ?? '–'} · SHIP {info.ship ?? '–'}</div>
                </div>
              </Tooltip>
            </Rectangle>
          )
        })}
      </MapContainer>
    </div>
  )
}
