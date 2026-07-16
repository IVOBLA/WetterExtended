export const HYDRO_TREND_LABELS = {
  rising: 'steigend',
  falling: 'fallend',
  stable: 'gleichbleibend',
  insufficient_history: 'nicht ermittelbar (zu wenig Historie)',
}

export const HYDRO_REASON_LABELS = {
  missing_station_q_threshold: 'Q≥-Grenzwert der Station fehlt',
  precipitation_proxy_used: 'Niederschlag wurde nur ersatzweise abgeleitet',
  'current_q_m3s >= station_q_threshold_m3s': 'aktueller Durchfluss liegt über dem Q≥-Grenzwert',
  'current_q_m3s nahe am Q-Grenzwert': 'aktueller Durchfluss liegt nahe am Q≥-Grenzwert',
  'Niederschlag im oberliegenden Einzugsgebiet': 'Niederschlag im oberliegenden Einzugsgebiet erkannt',
}

const validNumber = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value))
const fmt = (value, digits = 2) => validNumber(value) ? Number(value).toFixed(digits) : '—'
const translate = value => HYDRO_REASON_LABELS[value] || value


function parseTimestamp(value) {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

function formatViennaTimestamp(value) {
  const date = parseTimestamp(value)
  if (!date) return 'unbekannt'
  return new Intl.DateTimeFormat('de-AT', {
    timeZone: 'Europe/Vienna',
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date).replace(',', '')
}

function currentQTimestamp(p, flood) {
  if (flood.current_q_measured_at) return { value: flood.current_q_measured_at, source: flood.current_q_timestamp_source || 'hydro_live.measured_at' }
  if (flood.measured_at) return { value: flood.measured_at, source: 'hydro_live.measured_at' }
  if (p.measured_at) return { value: p.measured_at, source: 'hydro_live.measured_at' }
  if (flood.fetched_at) return { value: flood.fetched_at, source: 'hydro_live.fetched_at_fallback' }
  if (p.fetched_at) return { value: p.fetched_at, source: 'hydro_live.fetched_at_fallback' }
  return { value: null, source: 'missing' }
}

function timestampSourceLabel(source) {
  if (source === 'hydro_live.fetched_at_fallback') return 'Fetch-Zeitpunkt, Messzeit fehlt'
  if (source === 'hydro_live.measured_at') return 'Messzeit Hydro-Live'
  return 'unbekannt'
}

function thresholdSourceLabel(source) {
  if (source === 'station_override') return 'stationsspezifisch'
  if (source === 'global_fallback') return 'globaler Fallback'
  return '—'
}

export function normalizeHydroFloodPopup(p = {}, flood = {}) {
  const currentQ = validNumber(flood.current_q_m3s) ? flood.current_q_m3s : p.q_m3s
  const floodThresholdValid = validNumber(flood.station_q_threshold_m3s) && flood.station_q_threshold_source !== 'missing'
  const fallbackThreshold = validNumber(p.q_threshold) ? p.q_threshold : p.mark_q_m3s
  const fallbackValid = !floodThresholdValid && validNumber(fallbackThreshold) && Object.keys(flood || {}).length === 0
  const threshold = floodThresholdValid ? flood.station_q_threshold_m3s : (fallbackValid ? fallbackThreshold : null)
  const thresholdSource = floodThresholdValid ? flood.station_q_threshold_source : (fallbackValid ? 'station_override' : 'missing')
  const thresholdMissing = !validNumber(threshold)
  const distance = validNumber(flood.current_q_distance_to_threshold_m3s)
    ? flood.current_q_distance_to_threshold_m3s
    : (!thresholdMissing && validNumber(currentQ) ? Number(threshold) - Number(currentQ) : null)
  const floodNotEvaluable = flood.flood_evaluable === false || flood.flood_status === 'missing_threshold' || thresholdMissing
  const floodLabel = floodNotEvaluable ? 'nicht bewertbar' : (flood.flood_expected === true ? 'ja' : 'nein')
  const precipEvaluable = flood.precip_evaluable === true || (flood.effective_precip_source_type && flood.effective_precip_source_type !== 'missing' && validNumber(flood.effective_catchment_precip_sum_mm))
  const noRelevantCell = flood.precip_status === 'no_relevant_cell'
  const missingGeometry = flood.precip_status === 'catchment_geometry_missing' || flood.catchment_geometry_available === false
  const precipValue = precipEvaluable && validNumber(flood.effective_catchment_precip_sum_mm) ? `${fmt(flood.effective_catchment_precip_sum_mm)} mm` : (noRelevantCell ? '0,00 mm' : 'nicht bewertbar')
  const precipStatusLabel = flood.precip_status_label || (precipEvaluable ? 'aus erkannter Regenzelle abgeleitet' : 'keine verwertbaren Niederschlagsdaten zugeordnet')
  const precipQualityLabel = flood.precip_quality_label || (precipEvaluable ? (flood.effective_precip_source_quality === 'high' ? 'hoch' : 'mittel') : 'nicht bewertbar')
  const qTimestamp = currentQTimestamp(p, flood)
  const qTimestampDate = parseTimestamp(qTimestamp.value)
  const calculatedAge = qTimestampDate ? Math.max(0, (Date.now() - qTimestampDate.getTime()) / 60000) : null
  const dataAge = validNumber(flood.current_data_age_min) ? flood.current_data_age_min : (validNumber(flood.data_age_min) ? flood.data_age_min : (validNumber(p.data_age_min) ? p.data_age_min : calculatedAge))
  const reasonItems = (Array.isArray(flood.reasons) ? flood.reasons : []).map(translate).filter(Boolean)
  const warningItems = (Array.isArray(flood.warning_reasons) ? flood.warning_reasons : []).map(translate).filter(Boolean)
  const reasonsLabel = reasonItems.length ? reasonItems.join(', ') : (floodNotEvaluable ? 'nicht ermittelt' : 'keine Auslösegründe')
  const trendStatus = flood.q_trend_status || p.q_trend_status || 'insufficient_history'
  const trendDelta = validNumber(flood.q_trend_delta_m3s) ? flood.q_trend_delta_m3s : p.q_trend_delta_m3s
  const trendWindow = validNumber(flood.q_trend_reference_window_min) ? flood.q_trend_reference_window_min : p.q_trend_reference_window_min
  const trendDeltaLabel = validNumber(trendDelta) && validNumber(trendWindow)
    ? `${Number(trendDelta) >= 0 ? '+' : ''}${fmt(trendDelta)} m³/s / ${Number(trendWindow).toFixed(0)} Min`
    : '—'
  return {
    currentQLabel: validNumber(currentQ) ? fmt(currentQ) : '—',
    thresholdLabel: thresholdMissing ? '—' : fmt(threshold),
    currentQMeasuredAt: qTimestamp.value,
    currentQTimestampLabel: formatViennaTimestamp(qTimestamp.value),
    currentQTimestampSourceLabel: timestampSourceLabel(qTimestamp.source),
    thresholdSourceLabel: thresholdMissing ? '—' : thresholdSourceLabel(thresholdSource),
    distanceLabel: validNumber(distance) ? fmt(distance) : '—',
    dataAgeLabel: validNumber(dataAge) ? Number(dataAge).toFixed(1) : '—',
    floodLabel,
    predictedQMaxLabel: validNumber(flood.predicted_q_max_m3s) ? fmt(flood.predicted_q_max_m3s) : '—',
    thresholdExceededLabel: floodNotEvaluable ? 'nicht bewertbar' : (flood.flood_expected === true ? 'ja' : 'nein'),
    contributingCellCountLabel: validNumber(flood.contributing_cell_count) ? Number(flood.contributing_cell_count).toFixed(0) : '—',
    currentCellCountLabel: validNumber(flood.current_cell_count) ? Number(flood.current_cell_count).toFixed(0) : '—',
    incomingCellCountLabel: validNumber(flood.incoming_cell_count) ? Number(flood.incoming_cell_count).toFixed(0) : '—',
    dwellTimeLabel: validNumber(flood.total_dwell_time_min) ? `${Number(flood.total_dwell_time_min).toFixed(0)} min` : '—',
    precipValue,
    precipStatusLabel,
    precipQualityLabel,
    reasonsLabel,
    warningItems,
    trendStatus,
    trendLabel: HYDRO_TREND_LABELS[trendStatus] || HYDRO_TREND_LABELS.insufficient_history,
    trendDeltaLabel,
  }
}
