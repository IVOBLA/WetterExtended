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

function ApiLastRequestResponse({ service }) {
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    const query = service
      ? `/api/api_calls/last?service=${encodeURIComponent(service)}&hours=24`
      : '/api/api_calls/last?hours=24'
    api.get(query)
      .then(d => { setDetail(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [service])
  const entry = detail?.entry

  return (
    <div className="bg-gray-50 border border-gray-200 rounded p-3 text-xs">
      {loading ? <div className="text-gray-400">Lade Details…</div> : !entry ? (
        <div className="text-gray-400">Noch kein API-Request geloggt.</div>
      ) : (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            <span><b>Service:</b> <span className="font-mono">{entry.service}</span></span>
            <span><b>Zeit:</b> {(entry.ts || '').replace('T', ' ').substring(0, 19)} UTC</span>
            <span><b>Status:</b> {entry.status}</span>
            <span><b>Dauer:</b> {entry.duration_ms != null ? `${entry.duration_ms} ms` : '—'}</span>
            {entry.public_url && <a className="text-blue-600 underline" href={entry.public_url} target="_blank" rel="noreferrer">🌐 Quelle</a>}
          </div>
          <div>
            <div className="font-semibold">Request</div>
            <pre className="bg-white border rounded p-2 overflow-auto max-h-56">{JSON.stringify(entry.request, null, 2)}</pre>
            {entry.request?.truncated && <div className="text-amber-700">Ausgabe gekürzt</div>}
          </div>
          <div>
            <div className="font-semibold">Response</div>
            <pre className="bg-white border rounded p-2 overflow-auto max-h-56">{JSON.stringify(entry.response, null, 2)}</pre>
            {entry.response?.truncated && <div className="text-amber-700">Ausgabe gekürzt</div>}
            {String(entry.response?.body_preview || '').includes('[binary response:') && <div className="text-gray-500">Binärantwort erkannt.</div>}
          </div>
        </div>
      )}
    </div>
  )
}

export default function Dashboard() {
  const [objs, setObjs] = useState([])
  const [progress, setProgress] = useState({ versions: [] })
  const [git, setGit] = useState({})
  const [disk, setDisk] = useState(null)
  const [apiCalls,  setApiCalls]  = useState(null)
  const [apiHealth, setApiHealth] = useState(null)
  const [selectedService, setSelectedService] = useState(null)

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

  const diskColorClass = disk?.critical
    ? 'border-l-4 border-red-500'
    : disk?.warning
      ? 'border-l-4 border-yellow-500'
      : ''

  const diskLabel = disk
    ? `${disk.used_gb} / ${disk.total_gb} GB — ${disk.free_gb} GB frei`
    : null

  const handleServiceClick = (svc) => {
    setSelectedService(prev => prev === svc ? null : svc)
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Dashboard</h1>

      {disk?.critical && (
        <div className="bg-red-100 border border-red-400 text-red-900 p-3 rounded mb-4 text-sm">
          <strong>⚠ Kritischer Speicherstand:</strong> {disk.used_pct}% belegt —
          Daten-Cleanup prüfen oder DATA_RETENTION_DAYS reduzieren.
        </div>
      )}

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
                <span key={svc} className="bg-orange-100 px-2 py-0.5 rounded text-xs font-mono">
                  {svc}: {info.count}×
                </span>
              ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card title="Objekte aktuell" value={objs.length} />
        <Card title="Modell-Versionen" value={progress.versions.length} />
        <Card
          title="Letztes Training"
          value={lastTraining ?
            (lastTraining.timestamp_utc || '—').substring(0, 16) : '—'}
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
                .flatMap(([svc, d]) => {
                  const isSelected = selectedService === svc
                  return [
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
                        <span className="mr-1 text-gray-400">{isSelected ? '▾' : '▸'}</span>
                        {svc}
                        {d.public_url && (
                          <a
                            href={d.public_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={e => e.stopPropagation()}
                            className="ml-2 text-blue-500 hover:text-blue-700 text-xs"
                            title={`Öffentliche Quelle: ${d.public_url}`}
                          >🌐</a>
                        )}
                      </td>
                      <td className="p-1 text-right">{d.calls}</td>
                      <td className={`p-1 text-right ${d.errors > 0 ? 'text-red-600 font-semibold' : 'text-gray-400'}`}>
                        {d.errors}
                      </td>
                      <td className="p-1 text-right text-xs text-gray-500">
                        {d.calls > 0
                          ? `${((d.errors / d.calls) * 100).toFixed(1)}%`
                          : '—'}
                      </td>
                    </tr>,
                  ].filter(Boolean)
                })}
            </tbody>
          </table>
          <div className="mt-3">
            <h3 className="font-semibold mb-2">Letzter API-Request / Response</h3>
            <ApiLastRequestResponse service={selectedService} />
          </div>
        </div>
      )}
    </div>
  )
}
