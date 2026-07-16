import assert from 'node:assert/strict'
import { normalizeHydroFloodPopup } from '../hydroFloodPopup.js'

{
  const n = normalizeHydroFloodPopup({ q_threshold: 8 }, { station_q_threshold_m3s: 8, station_q_threshold_source: 'missing', flood_status: 'missing_threshold', warning_reasons: ['missing_station_q_threshold'] })
  assert.notEqual(`${n.thresholdLabel} m³/s (${n.thresholdSourceLabel})`, '8.00 m³/s (missing)')
}
{
  const n = normalizeHydroFloodPopup({}, { flood_evaluable: false, flood_status: 'missing_threshold' })
  assert.equal(n.floodLabel, 'nicht bewertbar')
  assert.notEqual(n.floodLabel, 'nein')
}
{
  const n = normalizeHydroFloodPopup({}, { flood_status: 'missing_threshold', warning_reasons: ['missing_station_q_threshold'] })
  assert.equal(n.warningItems[0], 'Q≥-Grenzwert der Station fehlt')
  assert.notEqual(n.warningItems[0], 'missing_station_q_threshold')
}
{
  const n = normalizeHydroFloodPopup({}, { effective_precip_source_type: 'missing', effective_precip_source_quality: 'missing' })
  assert.equal(n.precipStatusLabel, 'keine verwertbaren Niederschlagsdaten zugeordnet')
  assert.notEqual(`${n.precipStatusLabel} · Qualität ${n.precipQualityLabel}`, 'missing · Qualität missing')
}
{
  assert.equal(normalizeHydroFloodPopup({}, { flood_evaluable: true, station_q_threshold_m3s: 8, station_q_threshold_source: 'station_override', reasons: [] }).reasonsLabel, 'keine Auslösegründe')
  assert.equal(normalizeHydroFloodPopup({}, { flood_evaluable: false, reasons: [] }).reasonsLabel, 'nicht ermittelt')
}
{
  const n = normalizeHydroFloodPopup({}, { current_q_m3s: 0.89, current_q_measured_at: '2026-06-25T11:45:00Z' })
  assert.equal(n.currentQLabel, '0.89')
  assert.equal(n.currentQTimestampLabel, '25.06.2026 13:45')
}
{
  const n = normalizeHydroFloodPopup({}, { precip_status: 'missing', precip_status_label: 'keine verwertbaren Niederschlagsdaten zugeordnet' })
  assert.equal(n.precipStatusLabel, 'keine verwertbaren Niederschlagsdaten zugeordnet')
}
{
  const used = normalizeHydroFloodPopup({}, { precip_status_label: 'gemessen', observed_precip_used_in_forecast: true })
  const rejected = normalizeHydroFloodPopup({}, { observed_precip_rejection_reason: 'observed_precip_outside_lag_window' })
  assert.match(used.precipStatusLabel, /in Pegelprognose verwendet/)
  assert.match(rejected.precipStatusLabel, /zu alt/)
}
{
  const n = normalizeHydroFloodPopup({}, {
    current_q_m3s: 3,
    predicted_q_max_m3s: 4.2,
    station_q_threshold_missing: true,
    flood_status: 'missing_threshold',
    flood_evaluable: false,
    precip_status: 'no_relevant_cell',
    precip_evaluable: true,
    effective_catchment_precip_sum_mm: 0,
    contributing_cell_count: 0,
    current_cell_count: 0,
    incoming_cell_count: 0,
    total_dwell_time_min: 0,
    hydro_flood_risk_score: 0.9,
    confidence: 'high',
  })
  assert.equal(n.predictedQMaxLabel, '4.20')
  assert.equal(n.precipValue, '0.00 mm')
  assert.equal(n.floodLabel, 'nicht bewertbar')
  assert.equal(n.contributingCellCountLabel, '0')
  assert.equal('riskScoreLabel' in n, false)
  assert.equal('confidenceLabel' in n, false)
}
