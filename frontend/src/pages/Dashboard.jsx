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

/** Detail-Panel für einen API-Service (letzte Requests) */
function ApiDetailPanel({ service, onClose }) {
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    api.get(`/api/api_calls/detail?service=${encodeURIComponent(service)}&n=15`)
      .then(d => { setDetail(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [service])

  return (
    <tr>
      <td colSpan={4} className="p-0">
        <div className="bg-gray-50 border border-gray-200 rounded m-1 p-3 text-xs">
          <div className="flex justify-between items-center mb-2">
            <span className="font-semibold text-sm font-mono">{service}</span>
            <div className="flex items-center gap-3">
              {detail?.public_url && (
                <a
                  href={detail.public_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 underline text-xs"
                >
                  🌐 Öffentliche Datenquelle →
                </a>
              )}
              <button
                onClick={onClose}
                className="text-gray-400 hover:text-gray-700 font-bold text-base leading-none"
              >×</button>
            </div>
          </div>
          {loading ? (
            <div className="text-gray-400">Lade Details…</div>
          ) : !detail || detail.entries.length === 0 ? (
            <div className="text-gray-400">Keine Einträge im gewählten Zeitraum.</div>
          ) : (
            <table className="w-full">
              <thead>
                <tr className="border-b text-gray-500 uppercase">
                  <th className="p-1 text-left">Zeitstempel (UTC)</th>
                  <th className="p-1 text-center">Status</th>
                  <th className="p-1 text-left">Dauer</th>
                  <th className="p-1 text-left">URL</th>
                </tr>
              </thead>
              <tbody>
                {detail.entries.map((e, i) => (
                  <tr key={i} className="border-b last:border-0">
                    <td className="p-1 whitespace-nowrap">{(e.ts || '').replace('T', ' ').substring(0, 19)}</td>
                    <td className={`p-1 text-center font-semibold ${
                      e.status >= 400 ? 'text-red-600' : e.status >= 300 ? 'text-yellow-600' : 'text-green-600'
                    }`}>{e.status}</td>
                    <td className="p-1 text-gray-500">
                      {e.duration_ms != null ? `${e.duration_ms} ms` : '—'}
                    </td>
                    <td className="p-1 font-mono break-all max-w-xs"
                        title={e.url}>{(e.url || '').substring(0, 100)}{(e.url||'').length > 100 ? '…' : ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {detail && (
            <div className="mt-2 text-gray-400">
              {detail.total} Einträge in den letzten 24h
            </div>
          )}
        </div>
      </td>
    </tr>
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
              — Zeile klicken für Details
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
                      title="Klick für letzte Request-Details"
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
                    isSelected
                      ? <ApiDetailPanel key={`${svc}-detail`} service={svc} onClose={() => setSelectedService(null)} />
                      : null,
                  ].filter(Boolean)
                })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
