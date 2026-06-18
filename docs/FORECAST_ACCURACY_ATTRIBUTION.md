# Forecast Accuracy Attribution

B211 ergänzt die reine MAE/RMSE-Betrachtung um Einzelfehler und Ursachen-Breakdowns. Drift kann trotz funktionierendem pySTEPS/Optical-Flow auftreten, wenn z. B. ML schlechter als der kinematische Fallback ist, die Richtung des Bewegungsvektors nicht stimmt, der Startpunkt der Zelle springt, die Verifikation das falsche Zielobjekt matched, Split/Merge/ID-Wechsel auftreten, Zellschwerpunkte jittern, Radarframes stale sind oder das Zielframe fehlt.

## Prüfung

```bash
source venv/bin/activate
python tools/diagnose_motion_pipeline.py --hours 24
curl http://localhost:5000/api/forecast_error_breakdown
```

Die Einzelfehler werden in `train_data/evaluation/forecast_error_details.jsonl` geschrieben. Die aggregierte Attribution steht zusätzlich in `train_data/evaluation/accuracy_history.jsonl`, `motion_pipeline_health.json` und über `/api/forecast_error_breakdown` bereit.

## Wichtige Felder

- `forecast_mode`: `ml`, `kinematic` oder `unknown`; trennt ML-Ausgaben von Fallback-Prognosen.
- `kinematic_source`: Quelle des kinematischen Vektors, z. B. `optflow_fm5.0`, `ewma`, `kalman_only`.
- `match_type`: Verifikations-Match (`id`, `cell_id`, `nearest`, `none`). `nearest` deutet häufiger auf ID-/Split-/Merge-Probleme hin.
- `direction_error_deg`: minimaler Winkelabstand 0–180°. 350° vs. 10° ergibt 20°.
- `speed_error_kmh`: Betrag der Differenz zwischen Forecast- und tatsächlicher Geschwindigkeit.
- `forecast_error_km`: Haversine-Distanz zwischen Forecast-Position und verifiziertem Actual.

## Interpretation

- ML schlechter als kinematic → ML-Gating/Fallback prüfen.
- Richtung falsch → Bewegungsvektor, Optical-Flow-Ausrichtung und Koordinatentransformation prüfen.
- `nearest` deutlich schlechter als `id` → Lineage, Split/Merge und Matching prüfen.
- `no_target_frame` hoch → Radarframe-Coverage und effektive Leads prüfen.
- Hoher Speed-Fehler bei moderatem Richtungsfehler → Geschwindigkeits-Skalierung und Lead-Zeit prüfen.
