import React, { useEffect, useState } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import api from '../api.js'
import { formatChartTimestamp, buildIdxTimestampMap } from '../utils/chartTime.js'

export default function Accuracy() {
  const [hours, setHours] = useState(24)
  const [data, setData] = useState({ current: { horizons: [], tolerance_km: 5 }, history: [] })
  const [apiHealth, setApiHealth] = useState({ total: 0, by_service: {} })
  const [mlQuality, setMlQuality] = useState({ horizons: [], series: {} })
  const [mlHorizon, setMlHorizon] = useState(10)
  const [qualityDiagnosis, setQualityDiagnosis] = useState({ status: 'missing', important_findings: [], recommendations: [] })

  useEffect(() => {
    api.get(`/api/accuracy?hours=${hours}`).then(setData).catch(() => {})
    api.get(`/api/api_health?hours=${hours}`).then(setApiHealth).catch(() => {})
    api.get(`/api/ml_quality?hours=${hours}`).then(setMlQuality).catch(() => {})
    api.get('/api/forecast_quality_diagnosis').then(setQualityDiagnosis).catch(() => {})
  }, [hours])

  const horizons = data.current.horizons.map(h => h.horizon)
  const tolKm = data.current.tolerance_km
  const driftStatus = data.drift_status || {}
  const directionDrift = driftStatus.direction_drift_by_horizon || {}
  const speedDrift = driftStatus.speed_drift_by_horizon || {}
  const driftHorizons = Array.from(new Set([...Object.keys(directionDrift), ...Object.keys(speedDrift)]))
    .sort((a, b) => Number(a) - Number(b))
  const directionAlarm = driftStatus.direction_drift_alarm === true
  const speedAlarm = driftStatus.speed_drift_alarm === true

  const seriesKm = data.history.map((rec, i) => {
    const row = { idx: i + 1, ts: rec.timestamp_utc || null }
    horizons.forEach(h => {
      const e = rec.horizons?.find(x => x.horizon === h)
      row[`+${h}m`] = e?.mae_km
    })
    return row
  })
  const seriesHit = data.history.map((rec, i) => {
    const row = { idx: i + 1, ts: rec.timestamp_utc || null }
    horizons.forEach(h => {
      const e = rec.horizons?.find(x => x.horizon === h)
      row[`+${h}m`] = e?.hit_rate != null ? (e.hit_rate * 100) : null
    })
    return row
  })
  // B354: idx -> ts Lookup je Serie, fuer Achsen-Ticks und Tooltip-Titel.
  const seriesKmTsMap = buildIdxTimestampMap(seriesKm)
  const seriesHitTsMap = buildIdxTimestampMap(seriesHit)

  const mlPoints = mlQuality.series?.[String(mlHorizon)] || []
  const mlSeries = mlPoints.map(p => ({ idx: p.idx, ts: p.ts || null, Champion: p.champion_mae_km, Challenger: p.challenger_mae_km }))
  const mlSeriesTsMap = buildIdxTimestampMap(mlSeries)
  const mlSamplesLatest = mlPoints.length ? mlPoints[mlPoints.length - 1].challenger_samples : 0
  const runtimeKin = mlQuality.runtime_kinematic_mae_by_horizon || {}
  const lastPromotion = mlQuality.last_promotion || {}
  const promotionSources = lastPromotion.promotion_baseline_source || {}
  const mlUsageRatio = mlQuality.ml_usage_ratio ?? 0
  const mlGateReasons = mlQuality.ml_gate_reasons || {}
  const verificationCoverage = mlQuality.verification_coverage_by_horizon || {}
  // B285: ml_gate_reasons liefert jetzt {reason, allow_ml} je Horizont. Nur
  // Horizonte mit allow_ml === false gelten als tatsaechlich abgelehnt.
  // "ml_mae_better_or_equal" und "gating_disabled" sind ERLAUBTE Zustaende und
  // duerfen die Ampel nicht auf Rot setzen.
  const mlGateEntries = Object.entries(mlGateReasons)
  const mlGateReasonList = mlGateEntries.filter(([, v]) => v && v.reason)
  const mlDeniedList = mlGateEntries.filter(([, v]) => v && v.allow_ml === false)
  const mlAllowedList = mlGateEntries.filter(([, v]) => v && v.allow_ml === true)
  const mlTrafficStatus = mlUsageRatio > 0.05
    ? { label: 'ML aktiv', color: 'bg-green-100 border-green-300 text-green-900', icon: '🟢' }
    : mlDeniedList.length > 0 && mlAllowedList.length === 0
      ? { label: 'ML verworfen', color: 'bg-red-100 border-red-300 text-red-900', icon: '🔴' }
      : mlAllowedList.length > 0
        ? { label: 'ML erlaubt, wenig Traffic', color: 'bg-yellow-100 border-yellow-300 text-yellow-900', icon: '🟡' }
        : { label: 'ML shadow only', color: 'bg-yellow-100 border-yellow-300 text-yellow-900', icon: '🟡' }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Vorhersagegenauigkeit (Closed-Loop)</h1>
      <div className="card mb-4 bg-blue-50 border-blue-200 text-sm text-blue-900">
        <p className="font-semibold mb-1">📍 Closed-Loop-Verifikation: Vorhersage vs. tatsächliche Beobachtung</p>
        <p>Das System vergleicht automatisch jede Vorhersage mit dem was tatsächlich eingetroffen ist.
        Für jeden Horizont (+10 bis +60 min) wird geprüft: War die vorhergesagte Position
        innerhalb der Toleranz von der tatsächlichen Zellposition?</p>
      </div>

      <div className="card mb-4">
        <label className="label">Zeitraum</label>
        <select className="input" value={hours} onChange={e => setHours(parseInt(e.target.value))}>
          <option value="1">1 Stunde</option>
          <option value="6">6 Stunden</option>
          <option value="24">24 Stunden</option>
          <option value="168">7 Tage</option>
          <option value="720">30 Tage</option>
        </select>
        <div className="text-sm text-gray-500 mt-2">
          Treffer-Toleranz: <b>{tolKm} km</b> (siehe config.VERIFICATION_TOLERANCE_KM)
        </div>
      </div>


      <div className="card mb-4">
        <h3 className="text-lg font-medium mb-2">Automatische Forecast-Qualitätsdiagnose</h3>
        <div className="text-sm mb-2">
          <span className="font-semibold">Zeitpunkt:</span> {qualityDiagnosis.checked_at_utc || qualityDiagnosis.timestamp_utc || '—'}
          <span className="font-semibold ml-4">Status:</span> {qualityDiagnosis.status || 'missing'}
        </div>
        <div className="grid md:grid-cols-2 gap-4 text-sm">
          <div>
            <div className="font-semibold mb-1">Wichtigste Findings</div>
            {(qualityDiagnosis.important_findings || []).length ? (
              <ul className="list-disc ml-5">
                {(qualityDiagnosis.important_findings || []).slice(0, 5).map((item, idx) => <li key={idx}>{item}</li>)}
              </ul>
            ) : <div className="text-gray-500">Keine Findings vorhanden.</div>}
          </div>
          <div>
            <div className="font-semibold mb-1">Wichtigste Empfehlungen</div>
            {(qualityDiagnosis.recommendations || []).length ? (
              <ul className="list-disc ml-5">
                {(qualityDiagnosis.recommendations || []).slice(0, 5).map((item, idx) => <li key={idx}>{item}</li>)}
              </ul>
            ) : <div className="text-gray-500">Keine Empfehlungen vorhanden.</div>}
          </div>
        </div>
      </div>

      <div className="card mb-4">
        <h3 className="text-lg font-medium mb-2">Bias je Horizont</h3>
        <p className="text-xs text-gray-500 mb-2">
          Signierter mittlerer Forecast-Versatz aus der Qualitätsdiagnose. Positive dLon-Werte bedeuten: tatsächliche Zelle liegt im Mittel östlicher als vorhergesagt; positive dLat-Werte nördlicher.
        </p>
        <table className="w-full text-sm">
          <thead><tr className="border-b text-xs">
            <th className="text-left p-1">Horizont</th>
            <th className="text-left p-1">mean_dlon_deg</th>
            <th className="text-left p-1">mean_dlat_deg</th>
            <th className="text-left p-1">mean_speed_error_kmh</th>
            <th className="text-left p-1">mean_direction_error_deg</th>
            <th className="text-left p-1">sample_count</th>
          </tr></thead>
          <tbody>
            {Object.entries(qualityDiagnosis.bias_by_horizon || {}).map(([h, b]) => (
              <tr key={h} className="border-b">
                <td className="p-1">+{h} min</td>
                <td className="p-1">{b.mean_dlon_deg?.toFixed?.(6) ?? '—'}</td>
                <td className="p-1">{b.mean_dlat_deg?.toFixed?.(6) ?? '—'}</td>
                <td className="p-1">{b.mean_speed_error_kmh?.toFixed?.(3) ?? '—'}</td>
                <td className="p-1">{b.mean_direction_error_deg?.toFixed?.(3) ?? '—'}</td>
                <td className="p-1">{b.sample_count ?? '—'}</td>
              </tr>
            ))}
            {!Object.keys(qualityDiagnosis.bias_by_horizon || {}).length && (
              <tr><td className="p-1 text-gray-500" colSpan="6">Keine Bias-Daten vorhanden.</td></tr>
            )}
          </tbody>
        </table>
      </div>


      <div className="card mb-4">
        <h3 className="text-lg font-medium mb-2">Richtungs-/Geschwindigkeits-Drift</h3>
        <p className="text-xs text-gray-500 mb-2">
          Eigenständige Kurzhorizont-Prüfung der Zugbahn: Rot, wenn der p90-Richtungs- oder p90-Geschwindigkeitsfehler bei ausreichenden Samples über dem konfigurierten Schwellwert liegt.
        </p>
        <div className="grid md:grid-cols-2 gap-3 mb-3 text-sm">
          <div className={`rounded border p-3 ${directionAlarm ? 'bg-red-100 border-red-300 text-red-900' : 'bg-green-100 border-green-300 text-green-900'}`}>
            <div className="font-semibold">{directionAlarm ? '🔴 Richtungs-Drift' : '🟢 Richtung unauffällig'}</div>
            <div>p90-Schwelle: {Object.values(directionDrift)[0]?.threshold_deg ?? '—'}°</div>
          </div>
          <div className={`rounded border p-3 ${speedAlarm ? 'bg-red-100 border-red-300 text-red-900' : 'bg-green-100 border-green-300 text-green-900'}`}>
            <div className="font-semibold">{speedAlarm ? '🔴 Geschwindigkeits-Drift' : '🟢 Geschwindigkeit unauffällig'}</div>
            <div>p90-Schwelle: {Object.values(speedDrift)[0]?.threshold_kmh ?? '—'} km/h</div>
          </div>
        </div>
        <table className="w-full text-sm">
          <thead><tr className="border-b text-xs">
            <th className="text-left p-1">Horizont</th>
            <th className="text-left p-1">Richtung Median</th>
            <th className="text-left p-1">Richtung p90</th>
            <th className="text-left p-1">Richtung Samples</th>
            <th className="text-left p-1">Speed Median</th>
            <th className="text-left p-1">Speed p90</th>
            <th className="text-left p-1">Speed Samples</th>
          </tr></thead>
          <tbody>
            {driftHorizons.map(h => {
              const dir = directionDrift[h] || {}
              const spd = speedDrift[h] || {}
              return (
                <tr key={h} className="border-b">
                  <td className="p-1">+{h} min</td>
                  <td className="p-1">{dir.median_deg?.toFixed?.(1) ?? '—'}°</td>
                  <td className="p-1">{dir.p90_deg?.toFixed?.(1) ?? '—'}°</td>
                  <td className="p-1">{dir.samples ?? '—'}</td>
                  <td className="p-1">{spd.median_kmh?.toFixed?.(1) ?? '—'} km/h</td>
                  <td className="p-1">{spd.p90_kmh?.toFixed?.(1) ?? '—'} km/h</td>
                  <td className="p-1">{spd.samples ?? '—'}</td>
                </tr>
              )
            })}
            {!driftHorizons.length && (
              <tr><td className="p-1 text-gray-500" colSpan="7">Keine Richtungs-/Geschwindigkeits-Drift-Daten vorhanden.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="card mb-4">
        <h3 className="text-lg font-medium mb-2">Aktuelle Auswertung (letzte {hours} h)</h3>
        <table className="w-full text-sm">
          <thead><tr className="border-b text-xs">
            <th className="text-left p-1" title="Wie viele Minuten in die Zukunft vorhergesagt wird">Horizont ⓘ</th>
            <th className="text-left p-1" title="Gesamtzahl ausgewerteter Vorhersagen in diesem Zeitraum">Samples ⓘ</th>
            <th className="text-left p-1" title="Vorhersagen bei denen die echte Zelle innerhalb der Toleranz gefunden wurde">Hits ⓘ</th>
            <th className="text-left p-1" title="Keine passende Zelle innerhalb 25 km gefunden — Zelle verschwunden oder stark abgewichen">Missed ⓘ</th>
            <th className="text-left p-1" title="Hits ÷ verifizierte Samples. Hohe Rate = präzise Vorhersage. Basis: Toleranz 5 km">Hit-Rate ⓘ</th>
            <th className="text-left p-1" title="Mittlerer absoluter Abstand zwischen vorhergesagter und tatsächlicher Position in km">MAE (km) ⓘ</th>
            <th className="text-left p-1" title="Wurzel des mittleren quadratischen Fehlers — empfindlicher für große Ausreißer als MAE">RMSE (km) ⓘ</th>
            <th className="text-left p-1" title="MAE in Bildpixeln des upskalierten Radarbildes (1 px ≈ 0,5 km im Original)">MAE (px) ⓘ</th>
          </tr></thead>
          <tbody>
            {data.current.horizons.map(h => (
              <tr key={h.horizon} className="border-b">
                <td className="p-1">+{h.horizon} min</td>
                <td className="p-1">{h.samples}</td>
                <td className="p-1">{h.hits}</td>
                <td className="p-1">{h.missed}</td>
                <td className="p-1">{h.hit_rate != null ? (h.hit_rate * 100).toFixed(1) + '%' : '—'}</td>
                <td className="p-1">{h.mae_km?.toFixed?.(2) ?? '—'}</td>
                <td className="p-1">{h.rmse_km?.toFixed?.(2) ?? '—'}</td>
                <td className="p-1">{h.mae_px?.toFixed?.(2) ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card mb-4">
        <h3 className="text-lg font-medium mb-2">MAE (km) — Verlauf</h3>
        <p className="text-xs text-gray-500 mb-2">
          Mittlerer absoluter Positionsfehler in km über die Zeit, getrennt nach Horizont.
          Jeder Punkt = eine Genauigkeits-Messung (stündlich durch den Scheduler).
          <b> Niedrigere Werte = bessere Vorhersage.</b>
          Kürzere Horizonte (+10 min) haben typischerweise geringeren Fehler als längere (+60 min).
        </p>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={seriesKm}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis
              dataKey="idx"
              type="category"
              tickFormatter={i => formatChartTimestamp(seriesKmTsMap.get(i)) || ('#' + i)}
              label={{ value: 'Messzeitpunkt', position: 'insideBottom', offset: -5 }}
            />
            <YAxis label={{ value: 'km', angle: -90, position: 'insideLeft' }} />
            <Tooltip labelFormatter={i => 'Messzeitpunkt: ' + (formatChartTimestamp(seriesKmTsMap.get(i)) || ('#' + i))} />
            <Legend />
            {horizons.map(h => <Line key={h} type="monotone" dataKey={`+${h}m`} dot={{ r: 2 }} connectNulls />)}
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="card mb-4">
        <h3 className="text-lg font-medium mb-2">Hit-Rate (%) — Verlauf</h3>
        <p className="text-xs text-gray-500 mb-2">
          Anteil der Vorhersagen bei denen die tatsächliche Zelle innerhalb <b>5 km Toleranz</b>
          gefunden wurde (config: VERIFICATION_TOLERANCE_KM).
          <b> 100 % = alle Vorhersagen korrekt innerhalb der Toleranz.</b>
          Hit-Rate kann sinken wenn Zellen sehr schnell wachsen/verschwinden
          oder das Modell noch wenig Trainingsdaten hat.
        </p>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={seriesHit}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis
              dataKey="idx"
              type="category"
              tickFormatter={i => formatChartTimestamp(seriesHitTsMap.get(i)) || ('#' + i)}
              label={{ value: 'Messzeitpunkt', position: 'insideBottom', offset: -5 }}
            />
            <YAxis domain={[0, 100]} label={{ value: '%', angle: -90, position: 'insideLeft' }} />
            <Tooltip labelFormatter={i => 'Messzeitpunkt: ' + (formatChartTimestamp(seriesHitTsMap.get(i)) || ('#' + i))} />
            <Legend />
            {horizons.map(h => <Line key={h} type="monotone" dataKey={`+${h}m`} dot={{ r: 2 }} connectNulls />)}
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="card mb-4">
        <h3 className="text-lg font-medium mb-2">ML-Lernfortschritt — Champion vs. Challenger (MAE km)</h3>
        <p className="text-xs text-gray-500 mb-2">
          Vergleich des ausgelieferten <b>Champion</b> (Kinematik) mit dem im Schatten
          mitlaufenden <b>Challenger</b> (ML) für den gewählten Horizont über die Zeit.
          Liegt der Challenger dauerhaft unter dem Champion, aktiviert das Gate ML automatisch.
          <b> Niedriger = besser.</b>
        </p>
        <div className="mb-2">
          <label className="label">Horizont</label>
          <select className="input" value={mlHorizon} onChange={e => setMlHorizon(parseInt(e.target.value))}>
            {(mlQuality.horizons || []).map(h => <option key={h} value={h}>+{h} min</option>)}
          </select>
          <span className="text-xs text-gray-500 ml-2">Challenger-Samples (zuletzt): <b>{mlSamplesLatest}</b></span>
        </div>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={mlSeries}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis
              dataKey="idx"
              type="category"
              tickFormatter={i => formatChartTimestamp(mlSeriesTsMap.get(i)) || ('#' + i)}
              label={{ value: 'Messzeitpunkt', position: 'insideBottom', offset: -5 }}
            />
            <YAxis label={{ value: 'km', angle: -90, position: 'insideLeft' }} />
            <Tooltip labelFormatter={i => 'Messzeitpunkt: ' + (formatChartTimestamp(mlSeriesTsMap.get(i)) || ('#' + i))} />
            <Legend />
            <Line type="monotone" dataKey="Champion" stroke="#2563eb" dot={{ r: 2 }} connectNulls />
            <Line type="monotone" dataKey="Challenger" stroke="#ea580c" dot={{ r: 2 }} connectNulls />
          </LineChart>
        </ResponsiveContainer>
        <div className="mt-4 border-t pt-3">
          <h4 className="font-medium mb-2">Runtime-Gate / Promotion-Baseline (B277)</h4>
          <div className={`mb-3 rounded border p-3 text-sm ${mlTrafficStatus.color}`}>
            <div className="font-semibold">{mlTrafficStatus.icon} {mlTrafficStatus.label}</div>
            <div>ML-Nutzungsanteil im Zeitraum: <b>{(mlUsageRatio * 100).toFixed(1)}%</b></div>
            {mlGateReasonList.length ? (
              <div className="mt-1 text-xs">Gate-Gründe: {mlGateReasonList.map(([h, v]) => `+${h} min: ${v.reason} (${v.allow_ml ? 'erlaubt' : 'abgelehnt'})`).join(' · ')}</div>
            ) : (
              <div className="mt-1 text-xs">Keine Runtime-Gate-Gründe gemeldet.</div>
            )}
          </div>
          <div className="text-sm mb-2">
            <span className="font-semibold">Letzter Entscheid:</span> {lastPromotion.promotion_decision || '—'}
            <span className="font-semibold ml-4">Grund:</span> {lastPromotion.promotion_reject_reason || '—'}
          </div>
          <table className="w-full text-sm">
            <thead><tr className="border-b text-xs">
              <th className="text-left p-1">Horizont</th>
              <th className="text-left p-1">Runtime-Kinematik MAE</th>
              <th className="text-left p-1">Samples</th>
              <th className="text-left p-1">Promotion-Baseline-Quelle</th>
              <th className="text-left p-1">Coverage</th>
            </tr></thead>
            <tbody>
              {(mlQuality.horizons || []).map(h => {
                const hk = String(h)
                const kin = runtimeKin[hk] || {}
                return (
                  <tr key={hk} className="border-b">
                    <td className="p-1">+{h} min</td>
                    <td className="p-1">{kin.kinematic_mae?.toFixed?.(2) ?? '—'}</td>
                    <td className="p-1">{kin.kinematic_samples ?? '—'}</td>
                    <td className="p-1">{promotionSources[hk] || '—'}</td>
                    <td className="p-1">{verificationCoverage[hk] != null ? `${(verificationCoverage[hk] * 100).toFixed(1)}%` : '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h3 className="text-lg font-medium mb-2">API-Health (letzte {hours} h)</h3>
        {apiHealth.total === 0 ? (
          <div className="text-sm text-green-700">Keine API-Fehler im Zeitraum.</div>
        ) : (
          <table className="w-full text-sm">
            <thead><tr className="border-b">
              <th className="text-left p-1">Service</th>
              <th className="text-left p-1">Fehler</th>
              <th className="text-left p-1">Fallback</th>
              <th className="text-left p-1">Häufigster Grund</th>
              <th className="text-left p-1">Letzter Fehler</th>
            </tr></thead>
            <tbody>
              {Object.entries(apiHealth.by_service || {}).map(([svc, info]) => {
                const topReason = Object.entries(info.reasons || {})
                  .sort((a, b) => b[1] - a[1])[0]
                return (
                  <tr key={svc} className="border-b">
                    <td className="p-1">{svc}</td>
                    <td className="p-1">{info.count}</td>
                    <td className="p-1">{info.fallback_count}</td>
                    <td className="p-1">{topReason ? `${topReason[0]} (${topReason[1]})` : '—'}</td>
                    <td className="p-1 text-xs">{info.last_ts || '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
