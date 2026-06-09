import React, { useEffect, useRef, useState } from 'react'
import api from '../api.js'

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

  async function loadHealth() {
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
      const { blob, filename } = await api.download('/api/admin/export/last-24h.zip')
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
      setExportMsg({ ok: true, text: 'Debug-Datenexport wurde erstellt und heruntergeladen.' })
      exportingRef.current = false
      await loadLogs()
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

  useEffect(() => {
    loadLogs()
    loadCapabilities()
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
        {['wetterprojekt', 'scheduler', 'admin', 'api_fehler'].map(k => (
          <button key={k} onClick={() => setActive(k)}
            className={active === k ? 'btn-primary' : 'btn-secondary'}>
            {k === 'api_fehler'
              ? `⚠ API-Fehler${summary.total > 0 ? ` (${summary.total})` : ''}`
              : k}
          </button>
        ))}
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
          <th className="p-1 text-right">Nächster Abruf in</th>
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
            <td className="p-1 text-right">
              {s.status === 'FRESH' && s.next_allowed_in_s > 0
                ? `${Math.floor(s.next_allowed_in_s / 60)}m ${s.next_allowed_in_s % 60}s`
                : s.status === 'STALE' ? 'jetzt' : '—'}
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

export default Logs
