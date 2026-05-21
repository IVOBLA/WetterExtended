import React, { useEffect, useState } from 'react'
import api from '../api.js'

// Hilfsfunktion: 0.0 = Fallback-Wert → grau markieren
function Val({ v, unit = '', decimals = 1, zeroIsEmpty = false, negativeIsEmpty = false }) {
  if (v === null || v === undefined) return <span className="text-gray-300">—</span>
  const num = parseFloat(v)
  if (zeroIsEmpty && num === 0.0) return <span className="text-gray-300">0</span>
  if (negativeIsEmpty && num < 0) return <span className="text-gray-300">—</span>
  return (
    <span className={Math.abs(num) < 0.001 && zeroIsEmpty ? 'text-gray-400' : ''}>
      {num.toFixed(decimals)}{unit && <span className="text-gray-400 text-xs ml-0.5">{unit}</span>}
    </span>
  )
}

// Wolkenhöhe: unterscheidet zwischen fehlenden Daten (missing=1) und wolkenfrei (missing=0, height<0)
function CloudHeight({ height, missing, short = false }) {
  if (missing === 1 || missing === undefined || missing === null) {
    return <span className="text-gray-300">—</span>
  }
  const h = parseFloat(height)
  if (isNaN(h) || h <= 0) {
    return <span className="text-blue-300 text-xs" title="Wolkenfrei laut MSG IR108">{short ? '☀' : 'wolkenfrei'}</span>
  }
  return (
    <span>{Math.round(h)}<span className="text-gray-400 text-xs ml-0.5">m</span></span>
  )
}

function Group({ label, children }) {
  return (
    <div className="mb-1">
      <div className="text-xs text-gray-400 uppercase tracking-wide mb-0.5">{label}</div>
      <div className="text-sm">{children}</div>
    </div>
  )
}

// Windrichtung aus cos/sin berechnen
function windDirDeg(cos_val, sin_val) {
  if (!cos_val && !sin_val) return null
  const rad = Math.atan2(sin_val, cos_val)
  const deg = (rad * 180 / Math.PI + 360) % 360
  return deg.toFixed(0) + '°'
}

// px/Frame → km/h (Upscale-Faktor 3, ~2 km/px, Zyklus 120s)
const PX_TO_KMH = (1 / 3.0) * 2.0 * (3600 / 120)

// Timestamp "YYYY-MM-DD_HH-MM-SS" → Date
const parseTs = ts => {
  if (!ts) return null
  const [date, time] = ts.split('_')
  if (!date || !time) return null
  return new Date(`${date}T${time.replace(/-/g, ':')}`)
}

// Dauer in Minuten seit einem Timestamp
const durMin = ts => {
  const d = parseTs(ts)
  if (!d) return null
  return Math.round((Date.now() - d.getTime()) / 60000)
}

export default function LiveDaten() {
  const [objects, setObjects]   = useState([])
  const [lastTs, setLastTs]     = useState(null)
  const [loading, setLoading]   = useState(true)
  const [selected, setSelected] = useState(null)

  function load() {
    api.get('/api/objects')
      .then(data => {
        setObjects(data)
        if (data.length > 0) {
          setLastTs(new Date().toLocaleTimeString('de-AT'))
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    const t = setInterval(load, 30000)
    return () => clearInterval(t)
  }, [])

  if (loading) return <div className="text-gray-500 text-sm">Lade Live-Daten...</div>

  const active = objects.filter(o => (o.missing ?? 0) === 0)
  const sel = selected ? objects.find(o => o.id === selected) : null

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold">Live-Daten (API-Werte)</h1>
        <div className="flex items-center gap-3">
          {lastTs && <span className="text-xs text-gray-400">Stand: {lastTs}</span>}
          <button onClick={load} className="btn-secondary text-sm">↺ Reload</button>
        </div>
      </div>

      {active.length === 0 ? (
        <div className="bg-gray-50 border rounded p-4 text-sm text-gray-600">
          Aktuell keine Gewitterzellen erkannt. Bei aktivem Gewitter erscheinen
          hier alle Zellen mit ihren API-Werten.
        </div>
      ) : (
        <>
          {/* Übersichtstabelle */}
          <div className="card mb-4 overflow-auto">
            <h2 className="text-base font-semibold mb-2">
              {active.length} aktive Zelle{active.length !== 1 ? 'n' : ''}
            </h2>
            <table className="w-full text-sm whitespace-nowrap">
              <thead>
                <tr className="border-b text-xs text-gray-500 uppercase">
                  <th className="p-2 text-left">ID</th>
                  <th className="p-2 text-left">Seit</th>
                  <th className="p-2 text-left">Position</th>
                  <th className="p-2 text-right">Größe</th>
                  <th className="p-2 text-right">Core</th>
                  <th className="p-2 text-right">vx/vy</th>
                  <th className="p-2 text-center">Mode</th>
                  <th className="p-2 text-right">CAPE</th>
                  <th className="p-2 text-right">LI</th>
                  <th className="p-2 text-right">T 2m</th>
                  <th className="p-2 text-right">Td 2m</th>
                  <th className="p-2 text-right">Gefriergrenze</th>
                  <th className="p-2 text-right">Wind 700hPa</th>
                  <th className="p-2 text-right">Wolkenhöhe</th>
                  <th className="p-2 text-right">⚡ &lt;10km</th>
                  <th className="p-2 text-right">OF-Speed</th>
                </tr>
              </thead>
              <tbody>
                {active.map(o => (
                  <tr
                    key={o.id}
                    className={`border-b cursor-pointer hover:bg-blue-50 ${selected === o.id ? 'bg-blue-50' : ''}`}
                    onClick={() => setSelected(selected === o.id ? null : o.id)}
                  >
                    <td className="p-2 font-mono font-semibold text-blue-700">{o.id}</td>
                    <td className="p-2 text-xs">
                      {o.first_seen
                        ? (() => {
                            const d = parseTs(o.first_seen)
                            const m = durMin(o.first_seen)
                            return (
                              <>
                                <span className="font-medium">
                                  {d ? d.toLocaleTimeString('de-AT', { hour: '2-digit', minute: '2-digit' }) : '—'}
                                </span>
                                {m != null && (
                                  <span className="text-gray-400 ml-1">({m} min)</span>
                                )}
                              </>
                            )
                          })()
                        : <span className="text-gray-300">—</span>}
                    </td>
                    <td className="p-2 text-xs text-gray-600">
                      {o.lat?.toFixed(3)}°N {o.lon?.toFixed(3)}°E
                    </td>
                    <td className="p-2 text-right">{o.size ?? '—'}</td>
                    <td className="p-2 text-right">
                      <Val v={o.core_ratio} decimals={2} />
                    </td>
                    <td className="p-2 text-right text-xs">
                      {(o.vx * PX_TO_KMH).toFixed(0)}/
                      {(o.vy * PX_TO_KMH).toFixed(0)}
                      <span className="text-gray-400 ml-0.5">km/h</span>
                    </td>
                    <td className="p-2 text-center">
                      <span className={`text-xs px-1.5 py-0.5 rounded ${
                        o.forecast_mode === 'ml'
                          ? 'bg-green-100 text-green-800'
                          : 'bg-gray-100 text-gray-600'
                      }`}>{o.forecast_mode ?? '—'}</span>
                    </td>
                    <td className="p-2 text-right">
                      <Val v={o.cape} unit="J/kg" decimals={0} zeroIsEmpty />
                    </td>
                    <td className="p-2 text-right">
                      <Val v={o.arome_li} unit="°C" decimals={1} zeroIsEmpty />
                    </td>
                    <td className="p-2 text-right">
                      <Val v={o.arome_t2m} unit="°C" />
                    </td>
                    <td className="p-2 text-right">
                      <Val v={o.arome_td2m} unit="°C" />
                    </td>
                    <td className="p-2 text-right">
                      <Val v={o.arome_fl_height} unit="m" decimals={0} zeroIsEmpty />
                    </td>
                    <td className="p-2 text-right">
                      <Val v={o.wind_speed_700hPa} unit="km/h" zeroIsEmpty />
                      {o.wind_dir_cos != null && o.wind_dir_sin != null && (
                        <span className="text-gray-400 text-xs ml-1">
                          {windDirDeg(o.wind_dir_cos, o.wind_dir_sin)}
                        </span>
                      )}
                    </td>
                    <td className="p-2 text-right">
                      <CloudHeight height={o.cloud_top_height_msl} missing={o.cloud_height_missing} />
                    </td>
                    <td className="p-2 text-right">
                      <Val v={o.lightning_count_10km} decimals={0} zeroIsEmpty />
                    </td>
                    <td className="p-2 text-right">
                      <Val v={o.of_speed} decimals={1} zeroIsEmpty />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Detailansicht der gewählten Zelle */}
          {sel && (
            <div className="card">
              <h2 className="text-base font-semibold mb-3">
                Detail: Zelle <span className="font-mono text-blue-700">{sel.id}</span>
              </h2>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                <Group label="Position">
                  {sel.lat?.toFixed(4)}°N<br />
                  {sel.lon?.toFixed(4)}°E<br />
                  {sel.dem_elevation_m != null && (
                    <span className="text-gray-500 text-xs">
                      Gelände: {sel.dem_elevation_m.toFixed(0)} m MSL
                    </span>
                  )}
                </Group>
                <Group label="Thermodynamik">
                  CAPE: <Val v={sel.cape} unit="J/kg" decimals={0} zeroIsEmpty /><br />
                  LI: <Val v={sel.arome_li} unit="°C" zeroIsEmpty /><br />
                  Gefriergrenze: <Val v={sel.arome_fl_height} unit="m" decimals={0} zeroIsEmpty />
                </Group>
                <Group label="AROME-Gitterpunkt">
                  T2m: <Val v={sel.arome_t2m} unit="°C" /><br />
                  Td2m: <Val v={sel.arome_td2m} unit="°C" /><br />
                  FF10m: <Val v={sel.arome_ff10m} unit="km/h" />
                </Group>
                <Group label="Wind 700 hPa">
                  {sel.wind_speed_700hPa?.toFixed(1)} km/h
                  {' '}{windDirDeg(sel.wind_dir_cos, sel.wind_dir_sin)}
                </Group>
                <Group label="Wolke & Blitze">
                  Wolkentop: <CloudHeight height={sel.cloud_top_height_msl} missing={sel.cloud_height_missing} /><br />
                  Blitze &lt;10km: <Val v={sel.lightning_count_10km} decimals={0} />
                </Group>
                <Group label="Optical Flow">
                  Speed: <Val v={sel.of_speed} decimals={2} /><br />
                  Divergenz: <Val v={sel.of_divergence} decimals={4} /><br />
                  vx/vy: {sel.of_vx?.toFixed(2)} / {sel.of_vy?.toFixed(2)}
                </Group>
                <Group label="Stratiform-Umgebung">
                  Fläche: <Val v={sel.strat_area_px} unit="px" decimals={0} /><br />
                  Intensität: <Val v={sel.strat_intensity_mean} decimals={3} /><br />
                  dBZ-Gradient: <Val v={sel.strat_dbz_gradient} decimals={4} />
                </Group>
                <Group label="Tracking">
                  {sel.first_seen && (() => {
                    const d = parseTs(sel.first_seen)
                    const m = durMin(sel.first_seen)
                    return (
                      <>
                        Seit:{' '}
                        <span className="font-medium">
                          {d ? d.toLocaleTimeString('de-AT', { hour: '2-digit', minute: '2-digit' }) : '—'}
                        </span><br />
                        Dauer:{' '}
                        {m != null ? `${m} min` : '—'}
                        {sel.total_active_frames != null && (
                          <span className="text-gray-500 ml-1">
                            · {sel.total_active_frames} Frame{sel.total_active_frames !== 1 ? 's' : ''}
                          </span>
                        )}<br />
                      </>
                    )
                  })()}
                  Lineage: {sel.lineage ?? '—'}<br />
                  Trend: {sel.trend === 1 ? '↑ Intensivierung' : sel.trend === -1 ? '↓ Abschwächung' : '→ Stabil'}<br />
                  Missing: {sel.missing ?? 0} Frames
                </Group>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
