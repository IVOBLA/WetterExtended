# Forecast-Error-Diagnose (B214)

B211 schreibt Einzelfehler nach `train_data/evaluation/forecast_error_details.jsonl` und aggregierte Attributionen nach `accuracy_history.jsonl`. B214 liest diese vorhandenen lokalen Dateien offline und erzeugt daraus `train_data/evaluation/forecast_error_diagnosis.json`.

Die Diagnose verändert keine Forecast-Logik, erhöht keine Drift-Schwellen und beschönigt keine Metriken. Sie ergänzt den Drift-Alarm nur um vorsichtig formulierte Ursachenhinweise ("wahrscheinlich" bei dünner Datenlage).

## Root-Cause-Codes

| Code | Bedeutung |
| --- | --- |
| `ml_worse_than_kinematic` | ML-Forecasts sind im Kurzhorizont wahrscheinlich schlechter als der kinematische Fallback. |
| `kinematic_worse_than_ml` | Der kinematische Fallback ist wahrscheinlich schlechter als ML. |
| `direction_error_dominates` | Richtungsfehler dominieren wahrscheinlich den Forecast-Fehler. |
| `speed_error_dominates` | Geschwindigkeitsbetragsfehler dominieren wahrscheinlich den Forecast-Fehler. |
| `nearest_match_problem` | Nearest-Matches sind deutlich schlechter als ID-/cell_id-Matches; Split/Merge oder ID-Verlust können die MAE treiben. |
| `cell_id_matching_needed` | ID-Matches sind dünn, nearest dominiert, cell_id ist vorhanden und sollte priorisiert werden. |
| `coverage_limited` | Zu viele Ziel-Frames fehlen; ARSO-Takt, not_new-Skips oder Exportfenster prüfen. |
| `low_sample_count` | Zu wenige verifizierte Kurzhorizont-Samples; Diagnose nicht überinterpretieren. |
| `outlier_dominated` | Wenige Worst-Forecasts dominieren wahrscheinlich die MAE. |
| `motion_pipeline_ok_but_accuracy_bad` | pySTEPS/Optflow wirken gesund, aber Accuracy ist schlecht; Fokus weg von pySTEPS hin zu Richtung, Matching, ML-Gating oder Schwerpunktjitter. |

## Am Pi prüfen

```bash
cd /home/ki-pi/wetterprojekt
source venv/bin/activate
python tools/diagnose_motion_pipeline.py --hours 24
cat train_data/evaluation/forecast_error_diagnosis.json
curl -s http://localhost:5000/api/forecast_error_breakdown | python -m json.tool
```
