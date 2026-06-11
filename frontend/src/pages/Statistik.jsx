import React, { useEffect, useMemo, useState } from 'react'
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, RadarChart, PolarGrid,
  PolarAngleAxis, PolarRadiusAxis, Radar,
} from 'recharts'
import api from '../api.js'

const MONTHS = ['Jan','Feb','Mär','Apr','Mai','Jun','Jul','Aug','Sep','Okt','Nov','Dez']
const ROSE16 = ['N','NNO','NO','ONO','O','OSO','SO','SSO','S','SSW','SW','WSW','W','WNW','NW','NNW']
const INTENSITY_LABELS = ['schwach','mittel','stark','hagelverdächtig']
const INTENSITY_COLORS = ['#60a5fa','#f9a825','#c62828','#6a1b9a']

function dirToText(deg) {
  if (deg == null) return '—'
  const normalized = ((deg % 360) + 360) % 360
  const idx = Math.round(normalized / 22.5) % 16
  return `${ROSE16[idx]} (${Math.round(normalized)}°)`
}

function movingAverage(values, window = 7) {
  const out = []
  for (let i = 0; i < values.length; i++) {
    const from = Math.max(0, i - window + 1)
    const slice = values.slice(from, i + 1)
    out.push(slice.reduce((a, b) => a + b, 0) / slice.length)
  }
  return out
}

export default function Statistik() {
  const [years, setYears] = useState([])
  const [year, setYear] = useState(null)
  const [data, setData] = useState(null)
  const [prev, setPrev] = useState(null)
  const [trend, setTrend] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Verfügbare Jahre laden
  useEffect(() => {
    api.get('/api/statistics/years')
      .then(r => {
        const ys = r.years || []
        setYears(ys)
        if (ys.length) setYear(ys[ys.length - 1])
        else setLoading(false)
      })
      .catch(e => { setError(String(e)); setLoading(false) })
  }, [])

  // Mehrjahres-Trend (alle Jahre einmalig laden)
  useEffect(() => {
    if (!years.length) return
    Promise.all(years.map(y => api.get(`/api/statistics/${y}`).catch(() => null)))
      .then(list => {
        setTrend(list.filter(Boolean).filter(d => d.available !== false).map(d => ({
          year: d.year,
          cells_total: d.cells_total ?? 0,
          mean_lifetime_min: d.mean_lifetime_min ?? null,
          dominant_dir_deg: d.dominant_dir_deg ?? null,
        })))
      })
  }, [years])

  // Ausgewähltes Jahr + Vorjahr laden
  useEffect(() => {
    if (year == null) return
    setLoading(true)
    Promise.all([
      api.get(`/api/statistics/${year}`),
      api.get(`/api/statistics/${year - 1}`).catch(() => null),
    ])
      .then(([cur, pre]) => {
        setData(cur && cur.available !== false ? cur : null)
        setPrev(pre && pre.available !== false ? pre : null)
        setLoading(false)
      })
      .catch(e => { setError(String(e)); setLoading(false) })
  }, [year])

  const monthData = useMemo(() => {
    if (!data) return []
    return MONTHS.map((m, i) => ({
      month: m,
      [year]: (data.by_month || [])[i] ?? 0,
      ...(prev ? { [year - 1]: (prev.by_month || [])[i] ?? 0 } : {}),
    }))
  }, [data, prev, year])

  const dayData = useMemo(() => {
    if (!data || !data.by_day) return []
    const days = Object.keys(data.by_day).sort()
    const counts = days.map(d => data.by_day[d])
    const ma = movingAverage(counts, 7)
    let cum = 0
    return days.map((d, i) => {
      cum += counts[i]
      return { date: d, count: counts[i], ma7: Math.round(ma[i] * 10) / 10, cum }
    })
  }, [data])

  const intensityData = useMemo(() => {
    if (!data || !data.intensity_by_month) return []
    return MONTHS.map((m, i) => {
      const row = data.intensity_by_month[i] || [0, 0, 0, 0]
      return { month: m, schwach: row[0], mittel: row[1], stark: row[2], hagelverdächtig: row[3] }
    })
  }, [data])

  const roseData = useMemo(() => {
    if (!data || !data.dir_rose16) return []
    return ROSE16.map((label, i) => ({ dir: label, count: data.dir_rose16[i] ?? 0 }))
  }, [data])

  const lifetimeData = useMemo(() => {
    if (!data || !data.lifetime_bins) return []
    const edges = data.lifetime_bin_edges || []
    return data.lifetime_bins.map((c, i) => {
      const lo = edges[i] ?? i
      const hi = edges[i + 1]
      const label = hi == null ? `${lo}+ min` : (hi >= 100000 ? `${lo}+ min` : `${lo}–${hi}`)
      return { bin: label, count: c }
    })
  }, [data])

  const hourData = useMemo(() => {
    if (!data || !data.by_hour) return []
    return data.by_hour.map((c, h) => ({ hour: `${h}h`, count: c }))
  }, [data])

  if (loading) return <div className="p-6 text-gray-500 animate-pulse">Statistik wird geladen…</div>
  if (error)   return <div className="p-6 text-red-600">Fehler: {error}</div>
  if (!years.length)
    return <div className="p-6 text-gray-500">Noch keine Statistikdaten vorhanden. Sie entstehen, sobald Zellen erkannt und nächtlich aggregiert wurden.</div>

  return (
    <div className="p-6 space-y-8">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-bold">📊 Langzeitstatistik</h1>
        <select
          className="border rounded px-2 py-1 text-sm"
          value={year ?? ''}
          onChange={e => setYear(Number(e.target.value))}
        >
          {years.map(y => <option key={y} value={y}>{y}</option>)}
        </select>
        {data && (
          <span className="text-sm text-gray-500">
            {data.cells_total} Zellen · ⌀ Zugrichtung {dirToText(data.dominant_dir_deg)}
            {data.dir_consistency != null && ` · Konsistenz ${data.dir_consistency}`}
            {data.mean_lifetime_min != null && ` · ⌀ Lebensdauer ${data.mean_lifetime_min} min`}
          </span>
        )}
      </div>

      {!data ? (
        <div className="text-gray-500">Für {year} liegen keine aggregierten Daten vor.</div>
      ) : (
        <>
          {/* 1. Monatsverlauf (+ Vorjahr) */}
          <section>
            <h2 className="font-semibold mb-2">Monatsverlauf</h2>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={monthData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="month" /><YAxis allowDecimals={false} />
                <Tooltip /><Legend />
                <Bar dataKey={String(year)} fill="#2563eb" />
                {prev && <Bar dataKey={String(year - 1)} fill="#9ca3af" />}
              </BarChart>
            </ResponsiveContainer>
          </section>

          {/* 2. Tagesverlauf + 7-Tage-Mittel */}
          <section>
            <h2 className="font-semibold mb-2">Tagesverlauf im Jahr</h2>
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={dayData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" tick={{ fontSize: 10 }} minTickGap={28} />
                <YAxis allowDecimals={false} />
                <Tooltip /><Legend />
                <Line type="monotone" dataKey="count" name="Zellen/Tag" stroke="#2563eb" dot={false} />
                <Line type="monotone" dataKey="ma7" name="7-Tage-Mittel" stroke="#dc2626" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </section>

          {/* 3. Intensitätsverlauf (gestapelt) */}
          <section>
            <h2 className="font-semibold mb-2">Intensitätsverlauf pro Monat</h2>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={intensityData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="month" /><YAxis allowDecimals={false} />
                <Tooltip /><Legend />
                {INTENSITY_LABELS.map((k, i) => (
                  <Bar key={k} dataKey={k} stackId="int" fill={INTENSITY_COLORS[i]} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </section>

          {/* Kumulierte Jahreskurve */}
          <section>
            <h2 className="font-semibold mb-2">Kumulierte Jahreskurve</h2>
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={dayData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" tick={{ fontSize: 10 }} minTickGap={28} />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Line type="monotone" dataKey="cum" name="kumuliert" stroke="#059669" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </section>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            {/* Windrose */}
            <section>
              <h2 className="font-semibold mb-2">Vorwiegende Zugrichtung (Windrose)</h2>
              <ResponsiveContainer width="100%" height={300}>
                <RadarChart data={roseData}>
                  <PolarGrid />
                  <PolarAngleAxis dataKey="dir" />
                  <PolarRadiusAxis />
                  <Radar dataKey="count" stroke="#2563eb" fill="#2563eb" fillOpacity={0.5} />
                  <Tooltip />
                </RadarChart>
              </ResponsiveContainer>
              <p className="text-sm text-gray-500 mt-1">
                Zirkulär gemittelt: <b>{dirToText(data.dominant_dir_deg)}</b>,
                Konsistenz {data.dir_consistency ?? '—'} (1 = geradlinig, 0 = richtungslos).
              </p>
            </section>

            {/* Lebensdauer-Histogramm */}
            <section>
              <h2 className="font-semibold mb-2">Lebensdauer-Verteilung</h2>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={lifetimeData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="bin" tick={{ fontSize: 11 }} /><YAxis allowDecimals={false} />
                  <Tooltip />
                  <Bar dataKey="count" name="Zellen" fill="#7c3aed" />
                </BarChart>
              </ResponsiveContainer>
              <p className="text-sm text-gray-500 mt-1">
                Mittlere Lebensdauer: <b>{data.mean_lifetime_min ?? '—'} min</b>
              </p>
            </section>
          </div>

          {/* Tagesgang */}
          <section>
            <h2 className="font-semibold mb-2">Tagesgang (Zellen pro Stunde)</h2>
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={hourData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="hour" tick={{ fontSize: 11 }} /><YAxis allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="count" name="Zellen" fill="#0891b2" />
              </BarChart>
            </ResponsiveContainer>
          </section>

          {/* Mehrjahres-Trend */}
          {trend.length > 1 && (
            <section>
              <h2 className="font-semibold mb-2">Mehrjahres-Trend</h2>
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <ResponsiveContainer width="100%" height={220}>
                  <LineChart data={trend}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="year" /><YAxis allowDecimals={false} />
                    <Tooltip />
                    <Line dataKey="cells_total" name="Zellen/Jahr" stroke="#2563eb" />
                  </LineChart>
                </ResponsiveContainer>
                <ResponsiveContainer width="100%" height={220}>
                  <LineChart data={trend}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="year" /><YAxis />
                    <Tooltip />
                    <Line dataKey="mean_lifetime_min" name="⌀ Lebensdauer (min)" stroke="#7c3aed" />
                  </LineChart>
                </ResponsiveContainer>
                <ResponsiveContainer width="100%" height={220}>
                  <LineChart data={trend}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="year" /><YAxis domain={[0, 360]} />
                    <Tooltip />
                    <Line dataKey="dominant_dir_deg" name="⌀ Zugrichtung (°)" stroke="#059669" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p className="text-xs text-gray-400 mt-1">
                Zugrichtung in Grad (0°=N, 90°=O). Sprünge nahe 0°/360° sind durch die
                Winkelskala bedingt, nicht durch reale Richtungsumkehr.
              </p>
            </section>
          )}
        </>
      )}
    </div>
  )
}
