## P-M — Forecast-Fachfeatures

| ID | Änderung | Datei(en) | Status |
| --- | --- | --- | --- |
| P-M03 | **Merge-bewusste Tendenz.** `object_tracking.py`: neue reine Helfer (`_merge_prev_area`, `_merge_prev_core`, `_intensity_trend_vs_baseline`, `_size_trend_vs_baseline`); `trend`/`size_trend` vergleichen beim Merge gegen Summe/flächengewichtetes Mittel der Parents statt gegen den dominanten Einzel-Parent → kein Scheinwachstum/Scheinverstärkung. `merge_discontinuity` (Metadatum, kein ML-Feature) wird ins Objekt-JSON geschrieben. `prediction.py` `_classify_tendency`: `of_divergence` als merge-robuster Intensitäts-Tie-Breaker bei neutraler Tracker-Tendenz. | `object_tracking.py`, `prediction.py`, `tests/test_merge_tendency.py` | ✅ erledigt |
| P-M02 | **Feldbasierte Zuggeschwindigkeit im Forecast.** `prediction.py` `_append_kinematic`: bei gültigem optischen Fluss (of_available=1) wird die kinematische Vorhersage aus `of_vx/of_vy` (→ px/min über echtes Frame-Intervall) extrapoliert statt aus der centroid-/Kalman-EWMA; `kinematic_source=optflow_fm<n>`. Behebt falsche Richtungsvorhersage beim Zell-Merge an der Wurzel. Kalman/EWMA bleibt Fallback; Train=Inference gewahrt (gleiche Quelle in path_*-Vorbelegung). | `prediction.py`, `tests/test_forecast_uses_optflow.py` | ✅ erledigt |
| P-M04 | **ML-Label-Masking am Merge-Frame.** `intensity_regression.py` (`_build_intensity_dataset`: delta_core/delta_area) und `dataset_builder.py` (`build_classification_dataset`: intensified) schließen Samples aus, deren Jetzt- ODER Ziel-Frame `merge_discontinuity=1` trägt. Reiner Helfer `_merge_contaminated()` (testbar). Verhindert, dass Intensitäts-/Größen-Modelle den künstlichen Merge-Sprung als echten Trend lernen. Positions-Labels (`build_dataset`) bewusst unverändert. | `intensity_regression.py`, `dataset_builder.py`, `tests/test_merge_label_masking.py` | ✅ erledigt |


### B127 — Orts-Treffer bei Rand-Streifen entlang des gesamten Pfades ✅ erledigt
- **B127 — Orts-Treffer bei Rand-Streifen entlang des gesamten Pfades.** Die
  kantengenaue Polygon-vs-Radius-Prüfung lief bisher nur an den 5 diskreten
  Horizonten; zwischen den Horizonten wurde nur der Zellmittelpunkt geprüft.
  Neuer Helfer `_forecast_contour_grazes_segment` interpoliert das
  Forecast-Zentrum in 2-min-Schritten und wertet das vorhergesagte Polygon je
  Sub-Schritt gegen den (ggf. erweiterten) Radius aus. Treffer sobald der
  vorhergesagte Zellrand den Radius streift/überlappt — unabhängig von der
  Radiusgröße. Gilt für forecast + slow_approach. Tests:
  `tests/test_locations_grazing.py`.

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
### B126 — Debug-Export verlustfrei in ≤ 80 MB-Volumes ✅ erledigt
- Ersetzt den Hart-Abbruch (`413 export_too_large`) durch verlustfreie Aufteilung:
  `create_debug_export_volumes()` baut den vollständigen Export (ohne Größenlimit)
  und packt ihn in `…_partNNofMM.zip` ≤ 80 MB (`DEBUG_EXPORT_VOLUME_MAX_BYTES`),
  Text/Diagnose-Dateien zuerst.
- Admin-Download via `…/parts` (Token-Cache) + sequentieller Teil-Download;
  KI-Branch-Push legt alle Volumes + Manifest ab. Keine Datei wird ausgelassen.
- Test: `tests/test_debug_export_volumes.py`.


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

### B127 — Test-Isolation: numpy-Stub-Kontamination von prediction behoben ✅ erledigt
- Ursache des roten `test_pt08…::test_predict_lgbm_vector_nan_for_missing`:
  `test_lstm_feature_mismatch.py` importiert `prediction` mit numpy-Stub
  (asarray = Identität) und stellt das gecachte Modul nicht wieder her →
  Folgetest erbt `prediction.np` mit Listen-Rückgabe → `'list' has no shape`.
- Fix in `tests/conftest.py`: autouse-Teardown `_drop_numpy_contaminated_modules()`
  entfernt ein mit Stub-np kontaminiertes `prediction`/`model_training` nach jedem
  Test (Erkennung: fehlendes `ndarray`). Produktionscode unverändert.
- Test: `tests/test_b127_prediction_isolation.py`.

### B128 — Durchgehende Vorhersage-Zugbahn statt radialem Faecher (erledigt)
- Frontend (MapView.jsx + MapFullscreen.jsx): die bis zu 5 radialen Vorhersage-
  Speichen pro Zelle werden durch EINE durchgehende Polyline ersetzt
  (Ursprung -> +10 -> ... -> +60), mit Stuetzpunkt-Markern (+H min) und groesserem
  Endpunkt. Grau-gestrichelt = kinematische Schaetzung, farbig = KI.
- q10/q90-Einzel-Linien/-Dreiecke entfallen (Reduktion der Linienflut);
  Unsicherheitskorridor optional als Folge-Feature.
- Test: tests/test_b128_forecast_track.py (+ test_frontend_build.py als Build-Gate).

### B125 — EUMETView GetCapabilities robust gegen ParseError/Truncation (erledigt)
- Ursache der IR108-Veraltung: abgeschnittene GetCapabilities-Antworten (Timeout 10 s)
  -> ParseError/fehlender Layer -> get_latest_wms_time() lieferte None -> altes TIFF
  wurde ~11 h still wiederverwendet.
- Fix in cloud_height_from_eumetview.py: Timeout 10->30 s; Vollstaendigkeitspruefung
  (schliessendes </WMS_Capabilities>/</WMT_MS_Capabilities>) + bis zu 3 Neuversuche.
- Test: tests/test_b125_eumetview_caps_robust.py.

### B129 — Test-Isolation des API-Fehler-Logs (erledigt)
- Ursache der vielen Open-Meteo-"Fehler" im Dashboard: pytest-Tests (Outlook/
  Circuit-Breaker) riefen log_api_failure() auf und schrieben synthetische
  Eintraege ('RuntimeError: x', 'ConnectionError: down', ...) in die ECHTE
  train_data/evaluation/api_health.jsonl (install.sh Phase 9).
- Fix in tests/conftest.py: autouse-Fixture lenkt debug_utils._API_HEALTH_FILE
  pro Test in ein tmp-Verzeichnis um. Produktionscode unveraendert.
- Test: tests/test_b129_api_health_isolation.py.

### B130 — Unsicherheitskorridor (q10/q90) als verbreiterndes Polygon (erledigt)
- Frontend (MapView.jsx + MapFullscreen.jsx): erweitert den B128-Zugbahn-Block um
  EIN sich nach vorn verbreiterndes Korridor-Polygon (Flanke q10 hin, q90 zurueck).
  Nur bei KI-Vorhersagen mit Quantilen; kinematische Schaetzungen ohne Korridor.
- Ersetzt die frueheren q10/q90-Einzel-Linien/-Dreiecke durch eine ruhige Cone-Form.
- Test: tests/test_b130_uncertainty_corridor.py (+ test_frontend_build.py als Gate).

### B128 — Volume-Aufteilung nach komprimierter Größe + Dateinamen (erledigt)
- Korrigiert B126: Volumes werden jetzt nach **komprimierter** ZIP-Größe bis ≤ 80 MB gefüllt
  (`EXPORT_VOLUME_MAX_BYTES`), die unkomprimierte Größe ist irrelevant
  (Schätzung via `zlib`-Deflate + Header-Overhead). Dateinamen vereinheitlicht zu
  `wetterextended_debug{N}.zip` (`DEBUG_EXPORT_VOLUME_BASENAME`). Verlustfrei,
  einzelner Eintrag > 80 MB erhält eigenes Volume. Test neu:
  `tests/test_debug_export_volumes.py` (4 Tests, inkl. „unkomprimiert egal").

## B139 – ZIP-Volume-Schätzung nach UTF-8-Bytelänge des Namens (Codex-P2)
Status: ERLEDIGT
Ursache: _estimated_zip_entry_bytes() nutzte 2 * len(arcname) (Zeichen). ZIP-Header
         speichern den Namen als UTF-8-Bytes (lokaler Header + Central Directory).
         Bei ä/ö/Emoji oder langen verschachtelten Pfaden wurde der Overhead
         unterschätzt → ein Volume konnte das 80-MB-Limit real überschreiten.
Fix: 2 * len(arcname.encode("utf-8")). Docstring von create_debug_export_volumes
     auf "komprimierte Größe" korrigiert (war fälschlich "unkomprimiert").
Dateien: debug_export.py, tests/test_b139_zip_estimate_bytes.py (neu)


### ✅ 1L.4 ML-Lead-Time-Labels

Labels für IR-Vorläufer → Radarbestätigung werden in `train_data/cell_lineage/ir_lead_time_labels.jsonl` geschrieben. Training und Modellnutzung folgen später.

| B213 | Split-/Merge-Lineage über `cell_id`: Parent-/Child-Beziehungen, Merge-Aliase und Events `cell_split`/`cell_merge` | `cell_lineage.py`, `main.py`, `object_tracking.py`, `tests/test_b213_split_merge_lineage.py` | ✅ erledigt |
| B214 | Forecast-Error-Breakdown automatisch diagnostizieren: ML vs. kinematic, Richtung, Speed, Match-Type, Coverage und Worst-Forecasts | `forecast_error_diagnosis.py`, `tools/diagnose_motion_pipeline.py`, `app.py`, `drift_detector.py`, `tests/test_b214_forecast_error_diagnosis.py` | ✅ erledigt |

| B215 | Forecast-Error-Detail-Validation: synthetische/zeitlich unmögliche Details aus Diagnose ausschließen und Datenbasis sichtbar machen | `forecast_error_diagnosis.py`, `tools/diagnose_motion_pipeline.py`, `app.py`, `tests/test_b215_forecast_error_detail_validation.py` | ✅ erledigt |

| B227 | Ungueltige Zeitstempel mit doppelter Zeitzone (`+00:00Z`) behoben: zentraler Helper `utc_iso_z()` ersetzt `isoformat()+"Z"` auf tz-aware datetimes | `utils.py`, `drift_detector.py`, `api_health_check.py`, `tests/test_b227_utc_iso_z.py` | ✅ erledigt |

| B228 | Verifikations-Matching gehaertet: strenge, runtime-pflegbare NN-Akzeptanzschwelle `VERIFICATION_NN_MAX_MATCH_KM`. NN-Treffer jenseits der Schwelle = Fehlzuordnung (Bucket `nn_rejected`), nicht in MAE/Hit-Rate/Drift. ID-/cell_id-Treffer distanzunabhaengig gueltig. Match-Typ-Anteile geloggt | `config.py`, `accuracy_tracker.py`, `tests/test_b228_nn_match_threshold.py` | ✅ erledigt |
