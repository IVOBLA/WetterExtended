import assert from 'node:assert/strict'
import { hydroFloodRows } from '../hydro.js'
import { normalizeHydroFloodPopup } from '../hydroFloodPopup.js'

assert.deepEqual(hydroFloodRows({ stations: [{ station_id: '1' }] }).map(r => r.station_id), ['1'])
assert.deepEqual(hydroFloodRows({ data: { stations: [{ station_id: '2' }] } }).map(r => r.station_id), ['2'])
assert.deepEqual(hydroFloodRows({ data: {} }), [])

assert.equal(normalizeHydroFloodPopup({}, {}).thresholdExceededLabel, 'nicht bewertbar')
assert.equal(normalizeHydroFloodPopup({}, { current_q_m3s: 1, station_q_threshold_m3s: null, flood_status: 'missing_threshold' }).thresholdExceededLabel, 'nicht bewertbar')
assert.equal(normalizeHydroFloodPopup({}, { current_q_m3s: 1, station_q_threshold_m3s: 2, station_q_threshold_source: 'station_override', flood_evaluable: false }).thresholdExceededLabel, 'nicht bewertbar')
assert.equal(normalizeHydroFloodPopup({}, { current_q_m3s: 1, station_q_threshold_m3s: 2, station_q_threshold_source: 'station_override', flood_evaluable: true, flood_expected: false }).thresholdExceededLabel, 'nein')
assert.equal(normalizeHydroFloodPopup({}, { current_q_m3s: 3, station_q_threshold_m3s: 2, station_q_threshold_source: 'station_override', flood_evaluable: true, flood_expected: true }).thresholdExceededLabel, 'ja')
console.log('hydroFloodResponse tests passed')
