import assert from 'node:assert/strict'
import { normalizeHydroFloodPopup } from '../hydroFloodPopup.js'

const staleOldWarning = normalizeHydroFloodPopup({}, {
  current_q_above_threshold: false,
  forecast_evaluation_stale: true,
  forecast_flood_evaluable: false,
  flood_expected: true,
  flood_status: 'deferred_stale_cell_snapshot',
  stale_predicted_q_max_m3s: 12,
  forecast_evaluation_generated_at: '2026-07-16T10:00:00Z',
})
assert.equal(staleOldWarning.forecastStale, true)
assert.equal(staleOldWarning.predictedQMaxLabel, 'nicht aktuell')
assert.equal(staleOldWarning.stalePredictedQMaxLabel, '12.00 (veraltet)')
assert.equal(staleOldWarning.activeFloodWarning, false)
assert.match(staleOldWarning.forecastStatusLabel, /veraltet/)

const staleMeasuredWarning = normalizeHydroFloodPopup({}, {
  current_q_above_threshold: true,
  forecast_evaluation_stale: true,
  forecast_flood_evaluable: false,
  flood_expected: true,
})
assert.equal(staleMeasuredWarning.activeFloodWarning, true)

const freshForecastWarning = normalizeHydroFloodPopup({}, {
  current_q_above_threshold: false,
  forecast_evaluation_stale: false,
  forecast_flood_evaluable: true,
  flood_expected: true,
})
assert.equal(freshForecastWarning.activeFloodWarning, true)
