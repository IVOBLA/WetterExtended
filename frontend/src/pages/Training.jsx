import React, { useEffect, useState } from 'react'
import api from '../api.js'

export default function Training() {
  const [s, setS] = useState({
    retrain_interval_hours: 6, retrain_cron_hour: 3, retrain_cron_minute: 0,
    convlstm_cron_day_of_week: 'mon', convlstm_cron_hour: 2, convlstm_cron_minute: 0,
  })
  const [rebuild, setRebuild] = useState(60)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    api.get('/api/training').then(d => {
      if (d.TRAINING_SCHEDULE) setS(d.TRAINING_SCHEDULE)
      if (d.DATASET_REBUILD_INTERVAL_MIN) setRebuild(d.DATASET_REBUILD_INTERVAL_MIN)
    }).catch(() => {})
  }, [])

  async function save() {
    try {
      await api.post('/api/training', { TRAINING_SCHEDULE: s, DATASET_REBUILD_INTERVAL_MIN: rebuild })
      setMsg('Gespeichert. Bitte Service neu starten: sudo systemctl restart wetterprojekt-scheduler')
    } catch (e) { setMsg('Fehler: ' + e.message) }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Trainings-Schedule</h1>
      {msg && <div className="bg-blue-100 border border-blue-300 text-blue-900 p-2 rounded mb-3 text-sm">{msg}</div>}
      <div className="card grid grid-cols-1 md:grid-cols-3 gap-4">
        <div><label className="label">Datensatz-Rebuild (Min.)</label>
          <input className="input" type="number" value={rebuild} onChange={e => setRebuild(parseInt(e.target.value) || 60)} /></div>
        <div><label className="label">Retrain-Interval (Stunden)</label>
          <input className="input" type="number" value={s.retrain_interval_hours} onChange={e => setS({ ...s, retrain_interval_hours: parseInt(e.target.value) || 6 })} /></div>
        <div></div>
        <div><label className="label">Nightly Retrain Stunde</label>
          <input className="input" type="number" min="0" max="23" value={s.retrain_cron_hour} onChange={e => setS({ ...s, retrain_cron_hour: parseInt(e.target.value) || 0 })} /></div>
        <div><label className="label">Nightly Retrain Minute</label>
          <input className="input" type="number" min="0" max="59" value={s.retrain_cron_minute} onChange={e => setS({ ...s, retrain_cron_minute: parseInt(e.target.value) || 0 })} /></div>
        <div></div>
        <div><label className="label">ConvLSTM Tag</label>
          <select className="input" value={s.convlstm_cron_day_of_week} onChange={e => setS({ ...s, convlstm_cron_day_of_week: e.target.value })}>
            {['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'].map(d => <option key={d}>{d}</option>)}
          </select></div>
        <div><label className="label">ConvLSTM Stunde</label>
          <input className="input" type="number" min="0" max="23" value={s.convlstm_cron_hour} onChange={e => setS({ ...s, convlstm_cron_hour: parseInt(e.target.value) || 0 })} /></div>
        <div><label className="label">ConvLSTM Minute</label>
          <input className="input" type="number" min="0" max="59" value={s.convlstm_cron_minute} onChange={e => setS({ ...s, convlstm_cron_minute: parseInt(e.target.value) || 0 })} /></div>
      </div>
      <button className="btn-primary mt-4" onClick={save}>Speichern</button>
      <p className="text-sm text-gray-500 mt-2">Hinweis: Änderungen werden erst nach Neustart von wetterprojekt-scheduler aktiv.</p>
    </div>
  )
}
