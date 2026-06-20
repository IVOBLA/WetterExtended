import assert from 'node:assert/strict'
import test from 'node:test'
import { hasValidHydroImpactLine, hydroFeatureCollection, safeHydroFeatures } from './hydro.js'

const pointFeature = { type: 'Feature', properties: { station_id: 'p1' }, geometry: { type: 'Point', coordinates: [14.1, 46.6] } }
const polygonFeature = { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[[14, 46], [14.1, 46], [14.1, 46.1]]] } }

test('hydroFeatureCollection liefert defensive leere Collections fuer fehlende Envelope-Daten', () => {
  for (const response of [null, {}, { ok: true, data: null }, { ok: true, data: { type: 'FeatureCollection', features: [] } }]) {
    assert.deepEqual(hydroFeatureCollection(response), { type: 'FeatureCollection', features: [] })
    assert.deepEqual(safeHydroFeatures(response), [])
  }
})

test('hydroFeatureCollection akzeptiert direkte und enveloped FeatureCollections', () => {
  const direct = { type: 'FeatureCollection', features: [pointFeature] }
  const enveloped = { ok: true, data: { type: 'FeatureCollection', features: [polygonFeature] } }
  assert.deepEqual(hydroFeatureCollection(direct).features, [pointFeature])
  assert.deepEqual(hydroFeatureCollection(enveloped).features, [polygonFeature])
})

test('safeHydroFeatures ignoriert fehlende Features und kaputte Geometrien', () => {
  const response = { type: 'FeatureCollection', features: [
    { type: 'Feature', properties: {}, geometry: null },
    { type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [14] } },
    { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[]] } },
    pointFeature,
  ] }
  assert.deepEqual(hydroFeatureCollection({ type: 'FeatureCollection' }).features, [])
  assert.deepEqual(safeHydroFeatures(response), [pointFeature])
})

test('hasValidHydroImpactLine verhindert Linien ohne vollstaendige Koordinaten', () => {
  assert.equal(hasValidHydroImpactLine({ relation: 'upstream_catchment_hit', station_lat: 46, station_lon: 14 }), false)
  assert.equal(hasValidHydroImpactLine({ relation: 'upstream_catchment_hit', cell_lat: 46.1, cell_lon: 14.1, station_lat: 46, station_lon: 14 }), true)
})
