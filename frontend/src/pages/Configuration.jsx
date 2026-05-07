import React, { useEffect, useState } from 'react'
import api from '../api.js'

export default function Configuration() {
  const [text, setText] = useState('')
  const [msg, setMsg] = useState('')

  useEffect(() => {
    api.get('/api/config').then(d => setText(JSON.stringify(d, null, 2))).catch(() => {})
  }, [])

  async function save() {
    try {
      const data = JSON.parse(text)
      await api.post('/api/config', data)
      setMsg('Gespeichert.')
    } catch (e) { setMsg('Fehler: ' + e.message) }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Konfiguration (vollständig)</h1>
      {msg && <div className="bg-blue-100 border border-blue-300 text-blue-900 p-2 rounded mb-3 text-sm">{msg}</div>}
      <textarea className="input font-mono" rows="30" value={text} onChange={e => setText(e.target.value)} />
      <button className="btn-primary mt-3" onClick={save}>Speichern</button>
      <p className="text-sm text-gray-500 mt-2">
        Vorsicht: hier kann die ganze Konfiguration manipuliert werden.
        Bei Bedarf einzelne Seiten (Orte, Schwellwerte, Training, Horizonte) verwenden.
      </p>
    </div>
  )
}
