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
  const [trainingStatus, setTrainingStatus] = useState(null)
  const [startError, setStartError] = useState('')
  const [mlStatus, setMlStatus] = useState(null)
  const [mlBackups, setMlBackups] = useState([])
  const [mlBusy, setMlBusy] = useState(false)
  const [mlSchema, setMlSchema] = useState(null)
  const [schemaPolicy, setSchemaPolicy] = useState('compatible_only')
  const [backupJobId, setBackupJobId] = useState(null)
  const [backupStatus, setBackupStatus] = useState(null)
  const [resetStatus, setResetStatus] = useState(null)
  const [resetJobId, setResetJobId] = useState(null)
  const backupRunning = Boolean(backupStatus?.running)
  const resetRunning = Boolean(resetStatus?.running)
  const mlActionsDisabled = mlBusy || backupRunning || resetRunning
  const runtimeStatus = readiness?.runtime_status || mlStatus?.runtime_status || mlSchema?.runtime_status || {}
  const modelActive = runtimeStatus.runtime_mode === 'ml' && runtimeStatus.ml_model_available === true
  const modelVersion = runtimeStatus.active_model_version || runtimeStatus.ml_model_version || null
  const modelSchemaHash = runtimeStatus.active_model_schema_hash || mlSchema?.active_model_schema_hash || null
  const displayStatusLabels = {
    ml_active: 'ML aktiv',
    fallback: 'kinematischer Fallback',
    incompatible: 'Modell inkompatibel',
    missing_model: 'kein gültiges ML-Modell',
  }
  const displayStatus = runtimeStatus.display_status || (modelActive ? 'ml_active' : 'fallback')

  useEffect(() => {
    // B99: Countdown — Live-Refresh alle 60 s (sinkt sichtbar bei Sturmereignissen)
    const fetchReadiness = () =>
      api.get('/api/training_readiness').then(setReadiness).catch(() => {})
    const fetchTrainingStatus = () =>
      api.get('/api/training/status').then(setTrainingStatus).catch(() => setTrainingStatus({ backend_unreachable: true, running: false }))
    const fetchMl = () => {
      api.get('/api/admin/ml/status').then(setMlStatus).catch(() => {})
      api.get('/api/admin/ml/backups').then(d => setMlBackups(d.backups || [])).catch(() => {})
      api.get('/api/admin/ml/schema').then(setMlSchema).catch(() => {})
      api.get('/api/admin/ml/backup/status').then(setBackupStatus).catch(() => {})
      api.get('/api/admin/ml/reset/status').then(setResetStatus).catch(() => {})
    }
    fetchReadiness()
    fetchTrainingStatus()
    fetchMl()
    const _rdTimer = setInterval(fetchReadiness, 60_000)
    const _statusTimer = setInterval(fetchTrainingStatus, 5_000)
    const _mlTimer = setInterval(fetchMl, 60_000)

    api.get('/api/training')
      .then(d => {
        if (d.DATASET_REBUILD_INTERVAL_MIN != null) setRebuild(d.DATASET_REBUILD_INTERVAL_MIN)
        if (d.TRAINING_SCHEDULE) setS(prev => ({ ...prev, ...d.TRAINING_SCHEDULE }))
      })
      .catch(() => {})

    api.get('/api/local_training')
      .then(d => setLocalTraining(d.local_training !== false))
      .catch(() => {})

    return () => {
      clearInterval(_rdTimer)  // B99: Timer beim Unmount stoppen
      clearInterval(_statusTimer)
      clearInterval(_mlTimer)
    }
  }, [])

  const startTraining = async () => {
    setStartError('')
    try {
      const data = await api.post('/api/training/start', {})
      setMsg(data.message || 'Training wurde gestartet')
      const status = await api.get('/api/training/status')
      setTrainingStatus(status)
    } catch (e) {
      const text = e?.message || 'Unbekannter Fehler'
      setStartError(text)
      setMsg('Fehler: ' + text)
      try {
        setTrainingStatus(await api.get('/api/training/status'))
      } catch (_) {}
    }
  }

  const refreshMl = async () => {
    const st = await api.get('/api/admin/ml/status')
    setMlStatus(st)
    const b = await api.get('/api/admin/ml/backups')
    setMlBackups(b.backups || [])
    try { setMlSchema(await api.get('/api/admin/ml/schema')) } catch (_) {}
  }

  const formatSection = (section) => `${section.path}: ${section.files} Dateien, ${section.dirs} Ordner, ${section.size_mb} MB — ${section.reason || section.action}`

  const runMlReset = async (mode) => {
    setMlBusy(true)
    try {
      const plan = await api.get(`/api/admin/ml/reset/preview?mode=${encodeURIComponent(mode)}`)
      const deleteSections = plan.delete_sections || []
      const preserveSections = plan.preserve_sections || plan.preserved_sections || []
      const manualSections = plan.manual_review_sections || []
      if (manualSections.length) {
        setMsg('ML-Reset blockiert: Manuelle Prüfung erforderlich für ' + manualSections.map(s => s.path).join(', '))
        return
      }
      const lines = [
        'Backup wird erstellt:',
        `- ${plan.backup_target || 'backups/YYYYMMDD_HHMMSS_train_data.zip'}`,
        '',
        'Wird nach erfolgreichem Backup gelöscht:',
        ...(deleteSections.length ? deleteSections.map(formatSection) : ['—']),
        '',
        'Bleibt erhalten:',
        ...(preserveSections.length ? preserveSections.map(formatSection) : ['—']),
        '',
        'Manuelle Prüfung erforderlich:',
        ...(manualSections.length ? manualSections.map(formatSection) : ['—']),
        '',
        'Explizit erhalten: backups/, Konfigurationen, train_data/statistics/, DEM, Cell-Filter und statische Hydro-Daten.',
        'Explizit gelöscht: alte dynamische Daten wie arome, cape, cloud, evaluation, external_responses und archived_training_sources.',
        '',
        'Nach dem Reset ist kein ML-Modell aktiv; der kinematische Fallback übernimmt und neue Trainingsdaten werden ab jetzt gesammelt.',
        '',
        'Fortfahren?'
      ]
      const ok = window.confirm(lines.join('\n'))
      if (!ok) return
      const data = await api.post('/api/admin/ml/reset/start', { mode })
      setResetJobId(data.job_id)
      setResetStatus({ running: true, finished: false, failed: false, job_id: data.job_id, status: data.status, plan: data.plan, current_step: 'preflight', progress: 'Reset läuft', percent: 1 })
      setMsg('ML-Reset läuft im Hintergrund...')
    } catch (e) {
      setMsg('ML-Reset fehlgeschlagen: ' + e.message)
    } finally {
      setMlBusy(false)
    }
  }

  useEffect(() => {
    if (!backupRunning && !backupJobId) return undefined
    const pollBackupStatus = async () => {
      try {
        const status = await api.get('/api/admin/ml/backup/status')
        setBackupStatus(status)
        if (status.finished) {
          setBackupJobId(null)
          setMsg(`Backup erfolgreich erstellt: ${status.backup?.id || status.backup_id || '—'}`)
          await refreshMl()
        } else if (status.failed) {
          setBackupJobId(null)
          setMsg('Backup fehlgeschlagen: ' + (status.error || 'Unbekannter Fehler'))
        }
      } catch (e) {
        setBackupJobId(null)
        setBackupStatus(prev => ({ ...(prev || {}), running: false, failed: true, error: e.message }))
        setMsg('Backup-Status konnte nicht gelesen werden: ' + e.message)
      }
    }
    const timer = setInterval(pollBackupStatus, 1000)
    pollBackupStatus()
    return () => clearInterval(timer)
  }, [backupRunning, backupJobId])


  useEffect(() => {
    if (!resetRunning && !resetJobId) return undefined
    const pollResetStatus = async () => {
      try {
        const status = await api.get('/api/admin/ml/reset/status')
        setResetStatus(status)
        const leftovers = status.verification?.deleted_sections_verified?.filter(sec => !sec.ok) || []
        if (status.finished) {
          setResetJobId(null)
          setMsg(`Reset abgeschlossen. Backup: ${status.backup?.id || status.result?.backup_id || '—'}. Gelöscht aus dynamischer ML-/Datenhistorie: ${status.deleted_counts?.files || 0} Dateien / ${status.deleted_counts?.dirs || 0} Ordner / ${status.deleted_counts?.size_mb || 0} MB. Abschlussprüfung bestanden. Erhalten: Konfigurationen, Statistik, Backups, DEM, Cell-Filter, statische Hydro-Daten. ML-Modell fehlt, kinematischer Fallback aktiv. Neue Trainingsdaten werden ab jetzt gesammelt.`)
          await refreshMl()
        } else if (status.status === 'completed_with_leftovers' || status.status === 'failed_verification') {
          setResetJobId(null)
          setMsg('Reset abgeschlossen, aber Abschlussprüfung nicht bestanden. Folgende geplante Löschbereiche enthalten noch Dateien: ' + (leftovers.map(sec => `${sec.path} (${sec.actual_files} Dateien/${sec.actual_dirs} Ordner/${sec.actual_size_mb} MB)`).join('; ') || status.error || 'unbekannt'))
          await refreshMl()
        } else if (status.failed) {
          setResetJobId(null)
          setMsg('ML-Reset fehlgeschlagen: ' + (status.error || 'Unbekannter Fehler'))
        }
      } catch (e) {
        setResetJobId(null)
        setResetStatus(prev => ({ ...(prev || {}), running: false, failed: true, error: e.message }))
        setMsg('ML-Reset-Status konnte nicht gelesen werden: ' + e.message)
      }
    }
    const timer = setInterval(pollResetStatus, 1500)
    pollResetStatus()
    return () => clearInterval(timer)
  }, [resetRunning, resetJobId])

  const createMlBackup = async () => {
    setMlBusy(true)
    try {
      const data = await api.post('/api/admin/ml/backup', {})
      setBackupJobId(data.job_id)
      setBackupStatus({ running: true, finished: false, failed: false, job_id: data.job_id, status: data.status, progress: 'Backup wird erstellt...' })
      setMsg('Backup läuft...')
    } catch (e) {
      setMsg('Backup konnte nicht gestartet werden: ' + e.message)
    } finally {
      setMlBusy(false)
    }
  }

  const downloadMlBackup = async (id) => {
    setMlBusy(true)
    try {
      const { blob, filename } = await api.download(`/api/admin/ml/backups/${encodeURIComponent(id)}/download`)
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename || id
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
      setMsg(`Backup heruntergeladen: ${filename || id}`)
    } catch (e) {
      setMsg('Backup-Download fehlgeschlagen: ' + e.message)
    } finally {
      setMlBusy(false)
    }
  }

  const deleteMlBackup = async (id) => {
    if (!window.confirm(`Backup ${id} löschen?`)) return
    await api.delete(`/api/admin/ml/backups/${encodeURIComponent(id)}`)
    await refreshMl()
  }

  const scanDataset = async () => {
    setMlBusy(true)
    try {
      const data = await api.post('/api/admin/ml/dataset-scan', { schema_policy: schemaPolicy })
      setMlSchema(prev => ({ ...(prev || {}), dataset_scan: data, current_schema: data.current_schema || prev?.current_schema }))
      setMsg('Dataset-Scan abgeschlossen — es wurde kein Modell trainiert.')
    } catch (e) {
      setMsg('Dataset-Scan fehlgeschlagen: ' + e.message)
    } finally {
      setMlBusy(false)
    }
  }

  const retrainWithSchemaPolicy = async () => {
    setMlBusy(true)
    try {
      const data = await api.post('/api/admin/ml/retrain', { schema_policy: schemaPolicy })
      setMsg(data.message || 'Training mit Schema-Policy gestartet')
      try { setTrainingStatus(await api.get('/api/training/status')) } catch (_) {}
    } catch (e) {
      setMsg('Retrain fehlgeschlagen: ' + e.message)
    } finally {
      setMlBusy(false)
    }
  }

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

      <div className="card mb-4">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">Manuelles Training</h2>
            <p className="text-sm text-gray-600">Startet dieselbe serverseitige Trainingspipeline wie der Scheduler im Hintergrund.</p>
          </div>
          <button
            className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
            disabled={Boolean(trainingStatus?.running) || !readiness?.all_ready || Boolean(trainingStatus?.backend_unreachable)}
            onClick={startTraining}
          >
            Training jetzt starten
          </button>
        </div>
        {trainingStatus?.backend_unreachable && <div className="text-sm text-red-700 mt-3">Backend nicht erreichbar — manueller Start ist deaktiviert.</div>}
        {!readiness?.all_ready && <div className="text-sm text-amber-700 mt-3">Dataset-Schwelle noch nicht erreicht — Button deaktiviert.</div>}
        {trainingStatus?.running && (
          <div className="text-sm text-blue-800 mt-3">
            <b>Training läuft im Hintergrund.</b> Startzeit: {trainingStatus.started_at || '—'} · Run-ID: {trainingStatus.run_id || '—'} · Schritt: {trainingStatus.progress_message || '—'}
          </div>
        )}
        {trainingStatus && !trainingStatus.running && (
          <div className="text-sm text-gray-800 mt-3 leading-6">
            <div><b>Letzter Status:</b> {trainingStatus.last_status || '—'} · <b>Beendet:</b> {trainingStatus.finished_at || '—'}</div>
            <div><b>Modell aktiviert:</b> {modelActive ? 'ja' : 'nein'} · <b>Runtime-Modus:</b> {modelActive ? 'ML' : 'Fallback'}</div>
            <div><b>Promotion-Samples:</b> {trainingStatus.latest_training_meta?.validation?.samples_recent ?? readiness?.latest_training?.promotion_samples_recent ?? '—'} · <b>Low confidence:</b> {(trainingStatus.latest_training_meta?.validation?.low_confidence || readiness?.latest_training?.low_confidence) ? 'ja' : 'nein'}</div>
            <div><a className="text-blue-700 underline" href="/progress">Zur Progress-Versionstabelle</a></div>
          </div>
        )}
        {(startError || trainingStatus?.last_error) && (
          <div className="bg-red-50 border border-red-300 text-red-800 p-2 rounded mt-3 text-sm">
            Fehler: {startError || trainingStatus.last_error}
          </div>
        )}
      </div>


      <div className="card mb-4">
        <h2 className="text-lg font-semibold mb-2">ML Training</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-sm mb-3">
          <div><b>Aktive Modellversion:</b> {modelVersion || 'Kein gültig aktives ML-Modell'}</div>
          <div><b>Anzahl Modelle:</b> {mlStatus?.model_count ?? '—'}</div>
          <div><b>Dataset:</b> {mlStatus?.dataset_present ? 'vorhanden' : 'nicht vorhanden'} ({mlStatus?.samples ?? 0} Samples)</div>
          <div><b>Letztes Training:</b> {mlStatus?.latest_training || '—'}</div>
          <div><b>Letzter Reset:</b> {mlStatus?.last_reset?.created || '—'}</div>
          <div><b>Letztes Backup:</b> {mlStatus?.last_backup?.created || '—'}</div>
        </div>
        {!mlStatus?.models_present && (
          <div className="bg-amber-50 border border-amber-200 text-amber-900 rounded p-2 text-sm mb-3">
            Keine ML Modelle vorhanden. Neue Daten sammeln. Anschließend neu trainieren. Prediction nutzt automatisch den kinematischen Fallback.
          </div>
        )}
        {mlStatus?.last_backup?.id && (
          <div className="bg-green-50 border border-green-200 text-green-900 rounded p-2 text-sm mb-3">
            Backup erfolgreich erstellt · <button type="button" className="underline" disabled={mlActionsDisabled} onClick={() => downloadMlBackup(mlStatus.last_backup.id)}>Backup herunterladen</button>
          </div>
        )}
        <div className="flex flex-wrap gap-2 mb-4">
          <button className="btn inline-flex items-center gap-2" disabled={mlActionsDisabled} onClick={createMlBackup}>
            {backupRunning && <span className="inline-block h-4 w-4 rounded-full border-2 border-current border-t-transparent animate-spin" aria-hidden="true" />}
            {backupRunning ? 'Backup läuft...' : 'Backup erstellen'}
          </button>
          <button className="btn" disabled={mlActionsDisabled} onClick={() => runMlReset('models_only')}>ML zurücksetzen</button>
          <button className="btn-danger" disabled={mlActionsDisabled} onClick={() => runMlReset('full_new_data_only')}>ML zurücksetzen & nur neue Daten sammeln</button>
        </div>
        <div className="border rounded p-3 mb-4 bg-slate-50 text-sm">
          <h3 className="font-semibold mb-2">Feature-Schema-Kompatibilität</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2 mb-2">
            <div><b>Schema-Version:</b> {mlSchema?.current_schema?.schema_version || '—'}</div>
            <div><b>Schema-Hash:</b> <code className="text-xs">{mlSchema?.current_schema?.feature_schema_hash || '—'}</code></div>
            <div><b>Feature-Anzahl:</b> {mlSchema?.current_schema?.num_features ?? '—'}</div>
            <div><b>Kompatible Quellen:</b> {mlSchema?.dataset_scan?.compatible_samples ?? '—'}</div>
            <div><b>Legacy-Quellen:</b> {mlSchema?.dataset_scan?.legacy_samples ?? '—'}</div>
            <div><b>Schema-Mismatch:</b> {mlSchema?.dataset_scan?.mismatch_samples ?? '—'}</div>
            <div><b>Verwendbar:</b> {mlSchema?.dataset_scan?.used_samples ?? '—'}</div>
            <div><b>Abgelehnt:</b> {mlSchema?.dataset_scan?.rejected_samples ?? '—'}</div>
            <div><b>Modell kompatibel:</b> {runtimeStatus.model_schema_compatible ? 'ja' : 'nein'}</div>
          </div>
          <div className="mb-2"><b>Modell-Schema-Hash:</b> <code className="text-xs">{modelSchemaHash || '—'}</code></div>
          <div className="mb-2"><b>Top-Ablehnungsgründe:</b> {Object.entries(mlSchema?.dataset_scan?.rejection_reasons || {}).map(([k,v]) => `${k}: ${v}`).join(', ') || '—'}</div>
          <label className="inline-flex items-center gap-2 mr-3"><input type="radio" checked={schemaPolicy === 'compatible_only'} onChange={() => setSchemaPolicy('compatible_only')} /> Nur kompatible Daten trainieren</label>
          <label className="inline-flex items-center gap-2"><input type="radio" checked={schemaPolicy === 'allow_legacy'} onChange={() => setSchemaPolicy('allow_legacy')} /> Legacy-Daten erlauben</label>
          {schemaPolicy === 'allow_legacy' && <div className="bg-amber-100 border border-amber-300 text-amber-900 rounded p-2 mt-2">Legacy-Daten können mit altem Feature-Set erzeugt worden sein und die Modellqualität verschlechtern.</div>}
          {backupRunning && <div className="text-blue-800 text-sm mt-2">Backup läuft... {backupStatus?.progress || ''}</div>}
          {resetRunning && <div className="text-blue-800 text-sm mt-2 flex items-center gap-2"><span className="inline-block h-4 w-4 rounded-full border-2 border-current border-t-transparent animate-spin" aria-hidden="true" /> ML-Reset läuft: {resetStatus?.current_step || resetStatus?.progress || '—'} ({resetStatus?.percent || 0}%)</div>}
          {resetStatus?.finished && <div className="bg-green-50 border border-green-200 text-green-900 rounded p-2 mt-2">Reset abgeschlossen · Backup: {resetStatus.backup?.id || resetStatus.result?.backup_id || '—'} · Gelöscht aus dynamischer ML-/Datenhistorie: {resetStatus.deleted_counts?.files || 0} Dateien/{resetStatus.deleted_counts?.dirs || 0} Ordner/{resetStatus.deleted_counts?.size_mb || 0} MB · Abschlussprüfung bestanden · Erhalten: Konfigurationen, Statistik, Backups, DEM, Cell-Filter, statische Hydro-Daten · ML-Modell fehlt, kinematischer Fallback aktiv. Neue Trainingsdaten werden ab jetzt gesammelt.</div>}
          {(resetStatus?.status === 'completed_with_leftovers' || resetStatus?.status === 'failed_verification') && <div className="bg-amber-50 border border-amber-300 text-amber-900 rounded p-2 mt-2">
            <div className="font-semibold">Reset abgeschlossen, aber Abschlussprüfung nicht bestanden.</div>
            {(resetStatus.verification?.deleted_sections_verified || []).filter(sec => !sec.ok).map(sec => (
              <div key={sec.path}>{sec.path}: {sec.actual_files} Dateien/{sec.actual_dirs} Ordner/{sec.actual_size_mb} MB · Beispiele: {(sec.leftovers || []).join(', ') || '—'}</div>
            ))}
          </div>}
          {resetStatus?.failed && <div className="bg-red-50 border border-red-300 text-red-800 rounded p-2 mt-2">Reset fehlgeschlagen: {resetStatus.error || 'Unbekannter Fehler'}</div>}
          <div className="flex flex-wrap gap-2 mt-3">
            <button className="btn" disabled={mlActionsDisabled} onClick={scanDataset}>Dataset neu prüfen</button>
            <button className="btn-primary" disabled={mlActionsDisabled} onClick={retrainWithSchemaPolicy}>Nur kompatible Daten trainieren</button>
          </div>
        </div>
        <h3 className="font-semibold mb-2">ML Backups</h3>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead><tr className="border-b"><th className="text-left p-1">Datum</th><th className="text-left p-1">Größe</th><th className="text-left p-1">Reset-Typ</th><th className="text-left p-1">Download</th><th className="text-left p-1">Löschen</th></tr></thead>
            <tbody>
              {mlBackups.map(b => (
                <tr key={b.id} className="border-b"><td className="p-1">{b.created}</td><td className="p-1">{b.size_mb} MB</td><td className="p-1">{b.reset_type}</td><td className="p-1"><button type="button" className="underline" disabled={mlActionsDisabled} onClick={() => downloadMlBackup(b.id)}>Download</button></td><td className="p-1"><button className="btn" onClick={() => deleteMlBackup(b.id)}>Löschen</button></td></tr>
              ))}
              {mlBackups.length === 0 && <tr><td className="p-1 text-gray-500" colSpan="5">Keine Backups vorhanden.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

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
              marginBottom: 12, background: modelActive ? '#f0fdf4' : displayStatus === 'incompatible' ? '#fef2f2' : readiness.inference.ml_artifacts_available ? '#fffbeb' : '#fef2f2',
            }}>
              <div style={{ fontWeight: 800, color: modelActive ? '#16a34a' : displayStatus === 'incompatible' ? '#b91c1c' : readiness.inference.ml_artifacts_available ? '#92400e' : '#b91c1c' }}>
                {displayStatusLabels[displayStatus] || 'Fallback'}
              </div>
              {runtimeStatus.fallback_reason && (
                <div style={{ fontSize: 12, color: '#6b7280', marginTop: 4 }}>Grund: {runtimeStatus.fallback_reason}</div>
              )}
              <div style={{ fontSize: 12, color: '#374151', marginTop: 6 }}>
                Technische Artefakte vorhanden: {readiness.inference.ml_artifacts_available ? 'ja' : 'nein'} · Fachlich promoted: {readiness.inference.promoted ? 'ja' : 'nein'} · Produktiver Runtime-Modus: {modelActive ? 'ML aktiv' : 'Fallback'}
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
                <div><b>Technische Artefakte vorhanden:</b> {runtimeStatus.ml_model_artifacts_valid ? 'ja' : 'nein'}</div>
                <div><b>Fachlich promoted:</b> {runtimeStatus.ml_model_promoted ? 'ja' : 'nein'}</div>
                <div><b>ML-Modell verfügbar:</b> {runtimeStatus.ml_model_available ? 'ja' : 'nein'}</div>
                <div><b>Produktiver Runtime-Modus:</b> {modelActive ? 'ML aktiv' : 'kinematischer Fallback'}</div>
                <div><b>Modellversion:</b> {modelVersion || '—'}</div>
                <div><b>Fallback-Grund:</b> {runtimeStatus.fallback_reason || '—'}</div>
                <div style={{ marginTop: 6, color: '#475569' }}>Promotion-Samples steuern die Qualitätssicherung bei Modellwechseln. Bei Cold Start kann ein erstes Modell als low_confidence aktiv sein.</div>
                {runtimeStatus.ml_model_artifacts_valid && !runtimeStatus.ml_model_promoted && (
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
