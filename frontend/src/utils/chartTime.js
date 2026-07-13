/**
 * B354: Formatiert einen ISO-UTC-Zeitstempel fuer Chart-Achsen/Tooltips.
 * Liefert einen leeren String bei fehlendem oder ungueltigem Wert, statt zu werfen.
 */
export function formatChartTimestamp(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString('de-AT', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/**
 * B354: Baut eine idx -> ts Lookup-Map aus einer Chart-Datenserie.
 * Erwartet Objekte mit den Feldern {idx, ts}. Zeilen ohne ts werden uebersprungen.
 */
export function buildIdxTimestampMap(series) {
  const map = new Map()
  for (const row of series || []) {
    if (row && row.ts) map.set(row.idx, row.ts)
  }
  return map
}
