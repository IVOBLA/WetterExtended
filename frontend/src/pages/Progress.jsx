import React, { useEffect, useState } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, BarChart, Bar } from 'recharts'
import api from '../api.js'

const STATUS_TEXT = {
  promoted: 'Wurde bei diesem Trainingslauf aktiviert. Das bedeutet nicht automatisch, dass es heute noch aktiv ist.',
  rejected: 'Nicht aktiviert: kein ausreichender Vorteil gegenüber dem bisher aktiven Modell.',
  rejected_below_kinematic_baseline: 'Nicht aktiviert: ML war schlechter als die kinematische Baseline.',
  rejected_invalid_holdout: 'Nicht aktiviert: Holdout-Prüfung lieferte ungültige Werte.',
  cold_start_promoted_low_confidence: 'Erstes ML-Modell aktiviert, aber mit niedriger Vertrauensstufe wegen weniger Vergleichssamples.',
  fallback_kinematic: 'Kinematischer Fallback aktiv: kein nutzbares ML-Modell verfügbar.',
  insufficient_samples: 'Zu wenige Samples für eine belastbare Aktivierung oder Bewertung.',
  cold_start_insufficient_samples: 'Zu wenige Samples für die Erstaktivierung eines ML-Modells.',
  rejected_low_samples: 'Nicht aktiviert: zu wenige aktuelle Vergleichssamples.',
  rejected_low_samples_per_horizon: 'Nicht aktiviert: mindestens ein Horizont hat zu wenige gepaarte Vergleichssamples für eine belastbare Bewertung, auch wenn die Gesamtsumme ausreicht.',
  rejected_incompatible: 'Nicht aktiviert: Modell passt nicht zur aktuellen Horizonte-/Feature-Konfiguration.',
  cold_start_rejected_invalid_model: 'Nicht aktiviert: Modellartefakte fehlen, sind inkompatibel oder ungültig.',
  no_data: 'Kein nutzbarer Datensatz für diesen Trainingslauf vorhanden.',
}

function fmt(value, digits = 3) {
  return Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '—'
}

function statusReason(v) {
  return v.status_reason || v.validation?.status_reason || STATUS_TEXT[v.status || v.validation?.status] || 'Kein Statusgrund vorhanden.'
}

function isLegacy(v) {
  return v.validation?.legacy_incomparable !== false
}

export default function Progress() {
  const [progress, setProgress] = useState({ versions: [], active_version: null, active_meta: null })
  const [loaded, setLoaded] = useState(false)
  const [loadError, setLoadError] = useState(null)
  const [fcStats, setFcStats] = useState(null)

  function loadProgress() {
    setLoadError(null)
    setLoaded(false)
    api.get('/api/forecast_stats?hours=24').then(s => setFcStats(s)).catch(() => setFcStats(null))
    api.get('/api/progress')
      .then(d => { setProgress(d); setLoaded(true) })
      .catch(err => { setLoadError(err?.message || 'Laden fehlgeschlagen'); setLoaded(true) })
  }

  useEffect(() => { loadProgress() }, [])

  const versions = progress.versions || []
  const activeMeta = progress.active_meta
  const activeValidation = activeMeta?.validation || {}
  const activeIsLegacy = isLegacy(activeMeta || {})
  const mlActive = fcStats ? (fcStats.ml_blocked_reason == null) : null
  const blockedReason = fcStats?.ml_blocked_reason || null
  const horizons = activeMeta?.horizons_trained?.length
    ? activeMeta.horizons_trained
    : (versions.find(v => v.horizons_trained?.length)?.horizons_trained || [10, 20, 30, 40, 60])
  const mlBetterThanKin = !activeIsLegacy && Number.isFinite(Number(activeValidation.mae_km_new)) && Number.isFinite(Number(activeValidation.kin_baseline_mae))
    ? Number(activeValidation.mae_km_new) < Number(activeValidation.kin_baseline_mae)
    : null

  // P102: Differenz-/Zeitreihendiagramme duerfen laut Findings-Report keine
  // Alt-Versionen (legacy_incomparable, vor B492/B493 ohne echte km-Metrik)
  // enthalten — deren Werte wuerden Pixel- und km-Groessen unbemerkt mischen.
  const comparableVersions = versions.filter(v => !isLegacy(v))
  const legacyCount = versions.length - comparableVersions.length

  const lstmSeries = versions.map((v, i) => ({ idx: i + 1, version: v.version_id || v.version, val_loss: v.lstm?.val_loss }))
  const maeSeries = comparableVersions.map((v, i) => {
    const ml = v.validation?.mae_by_horizon_new_km || {}
    const kin = v.validation?.kin_baseline_by_horizon || {}
    const row = { idx: i + 1, version: v.version_id || v.version }
    horizons.forEach(hz => { row[`ML +${hz}m`] = ml[String(hz)]; row[`Kinematik +${hz}m`] = kin[String(hz)] })
    return row
  })
  const diffSeries = comparableVersions.map((v, i) => {
    const ml = v.validation?.mae_by_horizon_new_km || {}
    const kin = v.validation?.kin_baseline_by_horizon || {}
    const row = { idx: i + 1, version: v.version_id || v.version }
    horizons.forEach(hz => {
      const a = Number(ml[String(hz)]); const b = Number(kin[String(hz)])
      row[`Δ +${hz}m`] = Number.isFinite(a) && Number.isFinite(b) ? a - b : null
    })
    return row
  })
  const aucSeries = versions.map((v, i) => ({ idx: i + 1, auc: v.intensification?.auc }))

  function Chart({ title, data, lines }) {
    const colors = ['#2563eb', '#16a34a', '#dc2626', '#9333ea', '#ea580c', '#0891b2', '#4b5563', '#84cc16', '#f43f5e', '#0f766e']
    return <div className="card mb-4"><h3 className="text-lg font-medium mb-2">{title}</h3><ResponsiveContainer width="100%" height={270}><LineChart data={data}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="idx" /><YAxis /><Tooltip /><Legend />{lines.map((l, idx) => <Line key={l} type="monotone" dataKey={l} stroke={colors[idx % colors.length]} dot={{ r: 3 }} connectNulls />)}</LineChart></ResponsiveContainer></div>
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Lernfortschritt</h1>

      <section className="card mb-4"><h2 className="text-lg font-semibold">A. Offline-Training</h2><p>Modellversion, Train-/Validation-/Holdout-Samples, Feature-Schema, km-Metriken, Status und Ablehnungsgrund.</p></section>
      <section className="card mb-4"><h2 className="text-lg font-semibold">B. Runtime-Champion je Horizont</h2>{Object.entries(progress.runtime_champion_by_horizon || {}).map(([h, c]) => <div key={h}>+{h} min: <b>{c.mode}</b> · {c.model_version || c.reason || '—'}</div>)}</section>
      <section className="card mb-4"><h2 className="text-lg font-semibold">C. Aktives Shadow-Experiment</h2><pre className="text-xs whitespace-pre-wrap">{progress.active_shadow_experiment ? JSON.stringify(progress.active_shadow_experiment, null, 2) : 'Kein aktives Shadow-Experiment'}</pre></section>
      <section className="card mb-4"><h2 className="text-lg font-semibold">D. Experimentergebnis</h2><p>Incumbent vs Candidate · Delta · CI · Richtungs-/Speed-Fehler · Hit-Rate · Coverage · Promotion/Plateau/Rejected/Invalid</p></section>
      <section className="card mb-4"><h2 className="text-lg font-semibold">E. Verbesserungsverlauf</h2><p>7 Tage · 30 Tage · 90 Tage · Abstand zum Qualitätsziel · letzte echte Verbesserung · Plateau-/Stallstatus</p></section>

      <div className="card mb-4 bg-blue-50 border-blue-200 text-sm text-blue-900">
        <p className="font-semibold mb-1">📊 Diese Seite zeigt Trainingsqualität, aktive Version und Vergleich zur kinematischen Baseline — alle Fehlerwerte in km (Haversine-Distanz, seit B492/B493).</p>
        <p><b>promoted</b> = wurde bei diesem Trainingslauf aktiviert. <b>active</b> = aktuell über <code>train_data/models/current</code> genutztes Modell.</p>
      </div>

      {legacyCount > 0 && (
        <div className="card mb-4 bg-gray-50 border border-gray-300 text-xs text-gray-700">
          ℹ️ {legacyCount} Version(en) vor der km-Umstellung (B492/B493) besitzen keine
          vergleichbare km-Metrik und werden in den Diagrammen unten ausgeblendet, um
          Pixel- und km-Werte nicht unbemerkt zu vermischen. Sie erscheinen weiterhin
          in der Tabelle „Versionen“, klar als „nicht vergleichbar“ markiert.
        </div>
      )}

      <div className={`card mb-4 text-sm border ${mlActive ? 'bg-green-50 border-green-300 text-green-900' : 'bg-amber-50 border-amber-300 text-amber-900'}`}>
        <h2 className="font-semibold mb-2">Aktiver Forecast-Status</h2>
        <div className="grid md:grid-cols-2 gap-2">
          <div><b>Forecast-Modus:</b> {mlActive === null ? 'unbekannt' : mlActive ? '🤖 ML aktiv' : '📐 Kinematik aktiv'}</div>
          <div><b>Aktive Modellversion:</b> {progress.active_version || '—'}</div>
          <div><b>Aktiver Timestamp:</b> {activeMeta?.timestamp_utc || '—'}</div>
          <div><b>Aktiver MAE (km):</b> {activeIsLegacy ? 'nicht vergleichbar (Alt-Version vor B492)' : fmt(activeValidation.mae_km_new)}</div>
          <div><b>Aktive kinematische Baseline (km):</b> {fmt(activeValidation.kin_baseline_mae)}</div>
          <div><b>ML besser als Kinematik:</b> {mlBetterThanKin === null ? '—' : mlBetterThanKin ? 'ja' : 'nein'}</div>
        </div>
        {!mlActive && blockedReason && <p className="mt-2 text-xs"><b>Grund:</b> {blockedReason}</p>}
      </div>

      {loaded && loadError && <div className="card mb-4 bg-red-50 border border-red-300 text-red-900 text-sm"><p className="font-semibold">⚠️ Lernfortschritt konnte nicht geladen werden</p><p>{loadError}</p><button onClick={loadProgress} className="mt-2 px-3 py-1 rounded bg-red-600 text-white text-xs hover:bg-red-700">Erneut versuchen</button></div>}

      {loaded && !loadError && versions.length === 0 && <div className="card mb-4 bg-amber-50 border border-amber-300 text-amber-900 text-sm"><p className="font-semibold mb-2">⏳ Noch kein Trainings-Lauf abgeschlossen</p><p>Das System sammelt automatisch Trainingsdaten. Die Grafiken erscheinen nach dem ersten Training.</p></div>}

      {versions.length > 0 && <>
        <Chart title="LSTM val_loss (Validierungsverlust)" data={lstmSeries} lines={['val_loss']} />
        <Chart title="LightGBM MAE und kinematische Baseline pro Horizont (km)" data={maeSeries} lines={horizons.flatMap(h => [`ML +${h}m`, `Kinematik +${h}m`])} />
        <Chart title="Differenz ML - Kinematik pro Horizont (km)" data={diffSeries} lines={horizons.map(h => `Δ +${h}m`)} />
        <div className="text-xs text-gray-500 -mt-2 mb-4 px-1">Positive Differenz = ML schlechter als Kinematik. Negative Differenz = ML besser als Kinematik. Nur km-vergleichbare Versionen (siehe Hinweis oben).</div>
        <Chart title="Intensification AUC" data={aucSeries} lines={['auc']} />

        <div className="card mb-4">
          <h3 className="text-lg font-medium mb-2">Horizontvergleich der aktiven Version (km)</h3>
          {activeIsLegacy
            ? <p className="text-sm text-gray-600">Die aktive Version stammt von vor B492/B493 und besitzt keine km-Metrik pro Horizont.</p>
            : <>
                <ResponsiveContainer width="100%" height={260}><BarChart data={horizons.map(h => {
                  const ml = Number(activeValidation.mae_by_horizon_new_km?.[String(h)]); const kin = Number(activeValidation.kin_baseline_by_horizon?.[String(h)])
                  return { horizon: `+${h}m`, 'ML MAE (km)': Number.isFinite(ml) ? ml : null, 'Kinematik MAE (km)': Number.isFinite(kin) ? kin : null, 'ML - Kinematik': Number.isFinite(ml) && Number.isFinite(kin) ? ml - kin : null }
                })}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="horizon" /><YAxis /><Tooltip /><Legend /><Bar dataKey="ML MAE (km)" fill="#2563eb" /><Bar dataKey="Kinematik MAE (km)" fill="#16a34a" /><Bar dataKey="ML - Kinematik" fill="#dc2626" /></BarChart></ResponsiveContainer>
                <p className="text-xs text-gray-500 mt-2">Gepaarte Samples je Horizont: {horizons.map(h => `+${h}m: ${activeValidation.paired_samples_by_horizon?.[String(h)] ?? '—'}`).join(' · ')}</p>
              </>}
        </div>

        <div className="card overflow-x-auto">
          <h3 className="text-lg font-medium mb-2">Versionen</h3>
          <p className="text-xs text-gray-500 mb-2"><b>Aktiv</b> wird ausschließlich aus <code>current</code> ermittelt. Eine ältere promoted-Zeile kann daher inaktiv sein. <b>Vergleichbar</b> = km-Metrik seit B492/B493 vorhanden.</p>
          <table className="w-full text-sm">
            <thead><tr className="border-b"><th className="text-left p-1">Version</th><th className="text-left p-1">Aktiv</th><th className="text-left p-1">Vergleichbar</th><th className="text-left p-1">MAE Kandidat (km)</th><th className="text-left p-1">MAE bisher aktiv/alt (km)</th><th className="text-left p-1">Kinematik-MAE (km)</th><th className="text-left p-1">ML-Vorteil gegenüber Kinematik (km)</th><th className="text-left p-1">Status</th><th className="text-left p-1">Entscheidungsgrund</th></tr></thead>
            <tbody>{versions.map((v, i) => {
              const legacy = isLegacy(v)
              const mae = Number(v.validation?.mae_km_new); const kin = Number(v.validation?.kin_baseline_mae)
              const advantage = !legacy && Number.isFinite(mae) && Number.isFinite(kin) ? kin - mae : null
              return <tr key={v.version_id || i} className={`border-b ${v.is_active ? 'bg-green-50' : ''} ${legacy ? 'opacity-60' : ''}`}><td className="p-1">{v.version_id || v.version || v.timestamp_utc}</td><td className="p-1 font-semibold">{v.is_active ? 'ja' : 'nein'}</td><td className="p-1">{legacy ? 'nein (Alt)' : 'ja'}</td><td className="p-1">{legacy ? '—' : fmt(v.validation?.mae_km_new)}</td><td className="p-1">{legacy ? '—' : fmt(v.validation?.mae_km_old)}</td><td className="p-1">{fmt(v.validation?.kin_baseline_mae)}</td><td className={`p-1 ${advantage > 0 ? 'text-green-700' : advantage < 0 ? 'text-red-700' : ''}`}>{advantage === null ? '—' : fmt(advantage)}</td><td className="p-1">{v.status || v.validation?.status || '—'}</td><td className="p-1">{statusReason(v)}</td></tr>
            })}</tbody>
          </table>
        </div>
      </>}
    </div>
  )
}
