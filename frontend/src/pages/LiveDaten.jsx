import React, { useEffect, useState } from 'react'
import api from '../api.js'

// ---------------------------------------------------------------------------
// Hilfskomponenten (Modul-Ebene, kein Remount-Problem)
// ---------------------------------------------------------------------------

function Val({ v, unit = '', decimals = 1, zeroIsEmpty = false, negativeIsEmpty = false }) {
  if (v === null || v === undefined) return <span className="text-gray-300">—</span>
  const num = parseFloat(v)
  if (zeroIsEmpty && num === 0.0) return <span className="text-gray-300">0</span>
  if (negativeIsEmpty && num < 0) return <span className="text-gray-300">—</span>
  return (
    <span className={Math.abs(num) < 0.001 && zeroIsEmpty ? 'text-gray-400' : ''}>
      {num.toFixed(decimals)}
      {unit && <span className="text-gray-400 text-xs ml-0.5">{unit}</span>}
    </span>
  )
}

// Wolkenhöhe: unterscheidet fehlende Daten (missing=1) von wolkenfrei (height<=0)
function CloudHeight({ height, missing, short = false, lowConfidence = false }) {
  if (missing === 1 || missing === undefined || missing === null)
    return <span className="text-gray-300">—</span>
  const h = parseFloat(height)
  if (isNaN(h) || h <= 0)
    return <span className="text-blue-300 text-xs" title="Wolkenfrei laut MSG IR108">{short ? '☀' : 'wolkenfrei'}</span>
  if (lowConfidence)
    return (
      <span className="text-amber-500"
        title="Unsicher: IR108 zeigt einen warmen Wolkenoberteil — MSG-Bild ggf. veraltet/versetzt oder flache bzw. frische Zelle. Wert ist eine grobe Untergrenze, nicht der echte Cb-Top.">
        ~{Math.round(h)}<span className="text-gray-400 text-xs ml-0.5">m</span>
      </span>
    )
  return <span>{Math.round(h)}<span className="text-gray-400 text-xs ml-0.5">m</span></span>
}

function Group({ label, children }) {
  return (
    <div className="mb-1">
      <div className="text-xs text-gray-400 uppercase tracking-wide mb-0.5">{label}</div>
      <div className="text-sm">{children}</div>
    </div>
  )
}

// Windrichtung aus cos/sin (700-hPa-Wind, AROME)
function windDirDeg(cos_val, sin_val) {
  if (!cos_val && !sin_val) return null
  const rad = Math.atan2(sin_val, cos_val)
  return ((rad * 180 / Math.PI + 360) % 360).toFixed(0) + '°'
}

// Timestamp "YYYY-MM-DD_HH-MM-SS" → Date (Vienna-Lokalzeit, ohne Z-Suffix)
const parseTs = ts => {
  if (!ts) return null
  const [date, time] = ts.split('_')
  if (!date || !time) return null
  return new Date(`${date}T${time.replace(/-/g, ':')}`)
}

// Minuten seit einem Timestamp
const durMin = ts => {
  const d = parseTs(ts)
  if (!d) return null
  return Math.round((Date.now() - d.getTime()) / 60000)
}

// "Zuletzt aktiv"-Anzeige für inaktive Zellen
// Unterstützt _last_seen_ts (History-Endpoint) und missing_since (Epoch, tracking_memory)
function lastSeenDisplay(o) {
  if (o._last_seen_ts) {
    const d = parseTs(o._last_seen_ts)
    if (!d) return '—'
    const mins = Math.round((Date.now() - d.getTime()) / 60000)
    return `${d.toLocaleTimeString('de-AT', { hour: '2-digit', minute: '2-digit' })} (${mins} min)`
  }
  if (o.missing_since) {
    const epochMs = parseFloat(o.missing_since) * 1000
    const d = new Date(epochMs)
    const mins = Math.round((Date.now() - epochMs) / 60000)
    return `${d.toLocaleTimeString('de-AT', { hour: '2-digit', minute: '2-digit' })} (${mins} min)`
  }
  return '—'
}

// ---------------------------------------------------------------------------
// Tabellen-Hilfskomponenten (Modul-Ebene)
// ---------------------------------------------------------------------------

// Gemeinsamer Tabellenkopf für aktive und inaktive Zellen
function CellTableHeader({ isInactive }) {
  return (
    <tr className="border-b text-xs text-gray-500 uppercase">
      <th className="p-2 text-left">ID</th>
      <th className="p-2 text-left">{isInactive ? 'Zuletzt' : 'Seit'}</th>
      <th className="p-2 text-left">Position</th>
      <th className="p-2 text-right">Größe</th>
      <th className="p-2 text-right">Kern</th>
      <th className="p-2 text-right">Frames</th>
      <th className="p-2 text-right">Geschw.</th>
      <th className="p-2 text-center">Modus</th>
      <th className="p-2 text-right">CAPE</th>
      <th className="p-2 text-right">LI</th>
      <th className="p-2 text-right">T 2m</th>
      <th className="p-2 text-right">Td 2m</th>
      <th className="p-2 text-right">Gefriergrenze</th>
      <th className="p-2 text-right">Wind 700hPa</th>
      <th className="p-2 text-right">Wolkenhöhe</th>
      <th className="p-2 text-right">⚡ &lt;10km</th>
      <th className="p-2 text-right">OF-Geschw.</th>
    </tr>
  )
}

// Einzelne Tabellenzeile — shared zwischen aktiv und inaktiv
function CellTableRow({ o, isInactive, selected, onSelect }) {
  const frames = o.total_active_frames ?? o.active_frames ?? null
  const speed  = o.speed_kmh   != null ? parseFloat(o.speed_kmh)   : null
  const dir    = o.direction_deg != null ? parseFloat(o.direction_deg) : null

  // Zeitstempel-Anzeige "SEIT" (aktiv) oder "ZULETZT" (inaktiv)
  const zeitCell = isInactive
    ? lastSeenDisplay(o)
    : (() => {
        if (!o.first_seen) return '—'
        const d = parseTs(o.first_seen)
        const m = durMin(o.first_seen)
        return `${d ? d.toLocaleTimeString('de-AT', { hour: '2-digit', minute: '2-digit' }) : '—'} (${m ?? '?'} min)`
      })()

  return (
    <tr
      className={`border-b cursor-pointer hover:bg-blue-50 ${selected === o.id ? 'bg-blue-50' : ''} ${isInactive ? 'opacity-70' : ''}`}
      onClick={() => onSelect(selected === o.id ? null : o.id)}
    >
      {/* ID mit Karten-Link und Lineage-Badge */}
      <td className="p-2 font-mono font-semibold text-blue-700">
        <button
          style={{ background: 'none', border: 'none', padding: 0, color: 'inherit', font: 'inherit', cursor: 'pointer' }}
          title="In Karte anzeigen (neues Fenster)"
          onClick={e => { e.stopPropagation(); window.open(`/map?lat=${o.lat}&lon=${o.lon}&zoom=12&cell=${o.id}`, '_blank') }}
        >
          {o.id}
        </button>
        {o.lineage === 'merged' && <span className="ml-1 text-xs px-1 rounded font-normal bg-orange-100 text-orange-700">⊕</span>}
        {o.lineage === 'split'  && <span className="ml-1 text-xs px-1 rounded font-normal bg-purple-100 text-purple-700">⊗</span>}
      </td>

      {/* SEIT / ZULETZT */}
      <td className="p-2 text-sm text-gray-600">{zeitCell}</td>

      {/* POSITION */}
      <td className="p-2 text-xs text-gray-600">
        {o.lat?.toFixed(3)}°N {o.lon?.toFixed(3)}°E
      </td>

      {/* GRÖSSE */}
      <td className="p-2 text-right"><Val v={o.size} decimals={0} zeroIsEmpty /></td>

      {/* KERN */}
      <td className="p-2 text-right"><Val v={o.core_ratio} decimals={2} zeroIsEmpty /></td>

      {/* FRAMES — P28 NEU */}
      <td className="p-2 text-right font-mono text-xs">
        {frames != null ? frames : <span className="text-gray-300">—</span>}
      </td>

      {/* GESCHWINDIGKEIT — P28 NEU */}
      <td className="p-2 text-right text-xs">
        {speed != null
          ? <>
              {speed.toFixed(0)}
              <span className="text-gray-400 text-xs ml-0.5">km/h</span>
              {dir != null && <span className="text-gray-500 text-xs ml-1">{dir.toFixed(0)}°</span>}
            </>
          : <span className="text-gray-300">—</span>
        }
      </td>

      {/* FORECAST-MODUS */}
      <td className="p-2 text-center text-xs">
        <span className={o.forecast_mode === 'ml' ? 'text-green-700 font-semibold' : 'text-gray-500'}>
          {o.forecast_mode ?? '—'}
        </span>
      </td>

      <td className="p-2 text-right"><Val v={o.cape} decimals={0} unit=" J/kg" zeroIsEmpty /></td>
      <td className="p-2 text-right"><Val v={o.arome_li} unit="°C" zeroIsEmpty /></td>
      <td className="p-2 text-right"><Val v={o.arome_t2m} unit="°C" /></td>
      <td className="p-2 text-right"><Val v={o.arome_td2m} unit="°C" /></td>
      <td className="p-2 text-right"><Val v={o.arome_fl_height} decimals={0} unit=" m" zeroIsEmpty /></td>

      {/* WIND 700 hPa */}
      <td className="p-2 text-right text-xs">
        {o.wind_speed_700hPa != null
          ? `${parseFloat(o.wind_speed_700hPa).toFixed(1)} km/h ${windDirDeg(o.wind_dir_cos, o.wind_dir_sin) ?? ''}`
          : <span className="text-gray-300">—</span>
        }
      </td>

      <td className="p-2 text-right">
        <CloudHeight height={o.cloud_top_height_msl} missing={o.cloud_height_missing} lowConfidence={o.cloud_height_low_confidence === 1} short />
      </td>
      <td className="p-2 text-right"><Val v={o.lightning_count_10km} decimals={0} zeroIsEmpty /></td>
      <td className="p-2 text-right"><Val v={o.of_speed} decimals={1} zeroIsEmpty /></td>
    </tr>
  )
}

// ---------------------------------------------------------------------------
// Hauptkomponente
// ---------------------------------------------------------------------------

export default function LiveDaten() {
  const [objects, setObjects]   = useState([])   // /api/objects (aktiv + missing<20min)
  const [history, setHistory]   = useState([])   // /api/objects/history (bis 12 h)
  const [lastTs, setLastTs]     = useState(null)
  const [loading, setLoading]   = useState(true)
  const [selected, setSelected] = useState(null)

  function load() {
    api.get('/api/objects')
      .then(data => {
        setObjects(Array.isArray(data) ? data : [])
        setLastTs(new Date().toLocaleTimeString('de-AT'))
      })
      .catch(() => {})
      .finally(() => setLoading(false))

    // History-Abfrage: inaktive Zellen der letzten 12 h (60 s Cache im Backend)
    api.get('/api/objects/history')
      .then(data => { if (Array.isArray(data)) setHistory(data) })
      .catch(() => {})
  }

  useEffect(() => {
    load()
    const t = setInterval(load, 30000)
    return () => clearInterval(t)
  }, [])

  if (loading) return <div className="text-gray-500 text-sm">Lade Live-Daten...</div>

  // Aufteilung:
  // active      — missing === 0: aktuell vom Radar erkannte Zellen
  // inactiveLive — missing > 0: noch im Tracking-Memory, aber nicht mehr sichtbar (< 20 min)
  // history     — aus gespeicherten Frame-Dateien, nicht mehr in tracking_memory (bis 12 h)
  const active       = objects.filter(o => (o.missing ?? 0) === 0)
  const inactiveLive = objects.filter(o => (o.missing ?? 0) > 0)
  const allInactive  = [...inactiveLive, ...history]
  const hasData      = active.length > 0 || allInactive.length > 0

  // Detailansicht: in beiden Listen suchen
  const sel = selected ? [...objects, ...history].find(o => o.id === selected) : null

  return (
    <div>
      {/* ── Kopfzeile ────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold">Live-Daten (API-Werte)</h1>
        <div className="flex items-center gap-3">
          {lastTs && <span className="text-xs text-gray-400">Stand: {lastTs}</span>}
          <button onClick={load} className="btn-secondary text-sm">↺ Reload</button>
        </div>
      </div>

      {!hasData ? (
        <div className="bg-gray-50 border rounded p-4 text-sm text-gray-600">
          Aktuell keine Gewitterzellen erkannt. Bei aktivem Gewitter erscheinen
          hier alle Zellen mit ihren API-Werten.
        </div>
      ) : (
        <>
          {/* ── Aktive Zellen ──────────────────────────────────────────── */}
          {active.length > 0 && (
            <div className="card mb-4 overflow-auto">
              <h2 className="text-base font-semibold mb-2">
                {active.length} aktive Zelle{active.length !== 1 ? 'n' : ''}
              </h2>
              <table className="w-full text-sm whitespace-nowrap">
                <thead><CellTableHeader isInactive={false} /></thead>
                <tbody>
                  {active.map(o => (
                    <CellTableRow
                      key={o.id}
                      o={o}
                      isInactive={false}
                      selected={selected}
                      onSelect={setSelected}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* ── Inaktive Zellen (letzte 12 h) — P28 NEU ───────────────── */}
          {allInactive.length > 0 && (
            <div className="card mb-4 overflow-auto">
              <h2 className="text-base font-semibold mb-2 text-gray-500">
                {allInactive.length} inaktive Zelle{allInactive.length !== 1 ? 'n' : ''}
                <span className="font-normal text-xs ml-2">(letzte 12 h)</span>
              </h2>
              <table className="w-full text-sm whitespace-nowrap">
                <thead><CellTableHeader isInactive={true} /></thead>
                <tbody>
                  {allInactive.map(o => (
                    <CellTableRow
                      key={o.id}
                      o={o}
                      isInactive={true}
                      selected={selected}
                      onSelect={setSelected}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* ── Detailansicht der gewählten Zelle ─────────────────────── */}
          {sel && (
            <div className="card">
              <h2 className="text-base font-semibold mb-3">
                Detail: Zelle <span className="font-mono text-blue-700">{sel.id}</span>
                {(sel.missing ?? 0) > 0 && (
                  <span className="ml-2 text-xs text-gray-400 font-normal">(inaktiv)</span>
                )}
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
                  {sel.wind_speed_700hPa?.toFixed(1)} km/h{' '}
                  {windDirDeg(sel.wind_dir_cos, sel.wind_dir_sin)}
                </Group>

                <Group label="Wolke & Blitze">
                  Wolkentop: <CloudHeight height={sel.cloud_top_height_msl} missing={sel.cloud_height_missing} lowConfidence={sel.cloud_height_low_confidence === 1} /><br />
                  Blitze &lt;10km: <Val v={sel.lightning_count_10km} decimals={0} />
                </Group>

                <Group label="Optical Flow">
                  Speed: <Val v={sel.of_speed} decimals={2} />
                  <span className="text-gray-400 text-xs ml-1">px/Frame</span><br />
                  Divergenz: <Val v={sel.of_divergence} decimals={4} /><br />
                  vx/vy: {sel.of_vx?.toFixed(2)} / {sel.of_vy?.toFixed(2)}
                  <span className="text-gray-400 text-xs ml-1">px/Frame</span>
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
                        Dauer: {m != null ? `${m} min` : '—'}
                        {sel.total_active_frames != null && (
                          <span className="text-gray-500 ml-1">
                            · {sel.total_active_frames} Frame{sel.total_active_frames !== 1 ? 's' : ''}
                          </span>
                        )}<br />
                      </>
                    )
                  })()}
                  {sel.speed_kmh != null && (
                    <>
                      Geschw.:{' '}
                      <span className="font-medium">
                        {parseFloat(sel.speed_kmh).toFixed(0)} km/h
                      </span>
                      {sel.direction_deg != null && (
                        <span className="text-gray-500 ml-1">
                          {parseFloat(sel.direction_deg).toFixed(0)}°
                        </span>
                      )}<br />
                    </>
                  )}
                  Lineage:{' '}
                  <span className={
                    sel.lineage === 'merged' ? 'text-orange-600 font-semibold' :
                    sel.lineage === 'split'  ? 'text-purple-600 font-semibold' : ''
                  }>
                    {sel.lineage === 'merged'    ? '⊕ Zusammengeführt' :
                     sel.lineage === 'split'     ? '⊗ Geteilt'         :
                     sel.lineage === 'continued' ? 'Fortgeführt'        :
                     sel.lineage === 'new'       ? 'Neu'                :
                     sel.lineage ?? '—'}
                  </span>
                  {sel.parents?.length > 0 && (
                    <div className="text-xs text-gray-500 mt-1">
                      Parent-IDs: {sel.parents.join(', ')}
                    </div>
                  )}
                </Group>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
