# Motion-Pipeline-Health und Drift-Alarm

Massiv hohe Kurzfrist-MAE-Werte entstehen typischerweise, wenn Gewitterzellen real ziehen, die Forecast-Positionen aber nahezu am Ursprung stehen bleiben. Dann schlagen Accuracy- und Drift-Auswertung korrekt Alarm; die Schwellen dürfen dafür nicht angehoben werden.

## pySTEPS prüfen

Auf dem Raspberry Pi im Projektverzeichnis:

```bash
cd /home/ki-pi/wetterprojekt
source venv/bin/activate
python -c "import pysteps; print(pysteps.__version__)"
python tools/diagnose_motion_pipeline.py --hours 24
cat train_data/evaluation/motion_pipeline_health.json
```

`install.sh` führt zusätzlich einen Offline-Funktionstest mit `pysteps.motion.lucaskanade.dense_lucaskanade` auf zwei synthetischen Radarframes aus.

## Kritische Werte

* `pysteps_import_ok=false`: pySTEPS ist im aktiven venv nicht importierbar.
* `pysteps_lucaskanade_ok=false`: Import klappt, aber Lucas-Kanade funktioniert nicht.
* `of_available_pct` nahe 0: Optical Flow ist im Livebetrieb praktisch inaktiv.
* `kinematic_source_counts` fast nur `kalman_only`: Forecast nutzt nur den schwächsten Fallback.
* `median_forecast_speed_kmh_by_horizon` deutlich unter realer Zellbewegung: Forecasts stehen nahezu still.
* `zero_forecast_pct_by_horizon` hoch: viele Forecast-Punkte liegen weniger als 0,5 km vom Ursprung entfernt.

## Maßnahmen

```bash
cd /home/ki-pi/wetterprojekt
source venv/bin/activate
pip install --upgrade numpy scipy pysteps
# Auf Raspberry Pi/aarch64 falls nötig:
pip install git+https://github.com/pySTEPS/pysteps
./install.sh
python tools/diagnose_motion_pipeline.py --hours 24
cat train_data/evaluation/motion_pipeline_health.json
```

Wenn pySTEPS funktioniert, sollten `of_available_pct` und die optflow-Anteile in `kinematic_source_counts` steigen. Wenn Optical Flow ausfällt, muss EWMA aus Track-History vor `kalman_only` greifen; `kalman_only` ist nur für Objekte ohne verwertbare History vorgesehen.
