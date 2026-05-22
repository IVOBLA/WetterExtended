import React, { useEffect, useState } from 'react'
import api from '../api.js'

function Card({ title, value, subtitle, colorClass }) {
  return (
    <div className={`card ${colorClass || ''}`}>
      <div className="text-xs text-gray-500 uppercase">{title}</div>
      <div className="text-2xl font-semibold mt-1">{value}</div>
      {subtitle && <div className="text-xs text-gray-400 mt-1">{subtitle}</div>}
    </div>
  )
}

/** Strukturiertes Rendering für Request-Payload */
function RequestBlock({ req }) {
  if (!req) return null
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap gap-x-3 text-xs text-gray-600">
        <span><b>Methode:</b> {req.method || '—'}</span>
        <span className="break-all">
          <b>URL:</b> <span className="font-mono">{req.url || '—'}</span>
        </span>
      </div>
      {req.payload != null && (
        <div>
          <div className="text-xs font-semibold text-gray-500 mt-1">Payload</div>
          <pre className="bg-white border rounded p-2 overflow-auto max-h-48 text-xs">
            {typeof req.payload === 'string'
              ? req.payload
              : JSON.stringify(req.payload, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}

/** Strukturiertes Rendering für Response — kein doppeltes Escaping */
function ResponseBlock({ resp }) {
  if (!resp) return null
  const statusColor = resp.status >= 500
    ? 'text-red-600' : resp.status >= 400
    ? 'text-orange-600' : resp.status >= 300
    ? 'text-yellow-600' : 'text-green-600'

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap gap-x-3 text-xs text-gray-600">
        <span>
          <b>Status:</b>{' '}
          <span className={`font-bold ${statusColor}`}>{resp.status}</span>
        </span>
        {resp.content_type && (
          <span><b>Content-Type:</b> {resp.content_type}</span>
        )}
        {resp.error && (
          <span className="text-red-600"><b>Fehler:</b> {resp.error}</span>
        )}
      </div>

      {/* JSON-Body: formatiert als Baum */}
      {resp.body_json != null && (
        <div>
          <div className="text-xs font-semibold text-gray-500 mt-1">JSON-Body</div>
          <pre className="bg-white border rounded p-2 overflow-auto max-h-72 text-xs">
            {JSON.stringify(resp.body_json, null, 2)}
          </pre>
        </div>
      )}

      {/* Text-Body: direkt anzeigen */}
      {resp.body_text != null && (
        <div>
          <div className="text-xs font-semibold text-gray-500 mt-1">Text-Body</div>
          <pre className="bg-white border rounded p-2 overflow-auto max-h-72 text-xs whitespace-pre-wrap">
            {resp.body_text}
          </pre>
        </div>
      )}

      {/* Binär-Metadaten: strukturiert darstellen */}
      {resp.binary && (
        <div className="bg-gray-100 border border-gray-300 rounded p-2 text-xs space-y-0.5">
          <div className="font-semibold text-gray-600">📦 Binär-Antwort</div>
          {resp.content_length != null && (
            <div><b>Größe:</b> {(resp.content_length / 1024).toFixed(1)} KB</div>
          )}
          {resp.sha256 && (
            <div className="break-all">
              <b>SHA-256:</b>{' '}
              <span className="font-mono text-xs">{resp.sha256}</span>
            </div>
          )}
          {resp.saved_to && (
            <div className="break-all">
              <b>Gespeichert unter:</b>{' '}
              <span className="font-mono">{resp.saved_to}</span>
            </div>
          )}
        </div>
      )}

      {/* Kein Body vorhanden */}
      {resp.body_json == null && resp.body_text == null && !resp.binary && (
        <div className="text-xs text-gray-400 italic">Kein Response-Body geloggt.</div>
      )}
    </div>
  )
}

/**
 * Detail-Panel für letzten Request/Response.
 * selectedService: von Tabellen-Klick oder eigenem Dropdown gesteuert.
 * onServiceChange: Callback damit das Panel den externen Zustand aktualisiert.
 */
function ApiLastRequestResponse({ selectedService, onServiceChange, serviceList }) {
  const [detail, setDetail]   = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    const query = selectedService
      ? `/api/api_calls/last?service=${encodeURIComponent(selectedService)}&hours=24`
      : '/api/api_calls/last?hours=24'
    api.get(query)
      .then(d => { setDetail(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [selectedService])

  const entry = detail?.entry

  return (
    <div className="card mt-4">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <h2 className="text-base font-semibold">🔍 Letzter API-Request / Response</h2>
        {serviceList && serviceList.length > 0 && (
          <select
            className="text-xs border border-gray-300 rounded px-2 py-1 bg-white"
            value={selectedService}
            onChange={e => onServiceChange(e.target.value)}
          >
            <option value="">— Letzter Service (beliebig) —</option>
            {serviceList.map(svc => (
              <option key={svc} value={svc}>{svc}</option>
            ))}
          </select>
        )}
      </div>

      <div className="bg-gray-50 border border-gray-200 rounded p-3 text-xs">
        {loading ? (
          <div className="text-gray-400">Lade Details…</div>
        ) : !entry ? (
          <div className="text-gray-400">
            Noch kein API-Request in den letzten 24h geloggt.
          </div>
        ) : (
          <div className="space-y-3">
            {/* Meta-Zeile */}
            <div className="flex flex-wrap gap-x-4 gap-y-1 border-b pb-2">
              <span>
                <b>Service:</b>{' '}
                <span className="font-mono">{entry.service}</span>
              </span>
              <span>
                <b>Zeit:</b>{' '}
                {(entry.ts || '').replace('T', ' ').substring(0, 19)} UTC
              </span>
              <span>
                <b>Status:</b>{' '}
                <span className={`font-bold ${
                  (entry.status || 200) >= 400 ? 'text-red-600' : 'text-green-600'
                }`}>
                  {entry.status}
                </span>
              </span>
              <span>
                <b>Dauer:</b>{' '}
                {entry.duration_ms != null ? `${entry.duration_ms} ms` : '—'}
              </span>
              {entry.public_url && (
                <a
                  className="text-blue-600 underline"
                  href={entry.public_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  🌐 Quelle
                </a>
              )}
            </div>

            {/* Request */}
            <div>
              <div className="font-semibold text-gray-700 mb-1">Request</div>
              <RequestBlock req={entry.request} />
            </div>

            {/* Response */}
            <div>
              <div className="font-semibold text-gray-700 mb-1">Response</div>
              <ResponseBlock resp={entry.response} />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default function Dashboard() {
  const [objs, setObjs]             = useState([])
  const [progress, setProgress]     = useState({ versions: [] })
  const [git, setGit]               = useState({})
  const [disk, setDisk]             = useState(null)
  const [apiCalls, setApiCalls]     = useState(null)
  const [apiHealth, setApiHealth]   = useState(null)
  const [selectedService, setSelectedService] = useState('')

  useEffect(() => {
    Promise.all([
      api.get('/api/objects').then(setObjs).catch(() => setObjs([])),
      api.get('/api/progress').then(setProgress).catch(() => setProgress({ versions: [] })),
      api.get('/api/git').then(setGit).catch(() => {}),
      api.get('/api/disk').then(setDisk).catch(() => setDisk(null)),
      api.get('/api/api_calls?hours=24').then(setApiCalls).catch(() => {}),
      api.get('/api/api_health?hours=24').then(setApiHealth).catch(() => {}),
    ])
  }, [])

  const lastTraining = progress.versions[progress.versions.length - 1]
  const serviceList  = apiCalls?.by_service
    ? Object.keys(apiCalls.by_service).sort()
    : []

  const diskColorClass = disk?.critical
    ? 'border-l-4 border-red-500'
    : disk?.warning
      ? 'border-l-4 border-yellow-500'
      : ''

  const diskLabel = disk
    ? `${disk.used_gb} / ${disk.total_gb} GB — ${disk.free_gb} GB frei`
    : null

  const handleServiceClick = (svc) => {
    setSelectedService(prev => prev === svc ? '' : svc)
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Dashboard</h1>

      {/* Kritischer Speicher-Banner */}
      {disk?.critical && (
        <div className="bg-red-100 border border-red-400 text-red-900 p-3 rounded mb-4 text-sm">
          <strong>⚠ Kritischer Speicherstand:</strong> {disk.used_pct}% belegt —
          Daten-Cleanup prüfen oder DATA_RETENTION_DAYS reduzieren.
        </div>
      )}

      {/* API-Fehler-Banner */}
      {apiHealth?.total > 0 && (
        <div className="bg-orange-50 border border-orange-300 text-orange-900 p-3 rounded mb-4 text-sm">
          <div className="font-semibold mb-1">
            ⚠ {apiHealth.total} API-Fehler in den letzten 24h —{' '}
            <a href="/logs" className="underline">Details unter Logs → API-Fehler</a>
          </div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(apiHealth.by_service || {})
              .sort((a, b) => b[1].count - a[1].count)
              .map(([svc, info]) => (
                <span
                  key={svc}
                  className="bg-orange-100 px-2 py-0.5 rounded text-xs font-mono"
                >
                  {svc}: {info.count}×
                </span>
              ))}
          </div>
        </div>
      )}

      {/* Status-Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card title="Objekte aktuell" value={objs.length} />
        <Card title="Modell-Versionen" value={progress.versions.length} />
        <Card
          title="Letztes Training"
          value={lastTraining
            ? (lastTraining.timestamp_utc || '—').substring(0, 16)
            : '—'}
          subtitle={lastTraining?.validation?.status}
        />
        <Card title="Git" value={git.branch || '—'} subtitle={git.commit} />
        {disk && (
          <Card
            title="Disk-Belegung"
            value={`${disk.used_pct} %`}
            subtitle={diskLabel}
            colorClass={diskColorClass}
          />
        )}
      </div>

      {/* 24h-Statistiktabelle — Anfragen / Fehler / Fehlerrate */}
      {apiCalls?.by_service && Object.keys(apiCalls.by_service).length > 0 && (
        <div className="card mt-4">
          <h2 className="text-base font-semibold mb-2">
            📡 API-Requests (24h)
            <span className="ml-2 text-xs font-normal text-gray-400">
              — Zeile klicken für letzten Request/Response
            </span>
          </h2>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-xs text-gray-500 uppercase">
                <th className="p-1 text-left">Service</th>
                <th className="p-1 text-right">Anfragen</th>
                <th className="p-1 text-right">Fehler</th>
                <th className="p-1 text-right">Fehlerrate</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(apiCalls.by_service)
                .sort((a, b) => b[1].calls - a[1].calls)
                .map(([svc, d]) => {
                  const isSelected = selectedService === svc
                  return (
                    <tr
                      key={svc}
                      className={`border-b cursor-pointer select-none transition-colors ${
                        isSelected
                          ? 'bg-blue-50 hover:bg-blue-100'
                          : 'hover:bg-gray-50'
                      }`}
                      onClick={() => handleServiceClick(svc)}
                      title="Klick für letzten Request/Response"
                    >
                      <td className="p-1 font-mono text-xs">
                        <span className="mr-1 text-gray-400">
                          {isSelected ? '▾' : '▸'}
                        </span>
                        {svc}
                        {d.public_url && (
                          <a
                            href={d.public_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={e => e.stopPropagation()}
                            className="ml-2 text-blue-500 hover:text-blue-700 text-xs"
                            title={`Öffentliche Quelle: ${d.public_url}`}
                          >
                            🌐
                          </a>
                        )}
                      </td>
                      <td className="p-1 text-right">{d.calls}</td>
                      <td className={`p-1 text-right ${
                        d.errors > 0 ? 'text-red-600 font-semibold' : 'text-gray-400'
                      }`}>
                        {d.errors}
                      </td>
                      <td className="p-1 text-right text-xs text-gray-500">
                        {d.calls > 0
                          ? `${((d.errors / d.calls) * 100).toFixed(1)}%`
                          : '—'}
                      </td>
                    </tr>
                  )
                })}
            </tbody>
          </table>
        </div>
      )}

      {/* Letzter API-Request / Response — separater Card unter der Tabelle */}
      <ApiLastRequestResponse
        selectedService={selectedService}
        onServiceChange={setSelectedService}
        serviceList={serviceList}
      />
    </div>
  )
}
