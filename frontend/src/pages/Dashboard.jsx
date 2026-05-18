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

export default function Dashboard() {
  const [objs, setObjs] = useState([])
  const [progress, setProgress] = useState({ versions: [] })
  const [git, setGit] = useState({})
  const [disk, setDisk] = useState(null)

  useEffect(() => {
    Promise.all([
      api.get('/api/objects').then(setObjs).catch(() => setObjs([])),
      api.get('/api/progress').then(setProgress).catch(() => setProgress({ versions: [] })),
      api.get('/api/git').then(setGit).catch(() => {}),
      api.get('/api/disk').then(setDisk).catch(() => setDisk(null)),
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

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Dashboard</h1>

      {disk?.critical && (
        <div className="bg-red-100 border border-red-400 text-red-900 p-3 rounded mb-4 text-sm">
          <strong>⚠ Kritischer Speicherstand:</strong> {disk.used_pct}% belegt —
          Daten-Cleanup prüfen oder DATA_RETENTION_DAYS reduzieren.
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card title="Objekte aktuell" value={objs.length} />
        <Card title="Modell-Versionen" value={progress.versions.length} />
        <Card
          title="Letztes Training"
          value={lastTraining ? (lastTraining.timestamp_utc || '—').substring(0, 16) : '—'}
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
    </div>
  )
}
