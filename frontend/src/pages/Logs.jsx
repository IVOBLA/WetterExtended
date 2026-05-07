import React, { useEffect, useState } from 'react'
import api from '../api.js'

export default function Logs() {
  const [logs, setLogs] = useState({ wetterprojekt: [], scheduler: [], admin: [] })
  const [active, setActive] = useState('wetterprojekt')

  async function load() {
    try { setLogs(await api.get('/api/logs')) }
    catch (e) { console.error(e) }
  }

  useEffect(() => {
    load()
    const t = setInterval(load, 30000)
    return () => clearInterval(t)
  }, [])

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Logs (Auto-Refresh 30s)</h1>
      <div className="flex gap-2 mb-3">
        {['wetterprojekt', 'scheduler', 'admin'].map(k => (
          <button key={k} onClick={() => setActive(k)}
            className={active === k ? 'btn-primary' : 'btn-secondary'}>
            {k}
          </button>
        ))}
        <button onClick={load} className="btn-secondary">Reload</button>
      </div>
      <pre className="bg-slate-900 text-slate-100 p-3 rounded overflow-auto" style={{ maxHeight: '70vh' }}>
        {(logs[active] || []).join('\n')}
      </pre>
    </div>
  )
}
