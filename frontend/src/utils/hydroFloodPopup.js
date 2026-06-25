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
  const precipValue = precipEvaluable ? `${fmt(flood.effective_catchment_precip_sum_mm)} mm` : 'nicht bewertbar'
  const precipStatusLabel = flood.precip_status_label || (precipEvaluable ? 'aus erkannter Regenzelle abgeleitet' : 'keine verwertbaren Niederschlagsdaten zugeordnet')
  const precipQualityLabel = flood.precip_quality_label || (precipEvaluable ? (flood.effective_precip_source_quality === 'high' ? 'hoch' : 'mittel') : 'nicht bewertbar')
  const dataAge = validNumber(flood.current_data_age_min) ? flood.current_data_age_min : (validNumber(flood.data_age_min) ? flood.data_age_min : p.data_age_min)
  const reasonItems = (Array.isArray(flood.reasons) ? flood.reasons : []).map(translate).filter(Boolean)
  const warningItems = (Array.isArray(flood.warning_reasons) ? flood.warning_reasons : []).map(translate).filter(Boolean)
  const reasonsLabel = reasonItems.length ? reasonItems.join(', ') : (floodNotEvaluable ? 'nicht ermittelt' : 'keine Auslösegründe')
  return {
    currentQLabel: validNumber(currentQ) ? fmt(currentQ) : '—',
    thresholdLabel: thresholdMissing ? '—' : fmt(threshold),
    thresholdSourceLabel: thresholdMissing ? '—' : thresholdSourceLabel(thresholdSource),
    distanceLabel: validNumber(distance) ? fmt(distance) : '—',
    dataAgeLabel: validNumber(dataAge) ? Number(dataAge).toFixed(1) : '—',
    floodLabel,
    precipValue,
    precipStatusLabel,
    precipQualityLabel,
    reasonsLabel,
    warningItems,
  }
}
