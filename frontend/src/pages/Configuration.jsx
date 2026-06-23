import React, { useEffect, useState } from 'react'
import api from '../api.js'

// ── Parameter-Referenz (alle runtime_config.get()-Keys der Applikation) ─────
function hydroFeatureCollection(response) {
  const fc = response?.data || response
  return (fc && Array.isArray(fc.features)) ? fc : { type: 'FeatureCollection', features: [] }
}

const PARAM_GROUPS = [
  {
    label: '🗺 Risikozonen-Grid',
    params: [
      { key: 'RISK_CELL_RANGE_KM',     type: 'number', default: 20,   unit: 'km',   desc: 'Einfluss-Radius aktiver Sturmzellen auf das Risk-Grid.',         example: 20 },
      { key: 'RISK_TRACK_RANGE_KM',    type: 'number', default: 10,   unit: 'km',   desc: 'Breite des Korridors um die berechnete Zugbahn (Forecast-Pfad).', example: 10 },
      { key: 'RISK_BOLT_RANGE_KM',     type: 'number', default: 10,   unit: 'km',   desc: 'Einfluss-Radius von Blitzeinschlägen auf das Risk-Grid.',         example: 10 },
      { key: 'RISK_ATM_RANGE_KM',      type: 'number', default: 20,   unit: 'km',   desc: 'Einfluss-Radius atmosphärischer Instabilität (LI, CAPE, CIN).',   example: 20 },
      { key: 'RISK_GRID_STEP_DEG',     type: 'number', default: 0.05, unit: '°',    desc: 'Gitter-Schrittweite in Grad (0.05° ≈ 5,5 km). Kleinere Werte → feineres Raster, höhere Rechenlast.', example: 0.05 },
      { key: 'RISK_FAST_CELL_KMH',     type: 'number', default: 30,   unit: 'km/h', desc: 'Ab dieser Geschwindigkeit gilt eine Zelle als "schnell" und erhält keinen Stationär-Bonus mehr.', example: 30 },
      { key: 'RISK_STATIONARY_BOOST',  type: 'number', default: 0.8,  unit: '',     desc: 'Multiplikator-Bonus für stationäre Zellen (Dauergewitter). 0 = kein Bonus, 1 = +100%.', example: 0.8 },
      { key: 'RISK_IR_RANGE_KM',       type: 'number', default: 15,   unit: 'km',   desc: 'Einfluss-Radius von IR-Vorläuferzellen (Cumulonimbus, BT < 230 K) auf das Risk-Grid. Kleinere Werte = engerer Warnbereich.', example: 15 },
    ],
  },
  {
    label: '🛰 IR-Vorläufer-Erkennung',
    params: [
      { key: 'IR_WATCH_ENABLED', type: 'boolean', default: true, unit: '', desc: 'IR-Frühphase anzeigen: aktiviert die frühe IR108-Watch-Erkennung unabhängig vom Radarzyklus.', example: true },
      { key: 'IR_PUBLIC_WATCH_VISIBLE', type: 'boolean', default: true, unit: '', desc: 'IR-Frühphase öffentlich in /map und /karte anzeigen, wenn frisch und Score ausreichend ist.', example: true },
      { key: 'IR_WATCH_BT_THRESHOLD_K', type: 'number', default: 245, unit: 'K', desc: 'Frühe IR108-BT-Schwelle für mögliche Gewitterwolken.', example: 245 },
      { key: 'IR_PRE_CB_BT_THRESHOLD_K', type: 'number', default: 238, unit: 'K', desc: 'BT-Schwelle für stärkere IR-Vorläufer.', example: 238 },
      { key: 'IR_CB_BT_THRESHOLD_K', type: 'number', default: 230, unit: 'K', desc: 'BT-Schwelle für fachlich plausible CB-IR-Vorläufer.', example: 230 },
      { key: 'IR_WATCH_CLOUD_HEIGHT_MIN_M', type: 'number', default: 6500, unit: 'm', desc: 'Mindesthöhe Frühphase.', example: 6500 },
      { key: 'IR_PRE_CB_CLOUD_HEIGHT_MIN_M', type: 'number', default: 7500, unit: 'm', desc: 'Mindesthöhe IR-Vorläufer.', example: 7500 },
      { key: 'IR_CB_CLOUD_HEIGHT_MIN_M', type: 'number', default: 9000, unit: 'm', desc: 'Mindesthöhe CB-Vorläufer.', example: 9000 },
      { key: 'IR_SEVERE_CB_CLOUD_HEIGHT_MIN_M', type: 'number', default: 11000, unit: 'm', desc: 'Höhe für severe-CB-Score-Bonus, allein keine Hagelwarnung.', example: 11000 },
      { key: 'IR_WATCH_MIN_SCORE', type: 'number', default: 0.45, unit: '', desc: 'Mindestscore Frühphase.', example: 0.45 },
      { key: 'IR_PRE_CB_MIN_SCORE', type: 'number', default: 0.60, unit: '', desc: 'Mindestscore IR-Vorläufer.', example: 0.60 },
      { key: 'IR_CB_MIN_SCORE', type: 'number', default: 0.75, unit: '', desc: 'Mindestscore CB-IR-Vorläufer.', example: 0.75 },
      { key: 'IR_MAX_DATA_AGE_MIN', type: 'number', default: 25, unit: 'min', desc: 'Maximales Alter IR-Daten für Pipeline und Risk-Watch.', example: 25 },
      { key: 'IR_WATCH_MAX_PUBLIC_AGE_MIN', type: 'number', default: 20, unit: 'min', desc: 'Maximales Alter IR-Daten für öffentliche Frühphasenanzeige.', example: 20 },
      { key: 'IR_CONVECTION_BT_THRESHOLD_K', type: 'number', default: 230, unit: 'K',     desc: 'Brightness-Temperature-Schwelle: Pixel mit BT < Wert gelten als konvektiver Wolkentop. Niedriger = strenger (220 K ≈ 11.500 m MSL).', example: 230 },
      { key: 'IR_MIN_CELL_AREA_PX',          type: 'number', default: 300, unit: 'Pixel', desc: 'Mindestgröße eines IR-Clusters in TIFF-Pixeln. Kleiner = mehr Detektionen, aber mehr Fehlalarme. Bei 0.12 km/Pixel: 300 ≈ 4 km².', example: 300 },
      { key: 'IR_MIN_CAPE_J_KG',             type: 'number', default: 200, unit: 'J/kg',  desc: 'Mindest-CAPE für IR-Cell-Erkennung. 0 = Filter deaktiviert. Nur angewendet wenn ATM-Daten innerhalb 50 km verfügbar.', example: 200 },
      { key: 'IR_MAX_LI_C',                  type: 'number', default: -0.5, unit: '°C',   desc: 'Maximaler Lifted Index für IR-Cell-Erkennung (negativ = instabil). -0.5 = nur bei leichter Instabilität. 0 = Filter deaktiviert.', example: -0.5 },
    ],
  },
  {
    label: '📍 Orts-Watchlist',
    params: [
      {
        key: 'LOCATIONS_WATCHLIST', type: 'json-array', default: '[]',
        desc: 'Liste der überwachten Orte für Warn-Benachrichtigungen und Orts-Hits. Felder: name, lat, lon, radius_km, email (optional, Semikolon-getrennte Adressen).',
        example: JSON.stringify([
          { name: 'Klagenfurt', lat: 46.624, lon: 14.308, radius_km: 10, email: 'user@example.com' },
          { name: 'Villach',    lat: 46.611, lon: 13.846, radius_km: 8  },
        ], null, 2),
      },
    ],
  },
  {
    label: '⚠ Warnungsschwellen',
    params: [
      { key: 'HAIL_WARN_THRESHOLD',          type: 'number', default: 0.45, unit: '',      desc: 'Hagelwahrscheinlichkeit (0–1) ab der gewarnt wird.',          example: 0.45 },
      { key: 'STATIONARY_RISK_MARKER_THRESHOLD', type: 'number', default: 0.60, unit: '',  desc: 'Schwellwert für stationäres Risiko-Marker-Symbol auf der Karte.', example: 0.60 },
      { key: 'GUST_WARN_KMH',               type: 'number', default: 60,   unit: 'km/h',  desc: 'TAWES-Böengeschwindigkeit ab der gewarnt wird.',              example: 60 },
      { key: 'HEAVY_RAIN_WARN_MM_PER_H',    type: 'number', default: 25,   unit: 'mm/h',  desc: 'Regenrate ab der eine Starkregenwarnung ausgelöst wird.',      example: 25 },
      { key: 'MIN_MOVEMENT_FOR_ARROW_KMH',  type: 'number', default: 5,    unit: 'km/h',  desc: 'Minimale Zellgeschwindigkeit für die Darstellung eines Richtungspfeils.', example: 5 },
      { key: 'SLOW_CELL_MAX_KMH',           type: 'number', default: 15,   unit: 'km/h',  desc: 'Unter diesem Wert gilt eine Zelle als "langsam ziehend" → erweiterter Warnradius.', example: 15 },
      { key: 'SLOW_CELL_RADIUS_FACTOR',     type: 'number', default: 1.5,  unit: '',      desc: 'Faktor für den erweiterten Warnradius langsamer Zellen (radius_km × Faktor).', example: 1.5 },
      { key: 'WARN_MAX_HORIZON_MIN',       type: 'number', default: 20,   unit: 'min',   desc: 'Vorwarnzeit-Schwelle für E-Mail/WhatsApp: Alarm nur wenn der früheste Forecast-Horizont ≤ diesem Wert liegt. Horizont 0 alarmiert immer sofort.', example: 20 },
      { key: 'CLOUD_HEIGHT_ALERT_THRESHOLD_M', type: 'number', default: 10000, unit: 'm', desc: 'CB-Höhengrenze (MSL): Ab dieser geschätzten Wolkenoberkante wird ein IR-Cluster auf der Karte als „CB > …" statt „IR-Vorläufer" beschriftet.', example: 10000 },
    ],
  },
  {
    label: '⏱ Live-Loop / Timing',
    params: [
      { key: 'LOOP_INTERVAL_CELLS_S',             type: 'number', default: 120,  unit: 's',   desc: 'Wartezeit zwischen zwei Radar-Zyklen wenn aktive Zellen vorhanden sind.',          example: 120 },
      { key: 'LOOP_INTERVAL_NO_CELLS_S',          type: 'number', default: 900,  unit: 's',   desc: 'Wartezeit wenn keine aktiven Zellen erkannt wurden.',                              example: 900 },
      { key: 'ATMOSPHERIC_SNAPSHOT_INTERVAL_MIN', type: 'number', default: 30,   unit: 'min', desc: 'Intervall für den atmosphärischen Snapshot (LI, CAPE, CIN pro Referenzpunkt).',    example: 30 },
      { key: 'DATA_CLEANUP_CRON_HOUR',            type: 'number', default: 4,    unit: 'h',   desc: 'Stunde (0–23, UTC) des täglichen Daten-Cleanup-Jobs.',                             example: 4 },
      { key: 'DATA_CLEANUP_CRON_MINUTE',          type: 'number', default: 30,   unit: 'min', desc: 'Minute (0–59) des täglichen Daten-Cleanup-Jobs.',                                  example: 30 },
      { key: 'DATA_RETENTION_DAYS',               type: 'number', default: 90,   unit: 'Tage', desc: 'Alter in Tagen ab dem Radar/Objekt/Trainingsdaten gelöscht werden.',              example: 90 },
    ],
  },
  {
    label: '🧠 ML & Training',
    params: [
      { key: 'ML_FORECAST_HORIZONS_MIN', type: 'json-array', default: '[10,20,30,40,60]', desc: 'Forecast-Horizonte in Minuten. Änderung erfordert Neutraining der Modelle!', example: JSON.stringify([10, 20, 30, 40, 60]) },
      { key: 'LOCAL_TRAINING',           type: 'boolean', default: true,  desc: 'Training läuft lokal auf dem Pi. false = nur Inferenz, Modelle werden extern trainiert.', example: true },
      { key: 'DATASET_REBUILD_INTERVAL_MIN', type: 'number', default: 60, unit: 'min', desc: 'Wie oft wird das ML-Trainings-Dataset neu aufgebaut (5–1440 min).', example: 60 },
      { key: 'RETRAIN_INTERVAL_HOURS',   type: 'number', default: 24,  unit: 'h', desc: 'Intervall für automatisches Retraining (1–168 h).', example: 24 },
      {
        key: 'TRAINING_SCHEDULE', type: 'json-object', default: '{}',
        desc: 'Feinsteuerung der Training-Cron-Jobs. Felder: retrain_interval_hours, retrain_cron_hour, retrain_cron_minute, convlstm_cron_day_of_week (z.B. "mon"), convlstm_cron_hour, convlstm_cron_minute.',
        example: JSON.stringify({ retrain_interval_hours: 24, retrain_cron_hour: 3, retrain_cron_minute: 0, convlstm_cron_day_of_week: 'mon', convlstm_cron_hour: 2, convlstm_cron_minute: 0 }, null, 2),
      },
      { key: 'CONVLSTM_MODEL_PATH', type: 'string', default: '(auto)', desc: 'Absoluter Pfad zum ConvLSTM-Modell (.keras). Leer lassen = automatisch aus SAVE_PATHS["models"]/current/.', example: '/home/ki-pi/wetterprojekt/train_data/models/current/radar_convlstm.keras' },
    ],
  },
  {
    label: '🌩 TAWES-Wetterstationen',
    params: [
      { key: 'TAWES_GUST_STATION_IDS', type: 'string', default: '(alle Kärntner Stationen)', desc: 'Komma-getrennte GeoSphere TAWES Station-IDs. Leer = alle konfigurierten Kärntner Stationen.', example: '11275,11218,11234,11206,11227' },
      { key: 'TAWES_PARAMS',           type: 'string', default: 'RR,DD,FF,FFX,GLOW,P,RF,TL,TP', desc: 'Komma-getrennte TAWES-Parameter-Codes die abgerufen werden.', example: 'RR,DD,FF,FFX,GLOW,P,RF,TL,TP' },
    ],
  },
  {
    label: '🗄 API-Cache TTL',
    params: [
      {
        key: 'API_CACHE_TTL_SECONDS', type: 'json-object', default: '{}',
        desc: 'TTL in Sekunden pro API-Cache-Key. Keys: icon_d2, icon_global, gfs_conv, cloud_height, tawes, blitzortung, risk_grid. Nicht gesetzte Keys verwenden den globalen Default (1800 s).',
        example: JSON.stringify({ icon_d2: 1800, icon_global: 3600, gfs_conv: 1800, cloud_height: 900, tawes: 600, blitzortung: 300, risk_grid: 120 }, null, 2),
      },
    ],
  },
  {
    label: '🤖 KI-Tagesanalyse',
    params: [
      {
        key: 'AI_ANALYSIS_CONFIG', type: 'json-object', default: '{}',
        desc: 'Konfiguration der täglichen KI-Analyse via Anthropic API. Felder: enabled (bool), cron_hour (0–23), cron_minute (0–59), model (string), max_tokens (int), email_report (bool).',
        example: JSON.stringify({ enabled: false, cron_hour: 6, cron_minute: 0, model: 'claude-opus-4-6', max_tokens: 4096, email_report: false }, null, 2),
      },
    ],
  },
  {
    label: '🌊 Hydro-Impact',
    params: [
      { key: 'HYDRO_ENABLED', type: 'boolean', default: true, desc: 'Hydro-Impact-Layer und Bewertung aktivieren/deaktivieren.', example: true },
      { key: 'HYDRO_API_TTL_SECONDS', type: 'number', default: 600, unit: 's', desc: 'Cache-/Aktualisierungs-TTL fuer Hydro-Live-Daten.', example: 600 },
      { key: 'HYDRO_MIN_OVERLAP_AREA_KM2', type: 'number', default: 1.0, unit: 'km²', desc: 'Mindest-Schnittflaeche zwischen Zelle und Einzugsgebiet.', example: 1.0 },
      { key: 'HYDRO_MIN_CELL_OVERLAP_RATIO', type: 'number', default: 0.03, desc: 'Legacy-Alias fuer den Mindestanteil der Zellflaeche im Einzugsgebiet.', example: 0.03 },
      { key: 'HYDRO_MIN_OVERLAP_RATIO_CELL', type: 'number', default: 0.05, desc: 'Mindestanteil der Zellflaeche im oberliegenden Einzugsgebiet.', example: 0.05 },
      { key: 'HYDRO_MIN_DURATION_MIN', type: 'number', default: 5, unit: 'min', desc: 'Mindestdauer der Zelle im oberliegenden Einzugsgebiet.', example: 5 },
      { key: 'HYDRO_RELEVANT_INTENSITIES', type: 'json-array', default: '["strong","severe","extreme"]', desc: 'Intensitaetsklassen, die fuer Hydro-Impact relevant sind.', example: JSON.stringify(['strong', 'severe', 'extreme'], null, 2) },
      { key: 'HYDRO_DEFAULT_LAG_MIN', type: 'json-array', default: '[20,180]', desc: 'Standard-Zeitfenster fuer Pegelreaktionen in Minuten.', example: '[20,180]' },
      { key: 'HYDRO_LAG_WINDOW_MIN', type: 'json-array', default: '[20,180]', desc: 'Runtime-Zeitfenster fuer vorsichtige Hydro-Verifikation.', example: '[20,180]' },
      { key: 'HYDRO_VERIFY_MIN_DELTA_Q_M3S', type: 'number', default: 0.2, unit: 'm³/s', desc: 'Mindest-Abflussanstieg fuer eine plausible Bestaetigung.', example: 0.2 },
      { key: 'HYDRO_VERIFY_MIN_DELTA_W_CM', type: 'number', default: 5, unit: 'cm', desc: 'Mindest-Pegelanstieg fuer eine plausible Bestaetigung.', example: 5 },
      { key: 'HYDRO_VERIFY_MIN_RELATIVE_DELTA_PCT', type: 'number', default: 10, unit: '%', desc: 'Relative Mindest-Aenderung fuer eine plausible Bestaetigung.', example: 10 },
      { key: 'HYDRO_VERIFY_MAX_GAP_MIN', type: 'number', default: 90, unit: 'min', desc: 'Maximale Messluecke im Verifikationsfenster; groessere Luecken werden ambiguous.', example: 90 },
      { key: 'HYDRO_STATION_OVERRIDES', type: 'json-object', default: '{}', desc: 'Stations-Overrides, z.B. Aktivierung/Deaktivierung pro station_id.', example: JSON.stringify({ '123': { enabled: false } }, null, 2) },
      { key: 'HYDRO_STATIC_REQUIRED', type: 'boolean', default: false, desc: 'Erzwingt vorhandene statische Hydro-Daten, bevor Hydro-Impact aktiv genutzt wird.', example: false },
    ],
  },
  {
    label: '🔬 Erweitert / Sonstiges',
    params: [
      { key: 'FRAME_INTERVAL_MIN',        type: 'number', default: 2.0, unit: 'min', desc: 'Nominales Radar-Frame-Intervall in Minuten. Basis für Geschwindigkeitsberechnung.', example: 2.0 },
      { key: 'MAX_CONTOUR_DISTANCE',      type: 'number', default: 30,  unit: 'px',  desc: 'Maximale Pixel-Distanz für Zell-Matching im Kalman-Tracking.', example: 30 },
      { key: 'MAX_CELL_SPEED_KMH',        type: 'number', default: 150, unit: 'km/h', desc: 'Plausibilitätsgrenze: schnellere Zellen werden verworfen.', example: 150 },
      { key: 'MAX_SPEED_CHANGE_PER_CYCLE_KMH', type: 'number', default: 60, unit: 'km/h', desc: 'Maximale Geschwindigkeitsänderung pro Zyklus (Anti-Jitter).', example: 60 },
      { key: 'VERIFICATION_TOLERANCE_KM', type: 'number', default: 5,   unit: 'km',  desc: 'Toleranz-Radius für Closed-Loop-Verifikation (Forecast vs. tatsächliche Position).', example: 5 },
      { key: 'ML_SEQUENCE_LENGTH',        type: 'number', default: 6,   unit: '',       desc: 'Anzahl historischer Frames die das LSTM als Input-Sequenz bekommt.', example: 6 },
      { key: 'TRACK_HISTORY_LEN',         type: 'number', default: 6,   unit: 'Frames', desc: 'Anzahl gespeicherter History-Frames pro Zelle. Basis für EWMA-Geschwindigkeitsberechnung. Erhöhung verbessert Glättung; mind. 2.', example: 6 },
      { key: 'KINEMATIC_EWMA_ALPHA',      type: 'number', default: 0.6, unit: '',       desc: 'EWMA-Glättungsfaktor für kinematischen Forecast. 0.01 = gleichgewichtet (alle Frames gleich), 0.99 = fast nur neuester Frame. Empfohlen: 0.5–0.7.', example: 0.6 },
    ],
  },
  {
    label: '🔔 Benachrichtigungen & Cooldowns',
    params: [
      { key: 'WARN_COOLDOWN_S',                type: 'number', default: 900,   unit: 's',   desc: 'Safety-Cooldown für Gewitterwarnungen pro Ort (Sekunden). Primär-Logik ist einmal-pro-Zelle — dieser Wert ist der Fallback.', example: 900 },
      { key: 'ALLCLEAR_COOLDOWN_S',             type: 'number', default: 300,   unit: 's',   desc: 'Mindestabstand zwischen zwei Entwarnungen pro Ort (Sekunden).', example: 300 },
      { key: 'RISK_ALERT_COOLDOWN_S',           type: 'number', default: 43200, unit: 's',   desc: 'Mindestabstand zwischen zwei atmosphärischen Risikoalarmen pro Ort. Default: 43200 = 12 Stunden.', example: 43200 },
      { key: 'DRIFT_ALERT_COOLDOWN_H',          type: 'number', default: 6,     unit: 'h',   desc: 'Mindestabstand zwischen zwei Model-Drift-Alarmen (Stunden).', example: 6 },
      { key: 'WARN_MAX_HORIZON_MIN',            type: 'number', default: 20,    unit: 'min', desc: 'Vorwarnzeit: E-Mail/WhatsApp-Alarm nur wenn frühester Forecast-Horizont ≤ diesem Wert liegt.', example: 20 },
      { key: 'MIN_SEQUENCES_LSTM',              type: 'number', default: 50,    unit: 'Seq', desc: 'Mindestanzahl Zell-Sequenzen für LSTM-Training. Unter diesem Wert wird das Training übersprungen.', example: 50 },
      { key: 'MIN_SEQUENCES_LGBM',              type: 'number', default: 30,    unit: 'Seq', desc: 'Mindestanzahl Zell-Sequenzen für LightGBM-Training.', example: 30 },
      { key: 'RISK_ALERT_REQUIRED_DOMINANTS',   type: 'text',   default: '["atm"]', unit: '', desc: 'JSON-Array: Welche dominant-Quellen dürfen Risiko-Stufe-3-Alarm auslösen. Standard: ["atm"]. Mögliche Werte: "cell","track","lightning","ir_cell","atm".', example: '["atm"]' },
    ],
  },
]

function ParamRow({ p }) {
  const [open, setOpen] = useState(false)
  const isJson = p.type.startsWith('json')
  return (
    <tr className="border-b border-gray-100 hover:bg-gray-50">
      <td className="py-1.5 px-2 font-mono text-xs text-blue-700 whitespace-nowrap align-top">{p.key}</td>
      <td className="py-1.5 px-2 text-xs text-gray-500 whitespace-nowrap align-top">{p.type}{p.unit ? ` [${p.unit}]` : ''}</td>
      <td className="py-1.5 px-2 text-xs font-mono text-gray-700 align-top">
        {String(p.default).length > 30 ? '(komplex)' : String(p.default)}
      </td>
      <td className="py-1.5 px-2 text-xs text-gray-600 align-top">
        {p.desc}
        {isJson && (
          <button
            className="ml-2 text-blue-500 hover:underline"
            onClick={() => setOpen(v => !v)}
          >
            {open ? '▲ Beispiel' : '▼ Beispiel'}
          </button>
        )}
        {open && (
          <pre className="mt-1 bg-gray-100 rounded p-1 text-xs overflow-x-auto">{p.example}</pre>
        )}
      </td>
    </tr>
  )
}

export default function Configuration() {
  const [text, setText] = useState('')
  const [msg, setMsg] = useState('')
  const [showHelp, setShowHelp] = useState(false)
  const [search, setSearch] = useState('')
  const [hydroStations, setHydroStations] = useState([])
  const [hydroStatus, setHydroStatus] = useState(null)
  const [hydroBusy, setHydroBusy] = useState('')
  const [hydroMsg, setHydroMsg] = useState('')

  useEffect(() => {
    api.get('/api/config').then(d => setText(JSON.stringify(d, null, 2))).catch(() => {})
    api.get('/api/hydro/stations?include_disabled=1').then(d => setHydroStations(hydroFeatureCollection(d).features.map(f => f.properties || {}))).catch(() => setHydroStations([]))
    api.get('/api/hydro/status').then(d => setHydroStatus(d?.data || d)).catch(() => setHydroStatus({ status: 'hydro_status_error' }))
  }, [])

  async function save() {
    try {
      const data = JSON.parse(text)
      await api.post('/api/config', data)
      setMsg('✅ Gespeichert.')
    } catch (e) {
      setMsg('❌ Fehler: ' + e.message)
    }
  }

  async function pollHydroImport() {
    const deadline = Date.now() + 10 * 60 * 1000
    while (Date.now() < deadline) {
      await new Promise(r => setTimeout(r, 3000))
      let job = null
      try {
        const s = await api.get('/api/hydro/import-status?nocache=true')
        job = (s?.data || s)?.job
      } catch (e) { /* transienter Fehler: weiter pollen */ }
      if (job && job.status !== 'running') {
        if (job.status === 'failed' || job.status === 'stale') throw new Error(job.error || 'Import fehlgeschlagen')
        return job
      }
    }
    throw new Error('Import-Timeout — läuft ggf. im Hintergrund weiter')
  }

  async function runHydroAction(key, url, okMsg) {
    if (hydroBusy) return
    setHydroBusy(key)
    setHydroMsg('')
    try {
      const res = await api.post(url, {})
      const started = (res?.data || res)?.status
      if (key === 'reload-static' && (started === 'started' || started === 'already_running')) {
        await pollHydroImport()
      }
      setHydroMsg(okMsg)
      const [stations, status] = await Promise.all([
        api.get('/api/hydro/stations?include_disabled=1&nocache=true').catch(() => null),
        api.get('/api/hydro/status?nocache=true').catch(() => null),
      ])
      if (stations) setHydroStations(hydroFeatureCollection(stations).features.map(f => f.properties || {}))
      if (status) setHydroStatus(status?.data || status)
    } catch (e) {
      setHydroMsg('❌ Fehler: ' + (e?.payload?.error || e?.message || 'unbekannt'))
    } finally {
      setHydroBusy('')
    }
  }

  async function patchHydroStation(st, patch) {
    const sid = st.station_id
    setHydroMsg('')
    try {
      await api.patch(`/api/hydro/stations/${st.station_id}`, patch)
      setHydroStations(prev => prev.map(s => s.station_id === sid ? { ...s, ...patch } : s))
      setHydroMsg('✅ Station aktualisiert.')
    } catch (err) {
      setHydroMsg('❌ Fehler: ' + (err?.payload?.error || err?.message || 'unbekannt'))
    }
  }

  const hydroImpactEligibleCount = hydroStations.filter(st => st.impact_eligible === true).length
  const upstreamTopologyMissing = hydroStatus?.static_status === 'upstream_topology_missing' || hydroStatus?.impact_not_eligible_reason === 'upstream_topology_missing'

  const filteredGroups = PARAM_GROUPS.map(g => ({
    ...g,
    params: g.params.filter(p =>
      !search ||
      p.key.toLowerCase().includes(search.toLowerCase()) ||
      p.desc.toLowerCase().includes(search.toLowerCase())
    ),
  })).filter(g => g.params.length > 0)

  return (
    <div className="max-w-5xl mx-auto">
      <h1 className="text-2xl font-bold mb-4">Konfiguration</h1>


      <div className="bg-white border border-gray-200 rounded-lg p-4 mb-4">
        <h2 className="text-sm font-semibold text-gray-700 mb-2">🌊 Hydro-Impact Admin</h2>
        <div className="mb-3 rounded border bg-gray-50 p-2 text-xs text-gray-700">
          <div><strong>Status:</strong> {hydroStatus?.status || 'wird geladen'}</div>
          <div><strong>Static:</strong> {hydroStatus?.static_status || '—'} · <strong>Live:</strong> {hydroStatus?.live_ok ? 'ok' : (hydroStatus?.live_ready ? 'nicht ok' : 'fehlt')}</div>
          <div>{hydroStations.length} Hydro-Stationen geladen · {hydroImpactEligibleCount} impact-eligible</div>
          {upstreamTopologyMissing && <div className="text-amber-700">Hinweis: Upstream-Topologie fehlt noch</div>}
          {hydroStatus?.last_error && <div className="text-red-700"><strong>Fehler:</strong> {hydroStatus.last_error}</div>}
        </div>
        <div className="flex flex-wrap gap-2 mb-3">
          <button className="btn" disabled={!!hydroBusy} onClick={() => runHydroAction('fetch-live', '/api/hydro/fetch-live', '✅ Live-Hydro geladen.')}>{hydroBusy === 'fetch-live' ? '⏳ lädt …' : 'Live-Hydro jetzt laden'}</button>
          <button className="btn" disabled={!!hydroBusy} onClick={() => runHydroAction('reload-static', '/api/hydro/reload-static', '✅ Static-Hydro neu eingelesen.')}>{hydroBusy === 'reload-static' ? '⏳ Rebuild läuft … (eigener Prozess, kann dauern)' : 'Static-Hydro neu einlesen'}</button>
          <button className="btn" disabled={!!hydroBusy} onClick={() => runHydroAction('verify', '/api/hydro/verify', '✅ Pending-Verifikation geprüft.')}>{hydroBusy === 'verify' ? '⏳ prüft …' : 'Pending Verifikation prüfen'}</button>
        </div>
        {(hydroBusy || hydroMsg) && (
          <div className={`mb-3 rounded border p-2 text-sm ${hydroBusy ? 'bg-blue-50 border-blue-300 text-blue-800' : (hydroMsg.startsWith('✅') ? 'bg-green-50 border-green-300 text-green-800' : 'bg-red-50 border-red-300 text-red-800')}`}>
            {hydroBusy === 'reload-static' ? '⏳ Static-Rebuild läuft im Hintergrund … bitte warten.' : (hydroBusy ? '⏳ Aktion läuft …' : hydroMsg)}
          </div>
        )}
        <div className="max-h-48 overflow-auto border rounded">
          {hydroStations.length === 0 ? <div className="p-2 text-xs text-gray-500">Keine Hydro-Stationen geladen.</div> : hydroStations.map(st => (
            <div key={st.station_id} className="flex items-center justify-between gap-2 px-2 py-1 border-b text-xs">
              <span className="flex-1"><strong>{st.name || st.station_id}</strong> · {st.river || '—'}</span>
              <label className="flex items-center gap-1" title="Markierungs-Durchfluss dieser Station (m³/s); leer = globaler Wert">
                <span className="text-gray-500">Q≥</span>
                <input type="number" min="0" step="0.1" disabled={!!hydroBusy} defaultValue={st.mark_q_m3s ?? ''} className="w-16 border rounded px-1"
                  onBlur={e => { const v = e.target.value.trim(); const num = v === '' ? null : Number(v); patchHydroStation(st, { mark_q_m3s: Number.isFinite(num) ? num : null }) }} />
              </label>
              <input type="checkbox" disabled={!!hydroBusy} checked={st.enabled !== false} onChange={e => patchHydroStation(st, { enabled: e.target.checked })} />
            </div>
          ))}
        </div>
      </div>

      {/* Editor-Block */}
      <div className="bg-white border border-gray-200 rounded-lg p-4 mb-4">
        <h2 className="text-sm font-semibold text-gray-700 mb-2">
          Runtime-Overrides (JSON) — wirksam ohne Service-Neustart
        </h2>
        {msg && (
          <div className={`border p-2 rounded mb-3 text-sm ${msg.startsWith('✅') ? 'bg-green-50 border-green-300 text-green-800' : 'bg-red-50 border-red-300 text-red-800'}`}>
            {msg}
          </div>
        )}
        <textarea
          className="input font-mono text-xs"
          rows="22"
          value={text}
          onChange={e => setText(e.target.value)}
        />
        <div className="flex gap-3 mt-3 items-center">
          <button className="btn-primary" onClick={save}>Speichern</button>
          <span className="text-xs text-gray-400">
            Nur Overrides eintragen — Config-Defaults bleiben unverändert.
          </span>
        </div>
      </div>

      {/* Hilfe-Block */}
      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <button
          className="w-full flex items-center justify-between px-4 py-3 text-sm font-semibold text-gray-700 hover:bg-gray-50"
          onClick={() => setShowHelp(v => !v)}
        >
          <span>📖 Parameter-Referenz — alle konfigurierbaren Runtime-Keys</span>
          <span className="text-gray-400">{showHelp ? '▲ ausblenden' : '▼ einblenden'}</span>
        </button>

        {showHelp && (
          <div className="px-4 pb-4">
            <p className="text-xs text-gray-500 mb-3">
              Alle Schlüssel können als Top-Level-Felder in das JSON-Textfeld oben eingetragen werden.
              Override-Werte haben Vorrang vor <code>config.py</code>-Defaults.
              Nicht überschriebene Parameter behalten ihren Default-Wert automatisch.
            </p>

            {/* Suchfeld */}
            <input
              type="text"
              className="input mb-4 text-sm"
              placeholder="Parameter suchen …"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />

            {filteredGroups.map(group => (
              <div key={group.label} className="mb-5">
                <h3 className="text-sm font-bold text-gray-800 mb-1">{group.label}</h3>
                <table className="w-full text-left border border-gray-200 rounded overflow-hidden text-xs">
                  <thead className="bg-gray-100 text-gray-600">
                    <tr>
                      <th className="py-1 px-2 font-semibold">Schlüssel</th>
                      <th className="py-1 px-2 font-semibold">Typ</th>
                      <th className="py-1 px-2 font-semibold">Default</th>
                      <th className="py-1 px-2 font-semibold">Beschreibung</th>
                    </tr>
                  </thead>
                  <tbody>
                    {group.params.map(p => <ParamRow key={p.key} p={p} />)}
                  </tbody>
                </table>
              </div>
            ))}

            <p className="text-xs text-gray-400 mt-2">
              Änderungen an <code>ML_FORECAST_HORIZONS_MIN</code>,{' '}
              <code>INTENSITY_BANDS</code> und <code>LOCAL_TRAINING</code> erfordern
              anschließendes Neutraining der Modelle. Alle anderen Parameter wirken sofort.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
