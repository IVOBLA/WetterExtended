## Phase A — Stabilisierung (aktiv)

| ID | Status | Beschreibung |
| --- | --- | --- |
| B115 | ✅ Erledigt | Drift-Ursache: Zeitbasis 2 min statt realer 5 min (ARSO INCA, per Debug-Daten Median 5,0 min belegt). PX_TO_KMH 10.0→4.0, FRAME_INTERVAL_MIN 2.0→5.0 (Geometrie-Invariante exakt erhalten). speed_kmh wird zusätzlich mit echtem dt aus History-Timestamps skaliert (robust gegen fehlende Frames). Kinematischer Fallback nutzt `_actual_frame_min()`; Primärpfad gegen doppelte KML-Timestamps gehärtet. +30-Min-Drift von ~13 km auf <1 km reduziert. |
| B116 | ✅ Erledigt | ML-Forecast lief dauerhaft kinematisch: aktive Modelle inkompatibel (LSTM 23-Feat, LGBM 114-Feat) vs. aktuell 119; Retrain blockiert (44<50 Samples). Inkompatibler `current`-Stand wird jetzt quarantänisiert (umbenannt, nicht gelöscht) → sauberer Cold-Start beim nächsten Retrain. Ungeschützte LGBM-Inferenz (intensification/Regressoren) erhält Feature-Count-Gate → kein `[Fatal]`-Logspam. `/api/forecast_stats` liefert `ml_blocked_reason`. Keine Senkung der Trainings-Mindestsamples. |
| B117 | ✅ Erledigt | Geo-only Forecast-Fallback (`prediction._append_kinematic`, Pfad x==0/y==0) nutzte `PX_TO_KMH/60` als km/px → nach B115 (PX_TO_KMH 10→4) 5× zu kurz projiziert (vorher 2×). Ersetzt durch Geometrie-Konstante `1/UPSCALE_FACTOR`. Löst offenen Codex-Inline-Kommentar aus PR #601. Regressionstest `tests/test_b117_geo_only_scaling.py`. |


## B115 – Admin-Export 502 / Prozessabbruch (2026-06-11)
Status: ERLEDIGT
Ursache: Unbehandelte Exception / fehlender Export-Lock → Prozessabbruch für ~2 min
Fix: Exception-Handling, threading.Lock, size-begrenzte Log-Reads, journalctl-Timeout,
     temporäre Datei auf Disk, Secret-Redaktion, Alte-ZIPs-Ausschluss
Dateien: app.py, debug_export.py, tests/test_debug_export.py

## B116 – Open-Meteo Request-Sturm / Circuit-Breaker (2026-06-11)
Status: ERLEDIGT
Ursache: atmospheric_snapshot + outlook_series starten gleichzeitig → 45+ Requests/Lauf →
         SSLError-Kaskade → 429 → 28min Fehler-Run
Fix: api_circuit_breaker.py (neu), Job-Staffelung in scheduler.py,
     _BATCH_SIZE 8→4, _DEFAULT_TTL 60min, read_timeout 30→15s
Dateien: api_circuit_breaker.py (neu), fetch_outlook_series.py, http_retry.py,
         scheduler.py, api_cache.py, tests/test_circuit_breaker.py (neu),
         tests/test_outlook_series.py (neu)

## B117 – Frontend Doppel-Requests (2026-06-11)
Status: ERLEDIGT
Ursache: MapView/MapFullscreen laden objects+forecast doppelt pro Polling-Zyklus;
         alle Radar-Frames parallel beim Öffnen preloaded
Fix: Request-Dedupe + Memory-Cache (3s) in api.js, isLoadingRef in MapView/MapFullscreen,
     Preload-Limit auf ±3 Frames
Dateien: frontend/src/api.js, frontend/src/pages/MapView.jsx,
         frontend/src/pages/MapFullscreen.jsx, tests/test_frontend_build.py (neu)

## B118 – No-Cells KMZ Doppelwrite (2026-06-11)
Status: ERLEDIGT
Ursache: No-Cells-Pfad setzt no_cells_handled nicht, Code fällt in Else-Zweig →
         save_forecast_as_kmz() zweimal aufgerufen
Fix: no_cells_handled = True im No-Cells-Pfad, Else-Zweig nur bei echtem Datenfehler
Dateien: main.py, tests/test_no_cells_path.py (neu)

### B123 — install.sh ML-Feature/Model-Kompatibilitäts-Gate ✅ erledigt
- Neue Phase **8.9** in `install.sh` vor dem Testlauf (Phase 9), beide Modi.
- Prüft `training_meta.json → feature_count` gegen `config.ML_NUM_FEATURES` über die
  kanonische `model_training._check_model_compatibility()` (keine Logik-Duplikate).
- `--mode=full`: inkompatible Modelle werden gelöscht (Neutraining).
- `--mode=upgrade`: Quarantäne via `_quarantine_incompatible_current()`
  (current → current_incompatible_<ts>), Runtime läuft kinematisch bis Retrain (B116-Pattern).
- Test: `tests/test_b123_install_model_gate.py` (von install.sh Phase 9 ausführbar).
- **Phasenbezug:** Bereitet Phase B (U-Net/Hailo-DFC) vor — verhindert, dass nach
  einer Feature-Erweiterung veraltete Modelle still in den kinematischen Fallback rutschen.

### B124 — install.sh Full-Modus leert ALLE Logs vollständig ✅ erledigt
- **Journal:** wirkungslose Per-Unit-`--vacuum-time --unit`-Schleife entfernt;
  ersetzt durch korrektes globales `journalctl --rotate` + `--vacuum-time=1s`.
- **nginx:** `/var/log/nginx/access.log` und `error.log` werden im Full-Modus
  geleert (`truncate -s 0`) + `systemctl reload nginx`/`nginx -s reopen`.
- Behebt: nach `--mode=full` erschienen alte Journal-/nginx-Zeilen weiterhin im
  Debug-Export und Adminpanel als vermeintlich aktuelle Fehler.
- Test: `tests/test_b124_full_mode_log_clearing.py` (von install.sh Phase 9 ausführbar).


### B126 — Accuracy-Health unterscheidet Schönwetter von Defekt ✅ erledigt
- Ursache der Fehlalarme: `scheduler.py` warnte bei 0 verifizierbaren Samples pauschal,
  ohne „keine Zellen im Zeitraum" (legitim) von „Zellen vorhanden, aber forecast_lat_*
  fehlt" (Defekt) zu unterscheiden.
- Fix: neue reine Helferfunktion `accuracy_tracker.classify_zero_sample_health()`
  (wertet letzte 24 h `objects/*.json` aus) + differenziertes Logging/JSONL in `scheduler.py`:
  `no_cells_quiet` (info) / `missing_forecast_fields` (warning) / `zero_samples_despite_forecast` (warning).
- Test: `tests/test_b126_accuracy_health_quiet.py`.
- **Phasenbezug:** wichtig für den wartungsarmen Dauerbetrieb auf Pi 5/Hailo-Zielhardware
  (keine Fehlalarme in Ruhephasen).
