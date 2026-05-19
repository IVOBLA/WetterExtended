import React, { useEffect, useState } from 'react'
import api from '../api.js'

function ClaudeCodeBlock({ content }) {
  const [copied, setCopied] = React.useState(false)
  function copy() {
    navigator.clipboard.writeText(content).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }
  return (
    <div className="border border-gray-300 rounded-lg overflow-hidden text-sm">
      <div className="flex items-center justify-between px-3 py-2
                      bg-gray-800 text-gray-200">
        <span className="font-mono font-semibold text-xs tracking-wide">
          ⚡ Claude Code Prompt
        </span>
        <button
          onClick={copy}
          className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
            copied
              ? 'bg-green-600 text-white'
              : 'bg-gray-600 hover:bg-gray-500 text-gray-200'
          }`}
        >
          {copied ? '✓ Kopiert!' : 'Kopieren'}
        </button>
      </div>
      <pre className="p-4 bg-gray-900 text-gray-100 text-xs leading-relaxed
                      overflow-x-auto whitespace-pre-wrap">
        {content}
      </pre>
    </div>
  )
}

const PRIORITY_COLOR = {
  high: 'bg-red-100 border-red-400 text-red-800',
  medium: 'bg-yellow-100 border-yellow-400 text-yellow-800',
  low: 'bg-blue-100 border-blue-400 text-blue-800',
}
const CATEGORY_ICON = {
  accuracy: '🎯', api: '🌐', model: '🤖',
  data: '📊', system: '💻', config: '⚙️',
}
const STATUS_COLOR = {
  ok: 'text-green-700', warning: 'text-yellow-700', critical: 'text-red-700',
}

export default function AiSuggestions() {
  const [cfg, setCfg] = useState({
    enabled: false, cron_hour: 6, cron_minute: 0,
    since_hours: 24, max_tokens: 3000,
  })
  const [suggestions, setSuggestions] = useState([])
  const [running, setRunning] = useState(false)
  const [msg, setMsg] = useState('')
  const [saved, setSaved] = useState(false)
  const [models,         setModels]         = useState([])
  const [selectedModel,  setSelectedModel]  = useState('claude-sonnet-4-6')
  const [includeData,    setIncludeData]    = useState(true)
  const [includeSource,  setIncludeSource]  = useState(false)
  const [chatQuestion,   setChatQuestion]   = useState('')
  const [chatAnswer,     setChatAnswer]     = useState(null)
  const [chatLoading,    setChatLoading]    = useState(false)
  const [chatError,      setChatError]      = useState(null)
  const [chatImages,     setChatImages]     = useState([])   // [{name,media_type,data,url}]
  const [dragOver,       setDragOver]       = useState(false)
  const fileInputRef = React.useRef(null)

  useEffect(() => {
    api.get('/api/ai_analysis/config').then(setCfg).catch(() => {})
    api.get('/api/ai_analysis/suggestions?n=5').then(d => {
      setSuggestions(d.suggestions || [])
    }).catch(() => {})
    api.get('/api/ai_analysis/models')
      .then(d => setModels(d.models || []))
      .catch(() => {})
  }, [])

  async function saveCfg() {
    try {
      await api.post('/api/ai_analysis/config', cfg)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (e) { setMsg('Fehler: ' + e.message) }
  }

  async function runNow() {
    setRunning(true)
    setMsg('')
    try {
      const r = await api.post('/api/ai_analysis/run', {})
      if (r.ok) {
        setMsg('Analyse abgeschlossen.')
        api.get('/api/ai_analysis/suggestions?n=5').then(d => {
          setSuggestions(d.suggestions || [])
        }).catch(() => {})
      } else {
        setMsg('Fehler: ' + (r.error || 'unbekannt'))
      }
    } catch (e) {
      setMsg('Fehler: ' + e.message)
    }
    setRunning(false)
  }

  function _parseAnswer(raw) {
    // Zerlegt die KI-Antwort in Textabschnitte und claudecode-Bloecke.
    // Gibt Array von {type: 'text'|'claudecode', content: string} zurueck.
    const parts = []
    const pattern = /```claudecode\n([\s\S]*?)```/g
    let last = 0
    let match
    while ((match = pattern.exec(raw)) !== null) {
      if (match.index > last) {
        const txt = raw.slice(last, match.index).trim()
        if (txt) parts.push({ type: 'text', content: txt })
      }
      parts.push({ type: 'claudecode', content: match[1].trim() })
      last = match.index + match[0].length
    }
    const tail = raw.slice(last).trim()
    if (tail) parts.push({ type: 'text', content: tail })
    return parts.length ? parts : [{ type: 'text', content: raw }]
  }

  function _fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload  = () => resolve(reader.result.split(',')[1])
      reader.onerror = reject
      reader.readAsDataURL(file)
    })
  }

  async function addImages(files) {
    const allowed = Array.from(files).filter(f => f.type.startsWith('image/'))
    if (!allowed.length) return
    const remaining = 5 - chatImages.length
    const toAdd = allowed.slice(0, remaining)
    const entries = await Promise.all(toAdd.map(async f => ({
      name:       f.name,
      media_type: f.type,
      data:       await _fileToBase64(f),
      url:        URL.createObjectURL(f),
    })))
    setChatImages(prev => [...prev, ...entries])
  }

  function removeImage(idx) {
    setChatImages(prev => {
      URL.revokeObjectURL(prev[idx].url)
      return prev.filter((_, i) => i !== idx)
    })
  }

  function handleDrop(e) {
    e.preventDefault()
    setDragOver(false)
    addImages(e.dataTransfer.files)
  }

  async function sendChat() {
    if (!chatQuestion.trim()) return
    setChatLoading(true)
    setChatError(null)
    setChatAnswer(null)
    try {
      const r = await api.post('/api/ai_analysis/chat', {
        question:       chatQuestion,
        include_data:   includeData,
        include_source: includeSource,
        model:          selectedModel,
        images:         chatImages.map(({ media_type, data }) => ({ media_type, data })),
      })
      if (r.ok) {
        setChatAnswer(r.answer)
        setChatImages([])
      } else {
        setChatError(r.error || 'Unbekannter Fehler')
      }
    } catch (e) {
      setChatError(String(e))
    } finally {
      setChatLoading(false)
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">KI-Analyse (Anthropic)</h1>

      {msg && (
        <div className="bg-blue-50 border border-blue-300 text-blue-900 p-2 rounded mb-4 text-sm">
          {msg}
        </div>
      )}

      <div className="card mb-6">
        <h2 className="text-lg font-semibold mb-3">Konfiguration</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="flex items-center gap-3">
            <label className="label mb-0">Aktiviert</label>
            <button
              onClick={() => setCfg({ ...cfg, enabled: !cfg.enabled })}
              className={`px-4 py-1 rounded font-medium text-sm transition-colors ${
                cfg.enabled ? 'bg-green-600 text-white' : 'bg-gray-300 text-gray-700'
              }`}
            >
              {cfg.enabled ? 'EIN' : 'AUS'}
            </button>
          </div>
          <div>
            <label className="label">Datenfenster (Stunden)</label>
            <input className="input" type="number" min="1" max="168"
              value={cfg.since_hours}
              onChange={e => setCfg({ ...cfg, since_hours: parseInt(e.target.value) || 24 })} />
          </div>
          <div>
            <label className="label">Analyse-Uhrzeit (Stunde, 0–23)</label>
            <input className="input" type="number" min="0" max="23"
              value={cfg.cron_hour}
              onChange={e => setCfg({ ...cfg, cron_hour: parseInt(e.target.value) || 6 })} />
          </div>
          <div>
            <label className="label">Analyse-Uhrzeit (Minute)</label>
            <input className="input" type="number" min="0" max="59"
              value={cfg.cron_minute}
              onChange={e => setCfg({ ...cfg, cron_minute: parseInt(e.target.value) || 0 })} />
          </div>
          <div>
            <label className="label">Max. Tokens pro Analyse</label>
            <input className="input" type="number" min="500" max="4000" step="100"
              value={cfg.max_tokens}
              onChange={e => setCfg({ ...cfg, max_tokens: parseInt(e.target.value) || 3000 })} />
          </div>
        </div>
        <div className="flex gap-3 mt-4">
          <button className="btn-primary" onClick={saveCfg}>Speichern</button>
          <button className="btn-secondary" onClick={runNow} disabled={running}>
            {running ? 'Analyse läuft…' : 'Jetzt analysieren'}
          </button>
          {saved && <span className="text-green-700 text-sm self-center">✓ Gespeichert</span>}
        </div>
      </div>

      <div>
        <h2 className="text-lg font-semibold mb-3">Letzte Analysen ({suggestions.length})</h2>
        {suggestions.length === 0 ? (
          <div className="card text-sm text-gray-500">Noch keine Analyse-Ergebnisse vorhanden.</div>
        ) : (
          suggestions.map((entry, ei) => (
            <div key={ei} className="card mb-4">
              <div className="flex justify-between items-start mb-3">
                <div>
                  <span className={`font-semibold ${STATUS_COLOR[entry.overall_status] || ''}`}>
                    ● {entry.overall_status?.toUpperCase() || '?'}
                  </span>
                </div>
              </div>
              {(entry.suggestions || []).length === 0 ? (
                <div className="text-sm text-green-700">✓ Keine Probleme erkannt.</div>
              ) : (
                <div className="space-y-2">
                  {(entry.suggestions || []).map((s, si) => (
                    <div key={si} className={`border-l-4 p-3 rounded text-sm ${PRIORITY_COLOR[s.priority] || 'bg-gray-100'}`}>
                      <div className="flex gap-2 items-center font-medium mb-1">
                        <span>{CATEGORY_ICON[s.category] || '•'}</span>
                        <span>[{s.priority?.toUpperCase()}] {s.title}</span>
                      </div>
                      <div className="text-xs mb-1">{s.description}</div>
                      <div className="text-xs font-medium">→ {s.action}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {/* KI-Analyse Chat */}
      <div className="card mt-6">
        <h2 className="text-base font-semibold mb-3">🤖 KI-Analyse Chat</h2>

        <div className="flex flex-wrap gap-4 mb-3 text-sm">
          {/* Modell-Auswahl */}
          <label className="flex items-center gap-2">
            Modell:
            <select
              className="border rounded px-2 py-1 text-sm"
              value={selectedModel}
              onChange={e => setSelectedModel(e.target.value)}
            >
              {models.map(m => (
                <option key={m.id} value={m.id}>{m.label}</option>
              ))}
            </select>
          </label>

          {/* Kontext-Toggle */}
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={includeData}
              onChange={e => setIncludeData(e.target.checked)} />
            Metriken & Systemdaten (letzte 24h)
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={includeSource}
              onChange={e => setIncludeSource(e.target.checked)} />
            Quellcode einbeziehen
            <span className="text-xs text-gray-400">(langsamer)</span>
          </label>
        </div>

        {/* Bild-Upload — Drag & Drop Zone */}
        <div
          className={`mb-3 border-2 border-dashed rounded-lg p-3 text-sm text-center
                      transition-colors cursor-pointer
                      ${dragOver
                        ? 'border-blue-400 bg-blue-50'
                        : 'border-gray-300 hover:border-blue-300 hover:bg-gray-50'}`}
          onClick={() => fileInputRef.current?.click()}
          onDragOver={e => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            multiple
            className="hidden"
            onChange={e => addImages(e.target.files)}
          />
          {chatImages.length === 0 ? (
            <span className="text-gray-400">
              📎 Bilder hier ablegen oder klicken zum Auswählen
              <span className="block text-xs mt-1">PNG, JPG, WebP, GIF · max. 5 Bilder · max. 5 MB pro Bild</span>
            </span>
          ) : (
            <span className="text-blue-600 text-xs">
              + weitere Bilder hinzufügen ({chatImages.length}/5)
            </span>
          )}
        </div>

        {/* Bild-Vorschau */}
        {chatImages.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-3">
            {chatImages.map((img, idx) => (
              <div key={idx} className="relative group">
                <img
                  src={img.url}
                  alt={img.name}
                  className="h-20 w-20 object-cover rounded border border-gray-300"
                  title={img.name}
                />
                <button
                  onClick={() => removeImage(idx)}
                  className="absolute -top-1.5 -right-1.5 bg-red-500 text-white
                             rounded-full w-5 h-5 text-xs flex items-center justify-center
                             opacity-0 group-hover:opacity-100 transition-opacity"
                  title="Bild entfernen"
                >
                  ×
                </button>
                <div className="text-xs text-gray-400 text-center truncate w-20 mt-0.5">
                  {img.name}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Eingabe */}
        <div className="flex gap-2 items-end">
          <textarea
            className="flex-1 border rounded px-3 py-2 text-sm resize-y"
            style={{ minHeight: 80 }}
            placeholder={
              'Frage stellen, z.B.:\n' +
              '• Warum ist die Hit-Rate so niedrig?\n' +
              '• Was zeigt dieses Radar-Bild?\n' +
              '• Strg+Enter zum Senden'
            }
            value={chatQuestion}
            onChange={e => setChatQuestion(e.target.value)}
            onKeyDown={e => { if (e.ctrlKey && e.key === 'Enter') sendChat() }}
          />
          <button
            className="btn-primary px-5 py-2"
            onClick={sendChat}
            disabled={chatLoading || !chatQuestion.trim()}
          >
            {chatLoading
              ? '⏳…'
              : chatImages.length > 0
                ? `Senden (${chatImages.length} 🖼)`
                : 'Senden'}
          </button>
        </div>

        {/* Fehler */}
        {chatError && (
          <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
            ❌ {chatError}
          </div>
        )}

        {/* Antwort */}
        {chatAnswer && (
          <div className="mt-3 space-y-3">
            {_parseAnswer(chatAnswer).map((part, i) =>
              part.type === 'claudecode'
                ? <ClaudeCodeBlock key={i} content={part.content} />
                : (
                  <div key={i}
                       className="p-4 bg-green-50 border border-green-200 rounded text-sm
                                  whitespace-pre-wrap leading-relaxed">
                    {part.content}
                  </div>
                )
            )}
          </div>
        )}
      </div>


    </div>
  )
}
