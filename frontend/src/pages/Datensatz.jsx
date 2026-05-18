import React, { useEffect, useState } from 'react'
import api from '../api.js'

function StatCard({ title, value, sub }) {
  return (
    <div className="card">
      <div className="text-xs text-gray-500 uppercase tracking-wide">{title}</div>
      <div className="text-2xl font-semibold mt-1">{value ?? '—'}</div>
      {sub && <div className="text-xs text-gray-400 mt-1">{sub}</div>}
    </div>
  )
}

export default function Datensatz() {
  const [stats, setStats] = useState(null)
  const [frames, setFrames] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      api.get('/api/dataset_stats').then(setStats).catch(() => {}),
      api.get('/api/recent_frames?n=30').then(setFrames).catch(() => {}),
    ]).finally(() => setLoading(false))
  }, [])

  if (loading) {
    return <div className="text-gray-500 text-sm">Lade Datensatz-Info...</div>
  }

  const cleanup = stats?.last_cleanup
  const firstDay = stats?.first_frame?.substring(0, 10) ?? '—'
  const lastDay = stats?.last_frame?.substring(0, 10) ?? '—'

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Datensatz &amp; Trainingsdaten</h1>

      {/* Statistik-Karten */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <StatCard
          title="Gesammelte Frames"
          value={stats?.object_files?.toLocaleString()}
          sub={`${firstDay} → ${lastDay}`}
        />
        <StatCard
          title="Dataset-Samples"
          value={stats?.dataset_samples?.toLocaleString()}
          sub={stats?.dataset_features ? `${stats.dataset_features} Features` : 'noch kein Dataset'}
        />
        <StatCard
          title="Letzter Cleanup"
          value={cleanup ? `${cleanup.deleted_count} Dateien` : '—'}
          sub={cleanup ? `${cleanup.freed_mb} MB freigegeben · ${cleanup.ts_utc?.substring(0, 16)}` : 'noch kein Cleanup'}
        />
        <StatCard
          title="Letzter Frame"
          value={stats?.last_frame?.substring(11, 19) ?? '—'}
          sub={stats?.last_frame?.substring(0, 10)}
        />
      </div>

      {/* Hinweis wenn noch keine Daten */}
      {(!stats?.object_files || stats.object_files === 0) && (
        <div className="bg-yellow-50 border border-yellow-300 text-yellow-900 p-3 rounded mb-4 text-sm">
          Noch keine Frames gesammelt. Der Live-Loop muss mindestens einen Zyklus
          durchgelaufen sein und eine Gewitterzelle erkannt haben.
        </div>
      )}

      {/* Dataset-Hinweis */}
      {stats?.object_files > 0 && stats?.dataset_samples === 0 && (
        <div className="bg-blue-50 border border-blue-300 text-blue-900 p-3 rounded mb-4 text-sm">
          Frames vorhanden, aber noch kein Dataset gebaut. Der Scheduler führt
          <code className="mx-1 bg-blue-100 px-1 rounded">dataset_builder</code>
          automatisch alle {/* interval */} Minuten aus. Manuell:
          <code className="ml-1 bg-blue-100 px-1 rounded">python3 dataset_builder.py</code>
        </div>
      )}

      {/* Frame-Historik */}
      <div className="card">
        <h2 className="text-lg font-semibold mb-3">
          Letzte Frames ({frames.length})
        </h2>
        {frames.length === 0 ? (
          <div className="text-sm text-gray-500">Keine Frames vorhanden.</div>
        ) : (
          <div className="overflow-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-gray-500 uppercase">
                  <th className="p-2">Timestamp</th>
                  <th className="p-2 text-center">Zellen</th>
                  <th className="p-2">Zell-IDs</th>
                  <th className="p-2">Forecast-Mode</th>
                </tr>
              </thead>
              <tbody>
                {frames.map((f, i) => (
                  <tr key={i} className={`border-b ${f.count === 0 ? 'text-gray-400' : ''}`}>
                    <td className="p-2 font-mono text-xs">{f.ts}</td>
                    <td className="p-2 text-center">
                      <span className={`font-semibold ${f.count > 0 ? 'text-blue-700' : 'text-gray-400'}`}>
                        {f.count}
                      </span>
                    </td>
                    <td className="p-2 text-xs text-gray-600">
                      {f.ids.length > 0
                        ? f.ids.slice(0, 6).join(', ') + (f.ids.length > 6 ? ` +${f.ids.length - 6}` : '')
                        : <span className="text-gray-300">—</span>}
                    </td>
                    <td className="p-2">
                      {f.modes.map((m) => (
                        <span
                          key={m}
                          className={`text-xs px-1.5 py-0.5 rounded mr-1 ${
                            m === 'ml'
                              ? 'bg-green-100 text-green-800'
                              : m === 'kinematic'
                                ? 'bg-gray-100 text-gray-600'
                                : 'bg-yellow-100 text-yellow-800'
                          }`}
                        >
                          {m}
                        </span>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
