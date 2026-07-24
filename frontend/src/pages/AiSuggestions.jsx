import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
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
    since_hours: 24, max_tokens: 3000, report_email: '',
    cron_days: 'mon,tue,wed,thu,fri,sat,sun',
    only_if_cells: false,
    full_source_mode: false,
  })
  // --- Claude-Code-Report (unabhängig von KI-Analyse) ---
  const [ccCfg, setCcCfg] = useState({
    enabled: true, cron_hour: 4, cron_minute: 0,
    branch: 'debug-export-latest', report_email: '',
  })
  const [ccSaved, setCcSaved] = useState(false)
  const [ccMsg, setCcMsg] = useState('')
  // --- Betriebsart + lokale Analyse am Pi (P81) ---
  const [mode,      setMode]      = useState({ mode: 'repo', changed: '', changed_today: false })
  const [modeMsg,   setModeMsg]   = useState('')
  const [laCfg, setLaCfg] = useState({
    cron_hour: 0, cron_minute: 10, max_turns: 40, timeout_s: 900, model: '',
  })
  const [laStatus,  setLaStatus]  = useState(null)
  const [laSaved,   setLaSaved]   = useState(false)
  const [laMsg,     setLaMsg]     = useState('')
  const [laRunning, setLaRunning] = useState(false)

  const [testEmailStatus, setTestEmailStatus] = useState(null)  // null | 'sending' | 'ok' | 'error'
  const [testEmailMsg,    setTestEmailMsg]    = useState('')
  const [suggestions, setSuggestions] = useState([])
  const [running, setRunning] = useState(false)
  const [msg, setMsg] = useState('')
  const [saved, setSaved] = useState(false)
  const [models,         setModels]         = useState([])
  const [selectedModel,  setSelectedModel]  = useState('claude-sonnet-4-6')
  const [includeData,    setIncludeData]    = useState(true)
  const [includeSource,  setIncludeSource]  = useState(false)
  const [sourceMode,     setSourceMode]     = useState('short')
  const [includeRadar,   setIncludeRadar]   = useState(false)
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
    api.get('/api/claude_code_report/config')
      .then(d => setCcCfg(prev => ({ ...prev, ...d })))
      .catch(() => {})
    api.get('/api/analysis_mode').then(setMode).catch(() => {})
    api.get('/api/local_analysis/config')
      .then(d => setLaCfg(prev => ({ ...prev, ...d })))
      .catch(() => {})
    api.get('/api/local_analysis/status').then(setLaStatus).catch(() => {})
  }, [])

  function refreshLaStatus() {
    api.get('/api/local_analysis/status').then(setLaStatus).catch(() => {})
  }

  async function saveMode(next) {
    setModeMsg('')
    try {
      await api.post('/api/analysis_mode', { mode: next })
      const d = await api.get('/api/analysis_mode')
      setMode(d)
      setModeMsg(d.changed_today
        ? 'Umgestellt. Der erste automatische Lauf findet morgen statt.'
        : 'Betriebsart gespeichert.')
      refreshLaStatus()
    } catch (e) {
      setModeMsg('Fehler: ' + e.message)
    }
  }

  async function saveLaCfg() {
    setLaMsg('')
    try {
      await api.post('/api/local_analysis/config', laCfg)
      setLaSaved(true)
      setTimeout(() => setLaSaved(false), 3000)
      refreshLaStatus()
    } catch (e) {
      setLaMsg('Fehler: ' + e.message)
    }
  }

  async function runLocalAnalysis() {
    setLaMsg('')
    setLaRunning(true)
    try {
      await api.post('/api/system/run_job/local_analysis', {})
    } catch (e) {
      setLaRunning(false)
      setLaMsg('Start fehlgeschlagen: ' + e.message)
      return
    }
    // Der Lauf dauert bis zu 15 Minuten — Status alle 5 s abfragen,
    // nach 20 Minuten aufgeben, damit kein Intervall ewig weiterlaeuft.
    let ticks = 0
    const poll = setInterval(async () => {
      ticks += 1
      if (ticks > 240) {
        clearInterval(poll)
        setLaRunning(false)
        setLaMsg('Zeitueberschreitung — Status manuell pruefen')
        return
      }
      try {
        const s = await api.get('/api/system/job_status')
        const run = (s.runs || {}).local_analysis
        if (run && run.state !== 'running') {
          clearInterval(poll)
          setLaRunning(false)
          setLaMsg(run.state === 'ok'
            ? 'Fertig: ' + (run.message || '')
            : 'Fehlgeschlagen: ' + (run.message || ''))
          refreshLaStatus()
        }
      } catch { /* naechster Versuch */ }
    }, 5000)
  }

  async function saveCfg() {
    try {
      await api.post('/api/ai_analysis/config', cfg)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (e) { setMsg('Fehler: ' + e.message) }
  }

  async function testEmail() {
    setTestEmailStatus('sending')
    setTestEmailMsg('')
    try {
      const r = await api.post('/api/ai_analysis/test_email', {
        report_email: cfg.report_email || '',
      })
      setTestEmailStatus(r.ok ? 'ok' : 'error')
      setTestEmailMsg(r.ok ? r.message : (r.error || 'Fehler'))
    } catch (e) {
      setTestEmailStatus('error')
      setTestEmailMsg(e.message)
    }
    setTimeout(() => setTestEmailStatus(null), 6000)
  }

  async function runNow() {
    setRunning(true)
    setMsg('')
    try {
      const r = await api.post('/api/ai_analysis/run', {
        source_mode: cfg.full_source_mode ? 'full' : 'short',
      })
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

  // Claude-API unterstützt nur diese Bild-Formate:
  const CLAUDE_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']

  async function addImages(files) {
    const arr = Array.from(files)
    const allowed = arr.filter(f => CLAUDE_IMAGE_TYPES.includes(f.type))
    const rejected = arr.filter(f => !CLAUDE_IMAGE_TYPES.includes(f.type))
    if (rejected.length) {
      alert(
        'Nicht unterstützte Formate übersprungen: '
        + rejected.map(f => f.name).join(', ')
        + '\nErlaubt: JPEG, PNG, GIF, WebP.'
      )
    }
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
        source_mode:    sourceMode,
        include_radar:  includeRadar,
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
          <div className="md:col-span-2">
            <label className="flex items-center gap-3 cursor-pointer select-none">
              <div
                onClick={() => setCfg({ ...cfg, only_if_cells: !cfg.only_if_cells })}
                className={`w-11 h-6 rounded-full transition-colors flex items-center px-0.5
                  ${cfg.only_if_cells ? 'bg-blue-600' : 'bg-gray-300'}`}
              >
                <div className={`w-5 h-5 rounded-full bg-white shadow transition-transform
                  ${cfg.only_if_cells ? 'translate-x-5' : 'translate-x-0'}`} />
              </div>
              <div>
                <span className="font-medium text-sm">
                  Nur ausführen wenn heute Sturmzellen erkannt wurden
                </span>
                <p className="text-xs text-gray-400 mt-0.5">
                  An ruhigen Tagen ohne Radar-Treffer wird die Analyse (und E-Mail)
                  übersprungen. Spart API-Kosten.
                </p>
              </div>
            </label>
          </div>
          <div className="md:col-span-2 flex items-center gap-3 pt-1">
            <label className="flex items-center gap-2 cursor-pointer text-sm">
              <input
                type="checkbox"
                checked={!!cfg.full_source_mode}
                onChange={e => setCfg({ ...cfg, full_source_mode: e.target.checked })}
              />
              <span className="font-medium">Vollständiger Quellcode im Analyse-Lauf</span>
              <span className="text-xs text-gray-400">
                (alle Zeilen statt max. 120/Datei — mehr Tokens, genauere Code-Analyse)
              </span>
            </label>
          </div>
        </div>
        <div className="mt-3">
          <label className="label">Report-E-Mail</label>
          <div className="flex gap-2 items-center">
            <input
              className="input flex-1"
              type="email"
              placeholder="bericht@example.com (leer = kein E-Mail-Versand)"
              value={cfg.report_email || ''}
              onChange={e => setCfg({ ...cfg, report_email: e.target.value })}
            />
            <button
              className="btn-secondary whitespace-nowrap"
              onClick={testEmail}
              disabled={testEmailStatus === 'sending' || !cfg.report_email}
              title={!cfg.report_email ? 'Zuerst E-Mail-Adresse eingeben und speichern' : ''}
            >
              {testEmailStatus === 'sending' ? '⟳ Sende…' : '✉ Test senden'}
            </button>
          </div>
          {testEmailStatus === 'ok' && (
            <div className="text-green-700 text-xs mt-1">✓ {testEmailMsg}</div>
          )}
          {testEmailStatus === 'error' && (
            <div className="text-red-600 text-xs mt-1">✗ {testEmailMsg}</div>
          )}
          <p className="text-xs text-gray-400 mt-1">
            Nach jeder abgeschlossenen KI-Analyse wird der Report automatisch an diese Adresse gesendet.
          </p>
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

      {/* HitL — Filterkriterien-Analyse (Shortcut zur Filter-Galerie) */}
      <FilterCriteriaAnalysis />

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
          {includeSource && (
            <div className="flex items-center gap-3 ml-2 text-sm">
              <label className="flex items-center gap-1">
                <input type="radio" name="sourceMode" value="short"
                  checked={sourceMode === 'short'}
                  onChange={() => setSourceMode('short')} />
                Gekürzt ({`<`}120 Zeilen/Datei)
              </label>
              <label className="flex items-center gap-1">
                <input type="radio" name="sourceMode" value="full"
                  checked={sourceMode === 'full'}
                  onChange={() => setSourceMode('full')} />
                Vollständig (mehr Token)
              </label>
            </div>
          )}
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={includeRadar}
              onChange={e => setIncludeRadar(e.target.checked)} />
            Aktuelles Radarbild senden
            <span className="text-xs text-gray-400">(letztes ARSO-Frame)</span>
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
            accept="image/jpeg,image/png,image/gif,image/webp"
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


      {/* ═══════════════════════════════════════════════════════════════════
          Betriebsart der täglichen Analyse (P81) — genau EINE Analyse pro Tag
          ═════════════════════════════════════════════════════════════════ */}
      <div className="card mt-8 border-t-4 border-indigo-500">
        <h2 className="text-lg font-semibold mb-1">
          ⚙️ Betriebsart der täglichen Analyse
        </h2>
        <p className="text-sm text-gray-500 mb-4">
          Es läuft <strong>genau eine</strong> Analyse pro Tag. Die beiden Wege
          schließen einander aus — ein gleichzeitiger Betrieb ist bewusst nicht
          einstellbar.
        </p>

        <div className="space-y-3">
          {[
            {
              value: 'repo',
              titel: 'Über das Repository (extern)',
              text: 'Der Debug-Export wird um 23:59 nach GitHub gepusht und dort von '
                  + 'der externen Claude-Code-Routine analysiert. Die Mail liest das '
                  + 'Ergebnis aus dem Branch.',
            },
            {
              value: 'local',
              titel: 'Direkt am Pi',
              text: 'Die Analyse läuft nachts auf diesem Gerät und sieht dadurch auch '
                  + 'Live-Zustände (Dienste, Datenbank-Integrität, Dateifrische). Der '
                  + 'Debug-Export wird dann nicht mehr gepusht; der Download im '
                  + 'Admin-Panel bleibt erhalten.',
            },
          ].map(opt => (
            <label
              key={opt.value}
              className={`flex gap-3 items-start p-3 rounded border cursor-pointer
                ${mode.mode === opt.value
                  ? 'border-indigo-500 bg-indigo-50'
                  : 'border-gray-200 hover:bg-gray-50'}`}
            >
              <input
                type="radio"
                className="mt-1"
                name="analysis_mode"
                checked={mode.mode === opt.value}
                onChange={() => saveMode(opt.value)}
              />
              <span>
                <span className="font-medium text-sm">{opt.titel}</span>
                <span className="block text-xs text-gray-500 mt-0.5">{opt.text}</span>
              </span>
            </label>
          ))}
        </div>

        {mode.mode === 'local' && (
          <div className="mt-4 rounded border border-amber-300 bg-amber-50 p-3 text-sm">
            <strong>Externe Routine jetzt abschalten.</strong> Sie läuft auf
            Anthropic-Servern und kann von diesem Gerät aus nicht gestoppt werden.
            Bleibt sie aktiv, laufen zwei Analysen pro Tag.
          </div>
        )}
        {mode.changed_today && (
          <p className="text-xs text-gray-500 mt-2">
            Heute umgestellt ({mode.changed}) — der erste automatische Lauf findet
            morgen statt. „Jetzt ausführen" geht sofort.
          </p>
        )}
        {modeMsg && (
          <p className="text-sm text-gray-700 mt-2">{modeMsg}</p>
        )}
      </div>


      {/* ═══════════════════════════════════════════════════════════════════
          Claude-Code-Analyse-Report  –  vollständig unabhängige Konfiguration
          ═════════════════════════════════════════════════════════════════ */}
      <div className="card mt-8 border-t-4 border-purple-500">
        <h2 className="text-lg font-semibold mb-1">
          📊 Code-Analyse-Report (Claude Code)
        </h2>
        <p className="text-sm text-gray-500 mb-4">
          Versendet täglich{' '}
          <code className="text-xs bg-gray-100 px-1 rounded">analysis_result.json</code>{' '}
          per E-Mail. Die Quelle ergibt sich aus der Betriebsart oben:{' '}
          {mode.mode === 'local' ? (
            <>lokale Datei vom Pi.</>
          ) : (
            <>Branch{' '}
              <code className="text-xs bg-gray-100 px-1 rounded">
                {ccCfg.branch || 'debug-export-latest'}
              </code>.
            </>
          )}{' '}
          Unabhängig von der KI-Analyse-Pipeline.
        </p>
        {mode.mode === 'local' &&
          (laCfg.cron_hour * 60 + laCfg.cron_minute) >=
          (ccCfg.cron_hour * 60 + ccCfg.cron_minute) && (
          <p className="text-xs text-amber-700 mb-3">
            ⚠ Die Analyse startet nicht vor dem Versand — verschickt würde das
            Ergebnis des Vortages. Analysezeit früher legen.
          </p>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="md:col-span-2">
            <label className="flex items-center gap-3 cursor-pointer select-none">
              <div
                onClick={() => setCcCfg({ ...ccCfg, enabled: !ccCfg.enabled })}
                className={`w-11 h-6 rounded-full transition-colors flex items-center px-0.5
                  ${ccCfg.enabled ? 'bg-purple-600' : 'bg-gray-300'}`}
              >
                <div className={`w-5 h-5 rounded-full bg-white shadow transition-transform
                  ${ccCfg.enabled ? 'translate-x-5' : 'translate-x-0'}`} />
              </div>
              <div>
                <span className="font-medium text-sm">
                  Code-Analyse-Report aktiviert
                </span>
                <p className="text-xs text-gray-400 mt-0.5">
                  Täglich um {String(ccCfg.cron_hour).padStart(2, '0')}:
                  {String(ccCfg.cron_minute).padStart(2, '0')} Uhr (Europe/Vienna)
                </p>
              </div>
            </label>
          </div>

          <div>
            <label className="label">Versand-Stunde (0–23)</label>
            <input
              className="input"
              type="number" min="0" max="23"
              value={ccCfg.cron_hour}
              onChange={e => {
                const value = parseInt(e.target.value, 10)
                setCcCfg({ ...ccCfg, cron_hour: Number.isNaN(value) ? 4 : value })
              }}
            />
          </div>
          <div>
            <label className="label">Versand-Minute (0–59)</label>
            <input
              className="input"
              type="number" min="0" max="59"
              value={ccCfg.cron_minute}
              onChange={e => {
                const value = parseInt(e.target.value, 10)
                setCcCfg({ ...ccCfg, cron_minute: Number.isNaN(value) ? 0 : value })
              }}
            />
          </div>

          <div className="md:col-span-2">
            <label className="label">Report-E-Mail</label>
            <input
              className="input"
              type="email"
              placeholder="analyse@example.com (leer = kein Versand)"
              value={ccCfg.report_email || ''}
              onChange={e => setCcCfg({ ...ccCfg, report_email: e.target.value })}
            />
            <p className="text-xs text-gray-400 mt-1">
              Unabhängig von der Report-E-Mail der KI-Analyse.
              SMTP-Konfiguration wird geteilt (.env).
            </p>
          </div>
        </div>

        <div className="flex gap-3 mt-4">
          <button
            className="btn-primary"
            onClick={async () => {
              setCcMsg('')
              try {
                await api.post('/api/claude_code_report/config', ccCfg)
                setCcSaved(true)
                setTimeout(() => setCcSaved(false), 3000)
              } catch (e) {
                setCcMsg('Fehler: ' + e.message)
              }
            }}
          >
            Speichern
          </button>
          {ccSaved && (
            <span className="text-green-700 text-sm self-center">✓ Gespeichert</span>
          )}
          {ccMsg && (
            <span className="text-red-600 text-sm self-center">{ccMsg}</span>
          )}
        </div>
      </div>


      {/* ═══════════════════════════════════════════════════════════════════
          Lokale Analyse am Pi (P81)
          ═════════════════════════════════════════════════════════════════ */}
      <div className="card mt-8 border-t-4 border-emerald-500">
        <h2 className="text-lg font-semibold mb-1">
          🧠 Lokale Analyse am Pi (Claude Code)
        </h2>
        <p className="text-sm text-gray-500 mb-4">
          Prueft: Dienste, Journal, SQLite-Integritaet, Frische der Statusdateien
          und die Arbeitsanweisungen aus{' '}
          <code className="text-xs bg-gray-100 px-1 rounded">AIChecks.md</code>.
          Der Lauf ist streng lesend.{' '}
          {mode.mode === 'local'
            ? 'Aktiv — laeuft naechtlich.'
            : 'Inaktiv — oben auf „Direkt am Pi" umstellen, um sie zu nutzen.'}
        </p>

        {laStatus && !laStatus.cli_available && (
          <div className="mb-4 rounded border border-amber-300 bg-amber-50 p-3 text-sm">
            <strong>Claude-Code-CLI nicht gefunden.</strong> Auf dem Pi installieren:
            <code className="block mt-1 text-xs bg-white px-2 py-1 rounded">
              curl -fsSL https://claude.ai/install.sh | bash -s stable
            </code>
            Danach einmal <code className="text-xs">claude</code> interaktiv starten und
            anmelden — ohne Anmeldung bleibt jeder Lauf erfolglos.
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="label">Faellig ab Stunde (0–23)</label>
            <input className="input" type="number" min="0" max="23"
              value={laCfg.cron_hour}
              onChange={e => {
                const v = parseInt(e.target.value, 10)
                setLaCfg({ ...laCfg, cron_hour: Number.isNaN(v) ? 0 : v })
              }}
            />
          </div>
          <div>
            <label className="label">Faellig ab Minute (0–59)</label>
            <input className="input" type="number" min="0" max="59"
              value={laCfg.cron_minute}
              onChange={e => {
                const v = parseInt(e.target.value, 10)
                setLaCfg({ ...laCfg, cron_minute: Number.isNaN(v) ? 10 : v })
              }}
            />
          </div>
          <div>
            <label className="label">Max. Arbeitsschritte (1–200)</label>
            <input className="input" type="number" min="1" max="200"
              value={laCfg.max_turns}
              onChange={e => {
                const v = parseInt(e.target.value, 10)
                setLaCfg({ ...laCfg, max_turns: Number.isNaN(v) ? 40 : v })
              }}
            />
          </div>
          <div>
            <label className="label">Zeitlimit in Sekunden (60–3600)</label>
            <input className="input" type="number" min="60" max="3600"
              value={laCfg.timeout_s}
              onChange={e => {
                const v = parseInt(e.target.value, 10)
                setLaCfg({ ...laCfg, timeout_s: Number.isNaN(v) ? 900 : v })
              }}
            />
          </div>
        </div>

        {laStatus && (
          <div className="mt-4 rounded bg-gray-50 border border-gray-200 p-3 text-sm">
            <div className="font-medium mb-1">Letzter Lauf</div>
            {laStatus.status && laStatus.status.state ? (
              <ul className="text-xs text-gray-600 space-y-0.5">
                <li>
                  Zustand:{' '}
                  <strong className={
                    laStatus.status.state === 'ok' ? 'text-green-700'
                      : laStatus.status.state === 'mode_repo' ? 'text-gray-500'
                      : 'text-red-600'}>
                    {laStatus.status.state}
                  </strong>
                </li>
                <li>Zeitpunkt: {laStatus.status.ts_local || '–'}</li>
                <li>
                  Dauer: {laStatus.status.duration_s != null
                    ? laStatus.status.duration_s + ' s' : '–'}
                  {' · '}Gefundene Fehler: {laStatus.status.num_fehler != null
                    ? laStatus.status.num_fehler : '–'}
                  {' · '}Versuche heute: {laStatus.status.attempts_today != null
                    ? laStatus.status.attempts_today : '–'}
                </li>
                {laStatus.status.error && (
                  <li className="text-red-600">Meldung: {laStatus.status.error}</li>
                )}
                <li>
                  Ergebnisdatei: {laStatus.result_age_h != null
                    ? laStatus.result_age_h + ' h alt' : 'nicht vorhanden'}
                </li>
              </ul>
            ) : (
              <p className="text-xs text-gray-500">Noch kein Lauf aufgezeichnet.</p>
            )}
          </div>
        )}

        <div className="flex gap-3 mt-4 flex-wrap">
          <button className="btn-primary" onClick={saveLaCfg}>Speichern</button>
          <button className="btn-secondary" disabled={laRunning} onClick={runLocalAnalysis}>
            {laRunning ? 'Analyse laeuft …' : 'Jetzt ausfuehren'}
          </button>
          <button className="btn-secondary" onClick={refreshLaStatus}>
            Status aktualisieren
          </button>
          {laSaved && (
            <span className="text-green-700 text-sm self-center">✓ Gespeichert</span>
          )}
          {laMsg && (
            <span className="text-sm self-center text-gray-700">{laMsg}</span>
          )}
        </div>
      </div>

    </div>
  )
}


// ===========================================================================
// HitL — Filterkriterien-Analyse Block (Shortcut zu /cell-filters)
// ===========================================================================
function FilterCriteriaAnalysis() {
  const [stats,    setStats]    = React.useState({
    active: 0, with_png: 0, pending_suggestions: 0,
  })
  const [busy,     setBusy]     = React.useState(false)
  const [message,  setMessage]  = React.useState('')
  const [models,   setModels]   = React.useState([])
  const [selected, setSelected] = React.useState('claude-sonnet-4-6')

  const reload = React.useCallback(async () => {
    try {
      const d = await api.get('/api/cell_filters')
      const active   = (d.active_filters || []).filter(f => f.active).length
      const withPng  = (d.active_filters || []).filter(f => f.polygon_png).length
      const pending  = (d.ai_suggestions || [])
                        .filter(s => !s.accepted &&
                                     (s.suggested_ranges || []).length > 0).length
      setStats({ active, with_png: withPng, pending_suggestions: pending })
    } catch { /* still useful without */ }
  }, [])

  React.useEffect(() => {
    reload()
    api.get('/api/ai_analysis/models')
       .then(d => setModels(d.models || []))
       .catch(() => {})
  }, [reload])

  async function runAnalysis() {
    setBusy(true)
    setMessage('')
    try {
      const r = await api.post('/api/cell_filters/ai_analyze', {
        model: selected,
      })
      if (r.ok) {
        const n = r.suggestions?.length || 0
        setMessage(`✓ ${r.pngs_sent} PNGs analysiert · ${n} Vorschlag${n === 1 ? '' : (n > 1 ? 'e' : 'e')} erhalten`)
        reload()
      } else {
        setMessage('Fehler: ' + (r.error || 'unbekannt'))
      }
    } catch (e) {
      setMessage('Fehler: ' + (e.message || String(e)))
    } finally {
      setBusy(false)
    }
  }

  const noPngs = stats.with_png === 0

  return (
    <div className="card mt-6">
      <h2 className="text-base font-semibold mb-3">🔬 Filterkriterien-Analyse</h2>
      <p className="text-xs text-gray-600 mb-3">
        Sendet die zuletzt vom Benutzer markierten Polygon-Ausschnitte und die
        aktuellen HSV-Filter an die KI mit der Bitte, NEUE breitere Bereiche
        vorzuschlagen. Bestehende Filter bleiben unverändert (Modus „expand_only").
      </p>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3 text-sm">
        <div className="border rounded p-2 bg-gray-50">
          <div className="text-lg font-bold">{stats.active}</div>
          <div className="text-xs text-gray-500">Aktive Filter</div>
        </div>
        <div className="border rounded p-2 bg-gray-50">
          <div className="text-lg font-bold">{stats.with_png}</div>
          <div className="text-xs text-gray-500">mit Polygon-PNG</div>
        </div>
        <div className="border rounded p-2 bg-gray-50">
          <div className="text-lg font-bold">{stats.pending_suggestions}</div>
          <div className="text-xs text-gray-500">offene KI-Vorschläge</div>
        </div>
      </div>

      <div className="flex flex-wrap gap-3 items-center">
        <label className="flex items-center gap-2 text-sm">
          Modell:
          <select className="border rounded px-2 py-1 text-sm"
                  value={selected}
                  onChange={e => setSelected(e.target.value)}>
            {models.length === 0
              ? <option value="claude-sonnet-4-6">claude-sonnet-4-6</option>
              : models.map(m => (
                  <option key={m.id} value={m.id}>{m.label}</option>
                ))}
          </select>
        </label>
        <button onClick={runAnalysis}
                disabled={busy || noPngs}
                className="px-4 py-2 rounded bg-purple-600 text-white text-sm
                           hover:bg-purple-700 disabled:opacity-40 disabled:cursor-not-allowed">
          {busy ? 'Analysiere…' : '🤖 Filterkriterien analysieren'}
        </button>
        <Link to="/cell-filters"
              className="text-sm text-blue-600 hover:underline">
          → Zur Filter-Galerie
        </Link>
      </div>

      {noPngs && (
        <div className="mt-2 text-xs text-amber-700">
          Es sind noch keine Polygon-PNGs gespeichert. Markiere zuerst Zellen
          auf der Karte unter <em>Karte</em>.
        </div>
      )}

      {message && (
        <div className="mt-3 text-sm text-gray-700">
          {message}
          {stats.pending_suggestions > 0 && (
            <span className="ml-2">
              <Link to="/cell-filters" className="text-blue-600 hover:underline">
                Übernahme in Filter-Galerie öffnen →
              </Link>
            </span>
          )}
        </div>
      )}
    </div>
  )
}
