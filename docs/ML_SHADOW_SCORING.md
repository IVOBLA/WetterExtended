# ML-Shadow-Scoring / Re-Gating (Z02)

## Problem (verifiziert)
Das ML-Gate liest die ML-Güte (`breakdown_by_forecast_mode["ml"]["mae_km"]`) aus
verifizierten Forecasts. Solange das Gate ML verwirft, entstehen keine ML-Forecasts,
also keine ML-Verifikation → `ml_mae` bleibt eingefroren → ML bleibt verworfen. Deadlock.

## Zielbild: Champion / Challenger
- **Champion (ausgeliefert):** der vom Gate gewählte Forecast (heute: Kinematik). Bleibt
  unverändert und allein maßgeblich für Karte, KMZ, Warnungen.
- **Challenger (Schatten):** die ML-Vorhersage wird – ohne zusätzliche Inferenz, das
  `prediction`-Array existiert bereits – **immer** mitberechnet, in separate Schattenfelder
  geschrieben und **parallel verifiziert**. Sie wird **nicht** ausgeliefert.
- Sobald die gemessene Challenger-Güte den Champion über die bestehende Gate-Marge schlägt,
  re-aktiviert das (unveränderte) Gate ML automatisch.

## Datenfelder (Schatten, je Horizont h)
`forecast_ml_lat_{h}`, `forecast_ml_lon_{h}`, `forecast_ml_x_{h}`, `forecast_ml_y_{h}`,
`forecast_ml_displacement_km_{h}`, `forecast_ml_speed_kmh_{h}`,
`forecast_ml_rejected_{h}`, `forecast_ml_reject_reason_{h}`.
Die ausgelieferten Felder `forecast_lat_{h}` etc. bleiben unangetastet.

## Verifikation
`accuracy_tracker`: liegt für ein Objekt ein Schattenfeld vor und wurde ein reales Actual
gematcht (identische Match-Logik wie für den Champion, inkl. B228-NN-Schwelle), wird der
ML-Punkt zusätzlich bewertet und als Modus `ml` in `breakdown_by_forecast_mode` geführt.
Die Champion-Metriken (Gesamt-MAE, Drift) bleiben unverändert; der Schatten fließt
ausschließlich in den `ml`-Aufschlüsselungszweig.

## Gate
Keine Code-Änderung nötig: `_latest_runtime_mae_by_horizon` erhält durch die
Schattenverifikation endlich frische `ml_mae`-Werte und re-gated nach bestehender Marge.
Benchmark-Zeitstempel + Sample-Anzahl je Horizont werden geloggt (Transparenz; löst auch
Report-Befund #4 „statischer/gecachter ml_mae").

## Sicherheit & Schalter
- Runtime-Schalter `ML_SHADOW_SCORING_ENABLED` (Default `true` nach Implementierung).
- Schalter `false` ⇒ **bit-identisches** heutiges Verhalten (keine Schattenfelder, keine
  ml-Verifikation).
- Keine zusätzliche Modell-Inferenz; Schatten nutzt das bereits vorhandene `prediction`.
- Hailo/Trainer (Phase B) unberührt; rein CPU-seitige Wiederverwendung des Outputs.

## Akzeptanzkriterien
1. `ML_SHADOW_SCORING_ENABLED=false` ⇒ ausgelieferte Forecasts und Champion-Metriken
   unverändert gegenüber Vorzustand.
2. Mit aktivem Schatten und verfügbarem ML-Modell füllt sich
   `breakdown_by_forecast_mode["ml"]` innerhalb eines Verifikationsfensters mit realen Werten.
3. Das Gate kippt einen Horizont genau dann auf `ml`, wenn die Schatten-`ml_mae` die
   `kinematic_mae` um die konfigurierte Marge unterschreitet.
4. Keine zusätzliche Modell-Inferenz pro Zyklus messbar.

## Implementierungs-Decomposition (separate, je verifizierte Prompts)
- **P52** — `prediction.py`: Schattenfelder im gated/rejected-Zweig befüllen
  (ML-Punkt aus vorhandenem `prediction`, Plausibilisierung via `validate_forecast_point`),
  Runtime-Schalter `ML_SHADOW_SCORING_ENABLED`. Champion-Ausgabe unverändert.
- **P53** — `accuracy_tracker.py`: Schattenfelder verifizieren und als Modus `ml` in
  `breakdown_by_forecast_mode` führen; Champion-Metriken unverändert; Benchmark-Log.
- **P54** — Admin/Frontend: Champion- vs. Challenger-`ml_mae` je Horizont grafisch
  darstellen (erfüllt Zieldefinition „Lernfortschritt/Qualität grafisch").
Reihenfolge: P52 → P53 → P54 (P53 benötigt die Felder aus P52).
