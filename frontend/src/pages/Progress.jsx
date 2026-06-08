import React, { useEffect, useState } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import api from '../api.js'

export default function Progress() {
  const [versions, setVersions] = useState([])
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    api.get('/api/progress')
      .then(d => { setVersions(d.versions || []); setLoaded(true) })
      .catch(() => { setLoaded(true) })
  }, [])

  const horizons = [10, 20, 30, 40, 60]
  const lstmSeries = versions.map((v, i) => ({ idx: i + 1, val_loss: v.lstm?.val_loss }))
  const maeSeries = versions.map((v, i) => {
    const h = v.validation?.mae_by_horizon_new || {}
    const row = { idx: i + 1 }
    horizons.forEach(hz => { row[`+${hz}m`] = h[String(hz)] })
    return row
  })
  const aucSeries = versions.map((v, i) => ({ idx: i + 1, auc: v.intensification?.auc }))

  function Chart({ title, data, lines }) {
    return (
      <div className="card mb-4">
        <h3 className="text-lg font-medium mb-2">{title}</h3>
        <ResponsiveContainer width="100%" height={250}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="idx" />
            <YAxis />
            <Tooltip />
            <Legend />
            {lines.map(l => <Line key={l} type="monotone" dataKey={l} stroke="#2563eb" dot={{ r: 3 }} connectNulls />)}
          </LineChart>
        </ResponsiveContainer>
      </div>
    )
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Lernfortschritt</h1>

      <div className="card mb-4 bg-blue-50 border-blue-200 text-sm text-blue-900">
        <p className="font-semibold mb-1">📊 Diese Seite zeigt wie sich die ML-Modelle über die Trainingsversionen entwickeln.</p>
        <p>Jeder Punkt auf den Grafiken entspricht einem abgeschlossenen Trainings-Lauf.
        Die X-Achse zeigt die Versions-Nummer (neueste rechts). Je niedriger MAE und val_loss,
        desto präziser die Vorhersage.</p>
      </div>

      {loaded && versions.length === 0 && (
        <div className="card mb-4 bg-amber-50 border border-amber-300 text-amber-900 text-sm">
          <p className="font-semibold mb-2">⏳ Noch kein Trainings-Lauf abgeschlossen</p>
          <p>
            Das System sammelt automatisch Trainingsdaten, sobald Gewitterzellen erkannt
            werden. Alle Radar-Frames werden bereits archiviert.
          </p>
          <p className="mt-2">
            Der erste Trainings-Lauf startet automatisch (täglich um 03:00 Uhr), sobald
            genügend Zell-Sequenzen gesammelt wurden. Die Grafiken erscheinen nach dem
            ersten erfolgreichen Training.
          </p>
          <p className="mt-2 text-xs text-amber-700">
            <b>Aktueller Modus:</b> Kinematischer Fallback (Bewegungsextrapolation ohne ML) —
            kein trainiertes Modell aktiv.
          </p>
        </div>
      )}

      {versions.length > 0 && (
        <>
          <Chart title="LSTM val_loss (Validierungsverlust)" data={lstmSeries} lines={['val_loss']} />
          <div className="text-xs text-gray-500 -mt-2 mb-4 px-1">
            <b>Was zeigt dieser Graph:</b> Der Validierungsverlust (Loss) des LSTM-Zeitreihenmodells
            nach jedem Training. LSTM lernt Muster aus den letzten N Radar-Frames. Ein sinkender
            val_loss bedeutet, das Modell generalisiert besser auf unbekannte Daten.
            <br/><b>Ziel:</b> Abnehmende Tendenz. Anstieg = Overfitting oder zu wenig Trainingsdaten.
            <br/><b>Einheit:</b> MSE (Mean Squared Error) über normalisierte Positionsvorhersagen.
          </div>

          <Chart title="LightGBM MAE pro Horizont (px)" data={maeSeries} lines={horizons.map(h => `+${h}m`)} />
          <div className="text-xs text-gray-500 -mt-2 mb-4 px-1">
            <b>Was zeigt dieser Graph:</b> Der mittlere absolute Positionsfehler (MAE) des
            LightGBM-Modells in Bildpixeln, getrennt nach Vorhersage-Horizont (+10 bis +60 min).
            <br/><b>Einheit:</b> Pixel (1 px ≈ 0,5 km im originalen Radarbild).
            <br/><b>Interpretation:</b> Längere Horizonte haben typischerweise höheren Fehler — normal.
            Ein MAE von 5 px bei +10 min bedeutet die Zellposition wird im Schnitt 2–3 km verfehlt.
            <br/><b>Ziel:</b> Möglichst niedrige Werte bei allen Horizonten.
          </div>

          <Chart title="Intensification AUC" data={aucSeries} lines={['auc']} />
          <div className="text-xs text-gray-500 -mt-2 mb-4 px-1">
            <b>Was zeigt dieser Graph:</b> Area Under the ROC Curve für die binäre
            Intensivierungs-Klassifikation (wächst die Zelle in den nächsten 20 min?).
            <br/><b>Interpretation:</b> 0,5 = zufällig (wie Münzwurf), 1,0 = perfekt.
            Ein Wert über 0,7 gilt als brauchbar, über 0,8 als gut.
            <br/><b>Ziel:</b> Wert stabil über 0,7.
          </div>

          <div className="card">
            <h3 className="text-lg font-medium mb-2">Versionen</h3>
            <p className="text-xs text-gray-500 mb-2">
              Jede Zeile = ein Trainings-Lauf. <b>Samples</b> = Anzahl Trainingsbeispiele.
              <b> MAE total</b> = gemittelter absoluter Fehler über alle Horizonte (niedriger = besser).
              <b> Status</b>: <span className="text-green-700">promoted</span> = Modell ist aktiv,
              <span className="text-gray-500"> rejected</span> = schlechter als Vorgänger.
            </p>
            <table className="w-full text-sm">
              <thead><tr className="border-b">
                <th className="text-left p-1">Timestamp</th><th className="text-left p-1">Samples</th>
                <th className="text-left p-1">MAE total</th><th className="text-left p-1">Status</th>
              </tr></thead>
              <tbody>
                {versions.map((v, i) => (
                  <tr key={i} className="border-b">
                    <td className="p-1">{v.timestamp_utc}</td>
                    <td className="p-1">{v.num_samples}</td>
                    <td className="p-1">{v.validation?.mae_new?.toFixed?.(4) ?? '—'}</td>
                    <td className="p-1">{v.validation?.status ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
