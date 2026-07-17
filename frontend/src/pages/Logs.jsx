import React, { useEffect, useRef, useState } from 'react'
import api from '../api.js'

const EXPORT_STATUS_POLL_MIN_MS = 3000
const EXPORT_STATUS_POLL_MAX_MS = 30000

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

function isRateLimitError(error) {
  return error?.status === 429 || /(^|[^0-9])429([^0-9]|$)/.test(String(error?.message || ''))
}

function nextExportBackoffMs(currentMs) {
  return Math.min(Math.max(currentMs * 2, EXPORT_STATUS_POLL_MIN_MS), EXPORT_STATUS_POLL_MAX_MS)
}

function severityColor(reason = '') {
  if (reason.includes('timeout'))                                    return 'text-orange-600'
  if (reason.includes('http-5'))                                     return 'text-red-700'
  if (reason.includes('http-4'))                                     return 'text-yellow-700'
  if (reason.includes('None') || reason.includes('empty') ||
      reason.includes('0.0'))                                        return 'text-purple-700'
  return 'text-red-600'
}

function Logs() {
  const [logs,        setLogs]        = useState({ wetterprojekt: [], scheduler: [], admin: [] })
  const [rawHealth,   setRawHealth]   = useState({ entries: [], total: 0 })
  const [summary,     setSummary]     = useState({ total: 0, by_service: {} })
  const [active,      setActive]      = useState('wetterprojekt')
  const [hours,       setHours]       = useState(24)
  const [clearMsg,    setClearMsg]    = useState(null)   // { ok, text } für 3s-Feedback
  const [clearing,    setClearing]    = useState(false)
  const [allowPhysicalPurge, setAllowPhysicalPurge] = useState(false)
  const [physicalPurge, setPhysicalPurge] = useState(false)
  const [exporting,    setExporting]    = useState(false)
  const [exportMsg,    setExportMsg]    = useState(null)
  const [latestExport, setLatestExport] = useState(null)   // B350: zuletzt persistierter Export
  const exportingRef = useRef(false)

  async function loadLogs() {
    if (exportingRef.current) return
    try { setLogs(await api.get('/api/logs')) } catch (e) { console.error(e) }
  }
  async function loadCapabilities() {
    try {
      const caps = await api.get('/api/logs/capabilities')
      setAllowPhysicalPurge(Boolean(caps.allow_physical_purge))
    } catch (e) { console.error(e) }
  }

  async function loadLatestExport() {
    // B350: zeigt den zuletzt PERSISTIERTEN Export (egal ob manuell oder
    // automatisiert erstellt) an — ohne einen neuen Build anzustoßen.
    try {
      const meta = await api.get('/api/admin/export/latest/meta')
      setLatestExport(meta?.available ? meta : null)
    } catch (e) { console.error(e) }
  }

  async function loadHealth() {
    if (exportingRef.current) return
    try {
      const [raw, agg] = await Promise.all([
        api.get(`/api/api_health_raw?hours=${hours}&n=200`),
        api.get(`/api/api_health?hours=${hours}`),
      ])
      setRawHealth(raw)
      setSummary(agg)
    } catch (e) { console.error(e) }
  }

  async function clearAllLogs() {
    if (!window.confirm(
      'Logs wirklich löschen/zurücksetzen?\n\n' +
      'API-/Evaluation-Logs werden gelöscht.\n' +
      'Die Systemlog-Anzeige wird ab jetzt neu gestartet.\n' +
      'Alte Logs vor diesem Zeitpunkt werden auch nicht mehr an die KI/Analyse übergeben.\n\n' +
      'Optional physisches Löschen des systemd-Journals ist nur aktiv, wenn der Server dafür konfiguriert wurde.'
    )) return

    setClearing(true)
    try {
      const res = await api.post('/api/logs/clear', { physical: allowPhysicalPurge && physicalPurge })
      if (res.ok) {
        setClearMsg({ ok: true, text: 'API-Logs gelöscht, Systemlog-Anzeige zurückgesetzt, alte Logs für KI gesperrt.' })
        // Logs sofort neu laden
        await loadLogs()
        await loadHealth()  // immer neu laden — Clear betrifft alle Logs
      } else {
        setClearMsg({ ok: false, text: `Fehler: ${(res.errors || []).join(', ')}` })
      }
    } catch (e) {
      setClearMsg({ ok: false, text: `Fehler: ${e.message}` })
    } finally {
      setClearing(false)
      setTimeout(() => setClearMsg(null), 4000)
    }
  }

  async function downloadDebugExport() {
    exportingRef.current = true
    setExporting(true)
    setExportMsg({ ok: true, text: 'Export wird erstellt...' })
    try {
      // B126: Mehrteiliger Export. B162: Build läuft asynchron im Subprozess
      // (sonst systemd-Watchdog-Kill → 502). /parts startet nur und liefert ein
      // Token; der Status wird gepollt, bis das Volume-Set bereit ist.
      const start = await api.get('/api/admin/export/last-24h/parts')
      const token = start.token
      let meta = start
      if (start.status === 'building') {
        setExportMsg({ ok: true, text: 'Export wird im Hintergrund erstellt …' })
        const deadline = Date.now() + 15 * 60 * 1000  // max. 15 min
        // Poll-Schleife: leichte Requests mit Mindestabstand; 429 ist nur
        // temporaere nginx-Last und darf den bereits gestarteten Build nicht beenden.
        let pollDelayMs = EXPORT_STATUS_POLL_MIN_MS
        // eslint-disable-next-line no-constant-condition
        while (true) {
          await sleep(pollDelayMs)
          try {
            const st = await api.get(`/api/admin/export/status?token=${encodeURIComponent(token)}&nocache=true`)
            pollDelayMs = EXPORT_STATUS_POLL_MIN_MS
            if (st.status === 'ready') { meta = st; break }
            if (st.status === 'error') {
              throw new Error(`Export-Build fehlgeschlagen: ${st.detail || 'unbekannt'}`)
            }
            setExportMsg({ ok: true, text: 'Export wird im Hintergrund erstellt …' })
          } catch (e) {
            if (!isRateLimitError(e)) throw e
            setExportMsg({ ok: true, text: 'Server ausgelastet / Rate-Limit, versuche erneut...' })
            pollDelayMs = nextExportBackoffMs(pollDelayMs)
          }
          if (Date.now() > deadline) {
            throw new Error('Export-Build überschritt 15 Minuten — abgebrochen.')
          }
        }
      }
      const partCount = meta.part_count || 1
      for (let i = 1; i <= partCount; i++) {
        setExportMsg({ ok: true, text: `Lade Teil ${i}/${partCount} …` })
        const { blob, filename } = await api.download(
          `/api/admin/export/last-24h.zip?token=${encodeURIComponent(token)}&part=${i}`
        )
        const url = window.URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.download = filename
        document.body.appendChild(link)
        link.click()
        link.remove()
        window.URL.revokeObjectURL(url)
      }
      setExportMsg({
        ok: true,
        text: partCount > 1
          ? `Debug-Datenexport in ${partCount} Teilen heruntergeladen (je ≤ 80 MB).`
          : 'Debug-Datenexport wurde erstellt und heruntergeladen.',
      })
      exportingRef.current = false
      await loadLogs()
      await loadLatestExport()   // B350: gerade erstellter Export ist jetzt der "letzte"
    } catch (e) {
      const is502 = String(e.message || '').includes('502')
      setExportMsg({
        ok: false,
        text: is502
          ? `Datenexport fehlgeschlagen: ${e.message}. 502 bedeutet: Admin-Backend war während der Anfrage nicht erreichbar oder hat die Verbindung geschlossen. Details siehe nginx/admin Logs.`
          : `Datenexport fehlgeschlagen: ${e.message}`,
      })
    } finally {
      exportingRef.current = false
      setExporting(false)
      setTimeout(() => setExportMsg(null), 6000)
    }
  }

  async function downloadLatestExport() {
    // B350: laedt den zuletzt PERSISTIERTEN Export direkt herunter — ohne
    // einen neuen Build anzustoßen (kein Polling nötig).
    if (!latestExport) return
    exportingRef.current = true
    setExporting(true)
    setExportMsg({ ok: true, text: 'Letzter Export wird geladen...' })
    try {
      const partCount = latestExport.part_count || 1
      for (let i = 1; i <= partCount; i++) {
        setExportMsg({ ok: true, text: `Lade Teil ${i}/${partCount} …` })
        const { blob, filename } = await api.download(
          `/api/admin/export/latest.zip?part=${i}`
        )
        const url = window.URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.download = filename
        document.body.appendChild(link)
        link.click()
        link.remove()
        window.URL.revokeObjectURL(url)
      }
      setExportMsg({ ok: true, text: 'Letzter Export wurde heruntergeladen.' })
    } catch (e) {
      setExportMsg({ ok: false, text: `Download fehlgeschlagen: ${e.message}` })
    } finally {
      exportingRef.current = false
      setExporting(false)
      setTimeout(() => setExportMsg(null), 6000)
    }
  }

  useEffect(() => {
    loadLogs()
    loadCapabilities()
    loadLatestExport()   // B350
    const t = setInterval(() => {
      if (!exportingRef.current) loadLogs()
    }, 30000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    if (active === 'api_fehler') loadHealth()
  }, [active, hours])

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Logs</h1>

      <div className="flex gap-2 mb-3 flex-wrap items-center">
        {(() => {
          // B111: Tabs dynamisch aus API-Response + bekannte Reihenfolge.
          const KNOWN_TABS = [
            { key: 'wetterprojekt', label: 'wetterprojekt' },
            { key: 'scheduler', label: 'scheduler' },
            { key: 'admin', label: 'admin' },
            { key: 'nginx_error', label: 'nginx error' },
            { key: 'nginx_access', label: 'nginx access' },
          ]
          const apiErrorTab = {
            key: 'api_fehler',
            label: `⚠ API-Fehler${summary?.total > 0 ? ` (${summary.total})` : ''}`,
          }
          const TABS = [
            ...KNOWN_TABS.filter(t => logs && t.key in logs),
            apiErrorTab,
          ]
          return TABS.map(t => (
            <button key={t.key} onClick={() => setActive(t.key)}
              className={active === t.key ? 'btn-primary' : 'btn-secondary'}>
              {t.label}
            </button>
          ))
        })()}
        <button onClick={active === 'api_fehler' ? loadHealth : loadLogs}
          disabled={exporting}
          className="btn-secondary ml-auto disabled:opacity-50">↺ Reload</button>
        <button
          onClick={downloadDebugExport}
          disabled={exporting}
          className="btn-secondary text-emerald-700 border-emerald-300 hover:bg-emerald-50 disabled:opacity-50 text-xs px-2"
          title="Logs, Bilder, Forecasts, externe Responses und Auswertungen der letzten 24 Stunden als ZIP herunterladen. Secrets werden entfernt.">
          {exporting ? '⌛ Export wird erstellt…' : '⬇ Datenexport letzte 24h herunterladen'}
        </button>
        {active !== 'api_fehler' && (
          <a href="/api/download/logs" download
            className="btn-secondary text-blue-600 border-blue-300 hover:bg-blue-50 text-xs px-2"
            title="Systemlogs (wetterprojekt + scheduler + admin) als .txt herunterladen">
            ⬇ Logs .txt
          </a>
        )}
        <a href="/api/download/objects" download
          className="btn-secondary text-blue-600 border-blue-300 hover:bg-blue-50 text-xs px-2"
          title="Aktuelles Object-JSON (neuester Frame) herunterladen">
          ⬇ Objects .json
        </a>
        <button
          onClick={clearAllLogs}
          disabled={clearing}
          className="btn-secondary text-red-600 border-red-300 hover:bg-red-50 disabled:opacity-50"
          title="API-Logs löschen, Systemlog-Anzeige zurücksetzen und alte Logs für KI sperren">
          {clearing ? '⌛ Löschen…' : '🗑 Logs löschen'}
        </button>
        {allowPhysicalPurge && (
          <label className="text-sm flex items-center gap-2">
            <input
              type="checkbox"
              checked={physicalPurge}
              onChange={(e) => setPhysicalPurge(e.target.checked)}
            />
            Systemd-Journal physisch löschen
          </label>
        )}
      </div>

      {exportMsg && (
        <div className={`mb-3 px-3 py-2 rounded text-sm font-medium
          ${exportMsg.ok
            ? 'bg-green-50 border border-green-300 text-green-800'
            : 'bg-red-50  border border-red-300  text-red-800'}`}>
          {exportMsg.text}
        </div>
      )}

      {/* B350: zuletzt erstellter Export (manuell oder automatisiert) — immer
          direkt herunterladbar, ohne neuen Build. */}
      {latestExport && (
        <div className="mb-3 px-3 py-2 rounded text-sm bg-slate-50 border border-slate-200 flex items-center gap-3 flex-wrap">
          <span className="text-gray-600">
            📦 Letzter Export: {new Date(latestExport.created_at_utc).toLocaleString('de-AT', {
              day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
            })}
            {' '}· {latestExport.part_count} Teil{latestExport.part_count === 1 ? '' : 'e'}
            {' '}· {(latestExport.total_bytes / 1024 / 1024).toFixed(1)} MB
            {' '}· {latestExport.export_reason === 'scheduled_branch_publish' ? 'automatisch' : 'manuell'}
          </span>
          <button
            onClick={downloadLatestExport}
            disabled={exporting}
            className="btn-secondary text-emerald-700 border-emerald-300 hover:bg-emerald-50 disabled:opacity-50 text-xs px-2">
            ⬇ Letzten Export herunterladen
          </button>
        </div>
      )}

      <div className="mb-3 text-xs text-gray-500">
        Der Export enthält Logs, Bilder, Forecasts, externe Responses und Auswertungsdaten der letzten 24 Stunden. Secrets werden entfernt.
        {' '}Anzeige kann gekürzt sein. Vollständige Logs befinden sich im Datenexport.
      </div>

      {/* Feedback-Banner nach Löschen */}
      {clearMsg && (
        <div className={`mb-3 px-3 py-2 rounded text-sm font-medium
          ${clearMsg.ok
            ? 'bg-green-50 border border-green-300 text-green-800'
            : 'bg-red-50  border border-red-300  text-red-800'}`}>
          {clearMsg.text}
        </div>
      )}

      {/* Systemlogs */}
      {active !== 'api_fehler' && (
        <pre className="bg-slate-900 text-slate-100 p-3 rounded overflow-auto text-xs"
          style={{ maxHeight: '70vh' }}>
          {(logs[active] || []).join('\n')}
        </pre>
      )}

      {/* API-Fehler Tab */}
      {active === 'api_fehler' && (
        <div>
          <div className="flex items-center gap-2 mb-3 text-sm">
            <span className="text-gray-500">Zeitraum:</span>
            {[6, 24, 48, 168].map(h => (
              <button key={h} onClick={() => setHours(h)}
                className={hours === h ? 'btn-primary' : 'btn-secondary'}>
                {h < 48 ? `${h}h` : `${h/24}d`}
              </button>
            ))}
          </div>

          {/* Zusammenfassung */}
          {summary.total > 0 && (
            <div className="card mb-3">
              <h2 className="text-sm font-semibold mb-2 text-gray-700">
                Zusammenfassung — {summary.total} Fehler in {hours}h
              </h2>
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b text-gray-500 uppercase">
                    <th className="p-1 text-left">Service</th>
                    <th className="p-1 text-right">Fehler</th>
                    <th className="p-1 text-right">Fallback</th>
                    <th className="p-1 text-left">Häufigster Grund</th>
                    <th className="p-1 text-left">Letzter Fehler</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(summary.by_service || {})
                    .sort((a, b) => b[1].count - a[1].count)
                    .map(([svc, info]) => {
                      const top = Object.entries(info.reasons || {})
                        .sort((a, b) => b[1] - a[1])[0]
                      return (
                        <tr key={svc} className="border-b hover:bg-red-50">
                          <td className="p-1 font-mono font-semibold">{svc}</td>
                          <td className="p-1 text-right text-red-600 font-bold">{info.count}</td>
                          <td className="p-1 text-right text-gray-400">{info.fallback_count}</td>
                          <td className={`p-1 ${severityColor(top?.[0])}`}>
                            {top ? `${top[0]} (${top[1]}×)` : '—'}
                          </td>
                          <td className="p-1 text-gray-400 text-xs">
                            {info.last_ts?.slice(0,19).replace('T',' ') || '—'}
                          </td>
                        </tr>
                      )
                    })}
                </tbody>
              </table>
            </div>
          )}

          {/* Einzeleinträge */}
          <div className="card">
            <h2 className="text-sm font-semibold mb-2 text-gray-700">
              Einzelereignisse ({rawHealth.entries.length} von {rawHealth.total})
            </h2>
            {rawHealth.entries.length === 0 ? (
              <div className="text-sm text-green-700 py-2">✅ Keine API-Fehler im Zeitraum.</div>
            ) : (
              <div className="overflow-auto" style={{ maxHeight: '55vh' }}>
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-white">
                    <tr className="border-b text-gray-500 uppercase">
                      <th className="p-1 text-left">Zeit UTC</th>
                      <th className="p-1 text-left">Service</th>
                      <th className="p-1 text-left">Grund / URL</th>
                      <th className="p-1 text-center">HTTP</th>
                      <th className="p-1 text-center">Fallback</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rawHealth.entries.map((e, i) => (
                      <tr key={i} className="border-b hover:bg-gray-50">
                        <td className="p-1 font-mono whitespace-nowrap">
                          {e.ts_utc?.slice(0,19).replace('T',' ')}
                        </td>
                        <td className="p-1 font-mono font-semibold">{e.service}</td>
                        <td className={`p-1 ${severityColor(e.reason)}`}>
                          <div>{e.reason}</div>
                          {e.url && (
                            <div className="text-gray-400 text-xs break-all mt-0.5"
                                 style={{ wordBreak: 'break-all' }}>
                              {e.url}
                            </div>
                          )}
                        </td>
                        <td className="p-1 text-center text-gray-400">{e.http_status || '—'}</td>
                        <td className="p-1 text-center">
                          {e.fallback_used
                            ? <span className="text-orange-500">✓</span>
                            : <span className="text-gray-300">—</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* P47: Manueller Abruf externer Dienste */}
      <div className="card mt-4">
        <h2 className="text-base font-semibold mb-3">🔄 Externe Dienste manuell auslösen</h2>
        <ManualFetchPanel paused={exporting} />
      </div>

      {/* Cache-Status */}
      <div className="card mt-4">
        <h2 className="text-base font-semibold mb-3">🗄️ API-Cache Status</h2>
        <CacheStatusTable />
      </div>
    </div>
  )
}

function CacheStatusTable() {
  const [data, setData] = useState(null)

  useEffect(() => {
    api.get('/api/cache_status').then(setData).catch(() => {})
  }, [])

  if (!data) return <div className="text-gray-400 text-sm">Lade Cache-Status…</div>

  const statusColor = (s) =>
    s === 'FRESH' ? 'text-green-600' : s === 'STALE' ? 'text-orange-500' : 'text-gray-400'

  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="border-b text-gray-500 uppercase">
          <th className="p-1 text-left">Namespace</th>
          <th className="p-1 text-right">Status</th>
          <th className="p-1 text-right">Alter</th>
          <th className="p-1 text-right">TTL</th>
          <th className="p-1 text-right">Frühester nächster Abruf</th>
          <th className="p-1 text-left">Letzter Abruf</th>
        </tr>
      </thead>
      <tbody>
        {(data.services || []).map((s) => (
          <tr key={s.namespace} className="border-b hover:bg-gray-50">
            <td className="p-1 font-mono">{s.namespace}</td>
            <td className={`p-1 text-right font-bold ${statusColor(s.status)}`}>{s.status}</td>
            <td className="p-1 text-right">
              {s.age_s != null ? `${Math.floor(s.age_s / 60)}m ${s.age_s % 60}s` : '—'}
            </td>
            <td className="p-1 text-right">
              {s.ttl_s != null ? `${Math.floor(s.ttl_s / 60)}m` : '—'}
            </td>
            <td className="p-1 text-right whitespace-nowrap">
              {s.next_fetch_ts ? (() => {
                const t = new Date(s.next_fetch_ts)
                const clock = t.toLocaleString('de-AT', {
                  day: '2-digit', month: '2-digit', year: 'numeric',
                  hour: '2-digit', minute: '2-digit', second: '2-digit'
                })
                const overdue = t.getTime() <= Date.now()
                return (
                  <span className={overdue ? 'text-orange-500 font-semibold' : 'text-green-700'}>
                    {clock}{overdue ? ' (fällig)' : ''}
                  </span>
                )
              })() : '—'}
            </td>
            <td className="p-1 text-gray-500">
              {s.last_fetch_ts
                ? new Date(s.last_fetch_ts).toLocaleString('de-AT', {
                    day: '2-digit', month: '2-digit', year: 'numeric',
                    hour: '2-digit', minute: '2-digit', second: '2-digit'
                  })
                : '—'}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ManualFetchPanel({ paused = false }) {
  const [available, setAvailable] = useState([])
  const [runs, setRuns] = useState({})
  const [error, setError] = useState(null)

  const load = () => {
    if (paused) return Promise.resolve()
    return api.get('/api/system/job_status?nocache=true')
    .then((d) => { setAvailable(d.available || []); setRuns(d.runs || {}) })
    .catch(() => {})
  }

  useEffect(() => {
    if (!paused) load()
    const anyRunning = Object.values(runs).some((r) => r.state === 'running')
    const iv = setInterval(load, paused ? 30000 : (anyRunning ? 5000 : 10000))
    return () => clearInterval(iv)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paused, JSON.stringify(Object.values(runs).map((r) => r.state))])

  const trigger = (jobId) => {
    setError(null)
    api.post(`/api/system/run_job/${jobId}`)
      .then(() => setTimeout(load, 300))
      .catch((e) => {
        const msg = String(e?.message || e)
        setError(
          msg.includes('403') || msg.includes('Admin-Berechtigung') ? 'Nur für Admins.' :
          msg.includes('409') || msg.includes('Job läuft bereits') ? 'Job läuft bereits.' : msg
        )
      })
  }

  return (
    <div>
      {error && <div className="text-sm text-red-600 mb-2">{error}</div>}
      <div className="flex flex-wrap gap-2">
        {available.map((j) => {
          const r = runs[j.job_id]
          const running = r && r.state === 'running'
          return (
            <button
              key={j.job_id}
              onClick={() => trigger(j.job_id)}
              disabled={running}
              className={`px-3 py-1.5 rounded text-sm border transition
                ${running ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                          : 'bg-blue-600 text-white hover:bg-blue-700'}`}
            >
              {running ? '⏳ ' : '▶ '}{j.label}
            </button>
          )
        })}
      </div>
      <div className="mt-3 space-y-1 text-xs text-gray-600">
        {available.map((j) => {
          const r = runs[j.job_id]
          if (!r) return null
          const color = r.state === 'ok' ? 'text-green-700'
                       : r.state === 'error' ? 'text-red-600' : 'text-blue-700'
          const when = r.finished_utc || r.started_utc
          const clock = when ? new Date(when).toLocaleTimeString('de-AT', {
            hour: '2-digit', minute: '2-digit', second: '2-digit'
          }) : ''
          return (
            <div key={j.job_id} className={color}>
              <span className="font-mono">{j.label}</span>: {r.state}
              {r.message ? ` — ${r.message}` : ''}
              {r.duration_s != null ? ` (${r.duration_s}s)` : ''} {clock && `· ${clock}`}
            </div>
          )
        })}
      </div>
      <p className="text-xs text-gray-400 mt-2">
        Läuft im Admin-Dienst und aktualisiert die gemeinsamen Cache-Dateien. „Alle Dienste
        testen" pingt jeden externen Endpunkt einmal an. TAWES/CAPE/Nowcast/Radar werden
        sonst laufend im Hauptdienst geholt.
      </p>
    </div>
  )
}

export default Logs
