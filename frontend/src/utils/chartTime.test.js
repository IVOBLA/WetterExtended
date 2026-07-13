import assert from 'node:assert/strict'
import test from 'node:test'
import { formatChartTimestamp, buildIdxTimestampMap } from './chartTime.js'

test('formatChartTimestamp liefert leeren String fuer fehlende/ungueltige Werte', () => {
  assert.equal(formatChartTimestamp(null), '')
  assert.equal(formatChartTimestamp(undefined), '')
  assert.equal(formatChartTimestamp(''), '')
  assert.equal(formatChartTimestamp('not-a-date'), '')
})

test('formatChartTimestamp formatiert gueltige ISO-Zeitstempel', () => {
  const out = formatChartTimestamp('2026-07-13T06:30:00Z')
  assert.ok(out.length > 0)
  assert.ok(/\d{2}\.\d{2}\./.test(out))
})

test('buildIdxTimestampMap ignoriert Zeilen ohne ts und baut korrekte Zuordnung', () => {
  const series = [
    { idx: 1, ts: '2026-07-13T06:00:00Z' },
    { idx: 2 },
    { idx: 3, ts: '2026-07-13T07:00:00Z' },
  ]
  const map = buildIdxTimestampMap(series)
  assert.equal(map.size, 2)
  assert.equal(map.get(1), '2026-07-13T06:00:00Z')
  assert.equal(map.has(2), false)
  assert.equal(map.get(3), '2026-07-13T07:00:00Z')
})

test('buildIdxTimestampMap behandelt leere/undefined Serie defensiv', () => {
  assert.equal(buildIdxTimestampMap(null).size, 0)
  assert.equal(buildIdxTimestampMap(undefined).size, 0)
  assert.equal(buildIdxTimestampMap([]).size, 0)
})
