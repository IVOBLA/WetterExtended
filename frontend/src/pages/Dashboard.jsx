import React, { useEffect, useState } from 'react'
import api from '../api.js'

function Card({ title, value, subtitle }) {
  return (
    <div className="card">
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

  useEffect(() => {
    Promise.all([
      api.get('/api/objects').then(setObjs).catch(() => setObjs([])),
      api.get('/api/progress').then(setProgress).catch(() => setProgress({ versions: [] })),
      api.get('/api/git').then(setGit).catch(() => {}),
    ])
  }, [])

  const lastTraining = progress.versions[progress.versions.length - 1]

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Dashboard</h1>
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card title="Objekte aktuell" value={objs.length} />
        <Card title="Modell-Versionen" value={progress.versions.length} />
        <Card
          title="Letztes Training"
          value={lastTraining ? (lastTraining.timestamp_utc || '—').substring(0, 16) : '—'}
          subtitle={lastTraining?.validation?.status}
        />
        <Card title="Git" value={git.branch || '—'} subtitle={git.commit} />
      </div>
    </div>
  )
}
