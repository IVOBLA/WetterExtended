import React, { useEffect, useState } from 'react'
import api from '../api.js'

export default function Training() {
  const [rebuild, setRebuild] = useState(60)
  const [s, setS] = useState({
    retrain_interval_hours:   6,
    retrain_cron_hour:        3,
    retrain_cron_minute:      0,
    convlstm_cron_day_of_week: 'mon',
    convlstm_cron_hour:       2,
    convlstm_cron_minute:     0,
  })
  const [msg, setMsg]                     = useState('')
  const [localTraining, setLocalTraining] = useState(true)
  const [readiness, setReadiness]         = useState(null)

  useEffect(() => {
    // B99: Countdown — Live-Refresh alle 60 s (sinkt sichtbar bei Sturmereignissen)
    const fetchReadiness = () =>
      api.get('/api/training_readiness').then(setReadiness).catch(() => {})
    fetchReadiness()
    const _rdTimer = setInterval(fetchReadiness, 60_000)

    api.get('/api/training')
      .then(d => {
        if (d.DATASET_REBUILD_INTERVAL_MIN != null) setRebuild(d.DATASET_REBUILD_INTERVAL_MIN)
        if (d.TRAINING_SCHEDULE) setS(prev => ({ ...prev, ...d.TRAINING_SCHEDULE }))
      })
      .catch(() => {})

    api.get('/api/local_training')
      .then(d => setLocalTraining(d.local_training !== false))
      .catch(() => {})

    return () => clearInterval(_rdTimer)  // B99: Timer beim Unmount stoppen
  }, [])

  const save = async () => {
    try {
      await api.post('/api/training', {
        TRAINING_SCHEDULE:             s,
        DATASET_REBUILD_INTERVAL_MIN:  rebuild,
      })
      setMsg('Gespeichert. Bitte Service neu starten: sudo systemctl restart wetterprojekt-scheduler')
    } catch (e) {
      setMsg('Fehler: ' + e.message)
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Trainings-Schedule</h1>

      {!localTraining && (
        <div className="bg-yellow-100 border border-yellow-400 text-yellow-900 p-3 rounded mb-4">
          <strong>Lokales Training deaktiviert</strong> — Modelle werden extern
          auf dem Trainer-Rechner berechnet und per rsync synchronisiert.
          Die Einstellungen unten gelten für den Trainer-Rechner.
        </div>
      )}

      {msg && (
        <div className="bg-blue-100 border border-blue-300 text-blue-900 p-2 rounded mb-3 text-sm">
          {msg}
        </div>
      )}

      {/* B99: Trainingsbereitschaft — Live-Countdown */}
      {readiness && (
        <div className="card mb-4">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <h2 className="text-lg font-semibold">Trainingsbereitschaft</h2>
            <span style={{ fontSize: 11, color: '#9ca3af' }}>↺ alle 60 s</span>
          </div>

          {/* Countdown-Zahl */}
          <div style={{ textAlign: 'center', padding: '8px 0 20px' }}>
            {readiness.all_ready ? (
              <>
                <div style={{ fontSize: 72, lineHeight: 1 }}>✅</div>
                <div style={{ fontWeight: 700, fontSize: 18, color: '#16a34a', marginTop: 6 }}>
                  Bereit für Trainingslauf (Dataset-Schwelle erreicht)!
                </div>
                <div style={{ fontSize: 12, color: '#6b7280', marginTop: 4 }}>
                  {readiness.current_sequences} Sequenzen gesammelt
                </div>
              </>
            ) : (
              <>
                <div style={{
                  fontSize: 88, fontWeight: 900, lineHeight: 1, letterSpacing: '-2px',
                  fontVariantNumeric: 'tabular-nums',
                  color: readiness.current_sequences === 0 ? '#d1d5db' : '#f59e0b',
                }}>
                  {readiness.lstm.missing}
                </div>
                <div style={{ fontWeight: 600, fontSize: 14, color: '#92400e', marginTop: 6 }}>
                  Sequenz{readiness.lstm.missing !== 1 ? 'en' : ''} noch benötigt
                </div>
                <div style={{ fontSize: 12, color: '#6b7280', marginTop: 2 }}>
                  {readiness.current_sequences} von {readiness.lstm.required} gesammelt
                </div>
              </>
            )}
          </div>

          {/* Fortschrittsbalken */}
          <div style={{ background: '#e5e7eb', borderRadius: 8, height: 12, marginBottom: 16, overflow: 'hidden' }}>
            <div style={{
              height: '100%', borderRadius: 8,
              background: readiness.all_ready ? '#16a34a' : '#f59e0b',
              width: `${Math.min(100, Math.round(readiness.current_sequences / readiness.lstm.required * 100))}%`,
              transition: 'width 0.6s ease',
            }} />
          </div>

          {/* Modell-Chips */}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
            {[
              { label: 'LSTM + LightGBM', r: readiness.lstm },
              { label: 'LightGBM (solo)',  r: readiness.lgbm },
            ].map(({ label, r }) => (
              <div key={label} style={{
                flex: 1, minWidth: 130,
                background: r.ready ? '#f0fdf4' : '#fffbeb',
                border: `1px solid ${r.ready ? '#86efac' : '#fcd34d'}`,
                borderRadius: 8, padding: '8px 12px',
              }}>
                <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 2 }}>{label}</div>
                {r.ready
                  ? <span style={{ color: '#16a34a', fontWeight: 700, fontSize: 13 }}>✅ bereit ({r.required} erreicht)</span>
                  : <span style={{ color: '#92400e', fontWeight: 600, fontSize: 13 }}>⏳ noch {r.missing} fehlen</span>
                }
              </div>
            ))}
          </div>

          {readiness.inference && (
            <div style={{
              border: '1px solid #e5e7eb', borderRadius: 8, padding: '10px 12px',
              marginBottom: 12, background: readiness.runtime_status?.runtime_mode === 'ml' ? '#f0fdf4' : readiness.inference.ml_artifacts_available ? '#fffbeb' : '#fef2f2',
            }}>
              <div style={{ fontWeight: 800, color: readiness.runtime_status?.runtime_mode === 'ml' ? '#16a34a' : readiness.inference.ml_artifacts_available ? '#92400e' : '#b91c1c' }}>
                {readiness.runtime_status?.runtime_mode === 'ml' && 'ML aktiv'}
                {readiness.runtime_status?.runtime_mode !== 'ml' && readiness.inference.ml_artifacts_available && 'Modellartefakte vorhanden, aber Modell nicht aktiviert/promoted'}
                {readiness.runtime_status?.runtime_mode !== 'ml' && !readiness.inference.ml_artifacts_available && 'ML nicht aktiv – kinematischer Fallback'}
              </div>
              {readiness.inference.fallback_reason && (
                <div style={{ fontSize: 12, color: '#6b7280', marginTop: 4 }}>Grund: {readiness.inference.fallback_reason}</div>
              )}
              <div style={{ fontSize: 12, color: '#374151', marginTop: 6 }}>
                Technische Artefakte vorhanden: {readiness.inference.ml_artifacts_available ? 'ja' : 'nein'} · Fachlich promoted: {readiness.inference.promoted ? 'ja' : 'nein'} · Produktiver Runtime-Modus: {readiness.runtime_status?.runtime_mode === 'ml' ? 'ML aktiv' : 'Fallback'}
              </div>
              <div style={{ fontSize: 12, color: '#374151', marginTop: 4 }}>
                Aktive Horizonte: {readiness.runtime_status?.active_horizons?.length ? readiness.runtime_status.active_horizons.join(', ') + ' min' : 'keine'}
              </div>
              {readiness.inference.lgbm_status_by_horizon && (
                <div style={{ fontSize: 11, color: '#6b7280', marginTop: 4 }}>
                  Fehlende Horizonte: {Object.entries(readiness.inference.lgbm_status_by_horizon)
                    .filter(([, v]) => !v.complete)
                    .map(([h]) => h)
                    .join(', ') || 'keine'}
                </div>
              )}
              {readiness.inference.missing_files?.length > 0 && (
                <details style={{ fontSize: 11, color: '#6b7280', marginTop: 6 }}>
                  <summary>Fehlende Dateien ({readiness.inference.missing_files.length})</summary>
                  <ul style={{ margin: '6px 0 0 18px' }}>
                    {readiness.inference.missing_files.slice(0, 12).map(f => <li key={f}><code>{f}</code></li>)}
                    {readiness.inference.missing_files.length > 12 && <li>…</li>}
                  </ul>
                </details>
              )}
            </div>
          )}


          {readiness.latest_training && (
            <div style={{ border: '1px solid #bfdbfe', borderRadius: 8, padding: '10px 12px', marginBottom: 12, background: '#eff6ff' }}>
              <div style={{ fontWeight: 800, color: '#1d4ed8', marginBottom: 6 }}>Modell-Aktivierung / Promotion</div>
              <div style={{ fontSize: 12, color: '#1f2937', lineHeight: 1.6 }}>
                <div><b>Letzter Trainingsstatus:</b> {readiness.latest_training.status || '—'}</div>
                <div><b>Erklärung:</b> {readiness.latest_training.status_reason || 'Keine Erklärung verfügbar.'}</div>
                <div><b>Promotion-Samples:</b> {readiness.latest_training.promotion_samples_recent ?? 0} / {readiness.latest_training.promotion_samples_required ?? 50}</div>
                <div><b>Fehlende Promotion-Samples:</b> {readiness.latest_training.promotion_samples_missing ?? '—'}</div>
                <div><b>Low-confidence:</b> {readiness.latest_training.low_confidence ? 'ja' : 'nein'}</div>
                <div><b>Technische Artefakte vorhanden:</b> {readiness.runtime_status?.ml_model_artifacts_valid ? 'ja' : 'nein'}</div>
                <div><b>Fachlich promoted:</b> {readiness.runtime_status?.ml_model_promoted ? 'ja' : 'nein'}</div>
                <div><b>ML-Modell verfügbar:</b> {readiness.runtime_status?.ml_model_available ? 'ja' : 'nein'}</div>
                <div><b>Produktiver Runtime-Modus:</b> {readiness.runtime_status?.runtime_mode === 'ml' ? 'ML aktiv' : 'kinematischer Fallback'}</div>
                <div><b>Modellversion:</b> {readiness.runtime_status?.ml_model_version || '—'}</div>
                <div><b>Fallback-Grund:</b> {readiness.runtime_status?.fallback_reason || '—'}</div>
                <div style={{ marginTop: 6, color: '#475569' }}>Promotion-Samples steuern die Qualitätssicherung bei Modellwechseln. Bei Cold Start kann ein erstes Modell als low_confidence aktiv sein.</div>
                {readiness.runtime_status?.ml_model_artifacts_valid && !readiness.runtime_status?.ml_model_promoted && (
                  <div style={{ marginTop: 6, color: '#b45309' }}>Modellartefakte vorhanden, aber Modell nicht aktiviert/promoted.</div>
                )}
              </div>
            </div>
          )}

          {!readiness.dataset_exists && (
            <p style={{ fontSize: 11, color: '#9ca3af', margin: '0 0 4px' }}>
              Kein dataset.npz — wird beim nächsten Rebuild-Job erstellt.
            </p>
          )}
          <p style={{ fontSize: 11, color: '#9ca3af', margin: 0, lineHeight: 1.5 }}>
            Das Training verwendet den kumulativen gültigen Datensatz innerhalb der Aufbewahrungszeit. Nach einem Training werden die Samples nicht zurückgesetzt. Es werden nicht nur neue Samples seit dem letzten Training verwendet. Die Aktivierung eines Modells erfolgt separat über Promotion-/Validierungssamples.
          </p>
        </div>
      )}

      <div className="card grid grid-cols-1 md:grid-cols-3 gap-4">
        <div>
          <label className="label">Datensatz-Rebuild (Min.)</label>
          <input
            className="input" type="number" value={rebuild}
            onChange={e => setRebuild(parseInt(e.target.value) || 60)}
          />
          <p className="text-xs text-gray-500 mt-1">
            Wie oft (in Minuten) der Trainings-Datensatz aus den gesammelten
            Radar-Frames neu aufgebaut wird. Empfohlen: 60 Min.
          </p>
        </div>
        <div>
          <label className="label">Retrain-Interval (Stunden)</label>
          <input
            className="input" type="number" value={s.retrain_interval_hours}
            onChange={e => setS({ ...s, retrain_interval_hours: parseInt(e.target.value) || 6 })}
          />
          <p className="text-xs text-gray-500 mt-1">
            LightGBM- und LSTM-Modelle werden zusätzlich zum Nightly-Retrain
            alle N Stunden neu trainiert, wenn genug kumulative Dataset-Sequenzen vorhanden sind. Das Training verwendet den gesamten gültigen Datensatz innerhalb der Aufbewahrungszeit, nicht nur neue Samples seit dem letzten Lauf. Ob das Modell aktiv wird, entscheidet danach die Promotion-Logik. Empfohlen: 6 h.
          </p>
        </div>
        <div></div>

        <div>
          <label className="label">Nightly Retrain Stunde</label>
          <input
            className="input" type="number" min="0" max="23" value={s.retrain_cron_hour}
            onChange={e => setS({ ...s, retrain_cron_hour: parseInt(e.target.value) || 0 })}
          />
          <p className="text-xs text-gray-500 mt-1">
            Stunde (0–23, Lokalzeit) für den täglichen LightGBM/LSTM-Retrain.
            Empfohlen: 3 (03:00 Uhr nachts).
          </p>
        </div>
        <div>
          <label className="label">Nightly Retrain Minute</label>
          <input
            className="input" type="number" min="0" max="59" value={s.retrain_cron_minute}
            onChange={e => setS({ ...s, retrain_cron_minute: parseInt(e.target.value) || 0 })}
          />
          <p className="text-xs text-gray-500 mt-1">
            Minute (0–59) für den täglichen LightGBM/LSTM-Retrain.
            Empfohlen: 0.
          </p>
        </div>
        <div></div>

        <div>
          <label className="label">ConvLSTM Tag</label>
          <select
            className="input" value={s.convlstm_cron_day_of_week}
            onChange={e => setS({ ...s, convlstm_cron_day_of_week: e.target.value })}
          >
            {['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'].map(d => (
              <option key={d}>{d}</option>
            ))}
          </select>
          <p className="text-xs text-gray-500 mt-1">
            Wochentag für das ConvLSTM-Training (Radar-Bildfolgen-Modell).
            Das Training dauert länger als LightGBM — wöchentlich empfohlen.
          </p>
        </div>
        <div>
          <label className="label">ConvLSTM Stunde</label>
          <input
            className="input" type="number" min="0" max="23" value={s.convlstm_cron_hour}
            onChange={e => setS({ ...s, convlstm_cron_hour: parseInt(e.target.value) || 0 })}
          />
          <p className="text-xs text-gray-500 mt-1">
            Stunde (0–23) für den wöchentlichen ConvLSTM-Trainingslauf.
            Empfohlen: 2 (02:00 Uhr, Montag).
          </p>
        </div>
        <div>
          <label className="label">ConvLSTM Minute</label>
          <input
            className="input" type="number" min="0" max="59" value={s.convlstm_cron_minute}
            onChange={e => setS({ ...s, convlstm_cron_minute: parseInt(e.target.value) || 0 })}
          />
          <p className="text-xs text-gray-500 mt-1">
            Minute (0–59) für den wöchentlichen ConvLSTM-Trainingslauf.
            Empfohlen: 0.
          </p>
        </div>
      </div>

      <button className="btn-primary mt-4" onClick={save}>Speichern</button>
      <p className="text-sm text-gray-500 mt-2">
        Hinweis: Änderungen werden erst nach Neustart von wetterprojekt-scheduler aktiv.
      </p>
    </div>
  )
}
