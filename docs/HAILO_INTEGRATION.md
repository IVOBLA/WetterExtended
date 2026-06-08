# HAILO_INTEGRATION.md
# WetterExtended — Hailo-Integration, Phasen-Roadmap & Multi-Rechner-Architektur

**Dokumentversion:** 5.1 (Phase A ✅ abgeschlossen | Phase B vorbereitet)
**Stand:** Mai 2026
**Sprache:** Deutsch (verbindlich)
**Zweck:** Übergabe-Dokument für neue Chat-Sessions. Jede hier dokumentierte
Entscheidung ist verbindlich und wird in einer neuen Session NICHT erneut
diskutiert.

---

## 0. Anweisung für die neue Chat-Session

Beim Start einer neuen Session muss Claude folgende Schritte in genau dieser
Reihenfolge ausführen — ohne Rückfragen an den Nutzer:

1. Dieses Dokument vollständig ins Kontext-Fenster laden
2. `zieldefinition.txt` aus dem Project-Knowledge laden
3. Für jeden anstehenden Task: `project_knowledge_search` aufrufen um den
   aktuellen Stand der betroffenen Datei zu prüfen — kein Annehmen ohne Beleg
4. Atomaren Code-Prompt liefern gemäß §15 Konventionen
5. Auf Nutzer-Bestätigung warten bevor nächster Task geliefert wird

Claude darf in einer neuen Session NICHT erneut fragen nach:
- Welche Hardware vorhanden ist (siehe §2)
- Welcher Strategie-Plan gilt (Plan B, siehe §3)
- Welche Rolle der Linux-Rechner hat (Trainer + DFC-Build, siehe §8)
- Welche Sprache (Deutsch)
- Konventionen für Code-Übergabe (siehe §15)

---

## 1. Projekt-Kontext

### 1.1 Projekt
**WetterExtended** (entstanden aus Wetterprojekt) — Lokales Wetterradar- und
Sturmzellen-Tracking-System für Kärnten/Österreich. Hauptorte:
Klagenfurt, Villach, Wolfsberg, Spittal, St. Veit.

Verarbeitet ARSO INCA si0zm Radar-KMZ über HSV-Segmentierung, trackt
Sturmzellen mit Kalman-Filter, sagt Bewegung und Intensität voraus
(LSTM + LightGBM + ConvLSTM), visualisiert in React/Leaflet-Admin-Panel,
exportiert Vorhersage-Pfeile als KMZ.

### 1.2 Nutzer
Horst — kommuniziert auf Deutsch, programmiert Python und Node.js.
Erwartet Code direkt im Chat mit klarer Anweisung ob Datei vollständig oder
nur Abschnitt ersetzt wird, mit exakten Such-/Ersatz-Strings.

### 1.3 Repository
- GitHub: `git@github.com:IVOBLA/WetterExtended.git`
- Branch: `main`
- Lokal auf Pi: `/home/ki-pi/wetterprojekt`
- Nutzer auf Pi: `ki-pi`

---

## 2. Hardware-Stand (Mai 2026)

### 2.1 Was vorhanden ist
- **Raspberry Pi 5 B (16 GB)** — Hauptrechner, in Betrieb
- **Hailo-8 AI Module** (26 TOPS, PCIe Gen3) — montiert, `hailo-all` installiert
- **Raspberry Pi OS Bookworm 64-bit** mit Kernel ≥ 6.6
- **PCIe Gen3** aktiviert in `/boot/firmware/config.txt`

### 2.2 Linux-Trainer-Rechner (vorhanden ab Mai 2026)

**Lenovo ThinkCentre M910q Tiny**
- CPU: Intel Core i7-6700T @ 2,8 GHz (4 Kerne / 8 Threads)
- RAM: 16 GB
- SSD: 512 GB
- OS: **Ubuntu Linux** (x86-64)

Hailo DFC läuft **nativ** auf diesem Rechner — kein WSL2, kein Docker-Umweg nötig.

**Setup-Reihenfolge für Phase B (einmalig):**
1. Hailo DFC installieren: `pip install hailo-dataflow-compiler` (x86-Linux-only Paket)
2. Python-Trainingsumgebung: `pip install torch lightgbm onnx`
3. SSH-Key Pi → M910q einrichten für rsync-Transfer
4. Modell-Sync-Script: `rsync -avz models/ ki-pi@<pi-ip>:~/wetterprojekt/train_data/models/`

### 2.3 Rollenverteilung

| Rechner | Rolle | Phase | Hauptaufgaben |
|---------|-------|-------|---------------|
| **Raspberry Pi 5 + Hailo-8** | Edge | A + B + C | Live-Loop, Inferenz, Datensammlung, Admin-Panel |
| **Lenovo M910q (Ubuntu)** | **Trainer (only)** | B + C | Modell-Training, ONNX-Export, DFC-Build nativ, kein Live-Loop |

**Wichtig:** Der Linux-Rechner ist ausschließlich Trainer. Er übernimmt keine
Inferenz und keine Live-Loop-Funktionen. Im Falle eines Pi-Ausfalls ist KEIN
Failover auf den Linux-Rechner vorgesehen — der Pi ist die einzige
Inferenz-Instanz.

---

## 3. Strategische Entscheidung — Plan B

### 3.1 Entscheidung
Statt zwei kleiner CNNs (Cell-Intensity + Cell-Motion) wird **ein U-Net
Radar-Nowcasting-Modell** auf Hailo umgesetzt — aber erst in Phase B nach
Abschluss aller Stabilitäts-Tasks.

### 3.2 Warum nicht zwei kleine CNNs
Cell-Intensity-CNN (50k Params) + Cell-Motion-CNN (80k Params) bei
30 Zellen pro Frame ≈ 120 ms Inferenzzeit auf Hailo-8. Auf Pi-CPU
≈ 50–100 ms. Bei 120 s Loop-Zeit ist beides unkritisch — der Hailo-
Mehrwert wäre messbar aber bedeutungslos. Die Hardware (26 TOPS)
rechtfertigt nur Modelle die ohne Hailo zu langsam wären.

### 3.3 Warum U-Net
- Komplette Folge-Radarbild-Vorhersage statt nur Zellzentren
- Lernt Niederschlagsfeld-Dynamik (Neuentstehung, Auflösung, Verformung)
- ~2 Mio Parameter — ohne Hailo nicht praktikabel im Live-Loop
- State-of-the-Art Nowcasting (analog Google MetNet, DGMR)

---

## 4. Phasen-Roadmap

| Phase | Inhalt | Dauer | Hardware-Bedarf | Status |
|-------|--------|-------|----------------|--------|
| **A — Stabilität** | Bugfixes, Cleanup, Auth, Trainer-Architektur vorbereiten | 4–6 Wochen | Nur Pi 5 | ✅ **Abgeschlossen** |
| **A.1 — Produktreife (Welle 1)** | Forecast-Einheiten + Frame-Intervall, Geo-Korrektur in ML-Features, Accuracy-Pixel-Maßstab, Flask-Bind 127.0.0.1, KMZ Zip-Slip-Schutz, pytest-fixe, Modell-Promotion (zeitbasierter Split + Mindestsamples), KMZ-Layer (aktuelle Zellen + Locations) | 1–2 Wochen | Nur Pi 5 | 🚧 **In Arbeit** (Prompts P01–P08) |
| **A.3 — API-Resilienz-Hardening** | http_retry Session+Retry, Stale-While-Error-Cache, arome_li via icon_eu, WMS-Version-Vereinheitlichung, Speikkogel-Radius 15→8 km, daily_analyzer UnboundLocalError | 1 Woche | Nur Pi 5 | 🚧 **In Arbeit** (Prompts P-01 … P-09) |
| **B — Hailo + U-Net** | Linux-Rechner anschaffen, Training auslagern, DFC-Pipeline, U-Net, Hailo-Integration | 6–8 Wochen | Pi 5 + Linux-Rechner | ⏳ Offen (wartet auf Linux-Rechner) |
| **C — Skalierung** | Optimierungen, weitere Modelle, KI-Analyse vertiefen, Bugfixes B10–B12 | bei Bedarf | Pi 5 + Linux-Rechner | ⏳ Offen |
| **E — IR-Sat Pre-Convection Tracking** | Hohe Wolken (BT < 230 K) aus EUMETView IR108 als eigenständige Objekte detektieren, tracken und vorhersagen. Pseudo-Zellen erweitern Risk-Grid und KMZ. 300-hPa-Steuerstrom als neue Höhenwind-Schicht. Neue ML-Features (`bt_min_k`, `bt_trend_k_per_min`, `overshooting_top`, `ir_only_precursor`, …) für Radar-Zellen. | 3–4 Wochen | Nur Pi 5 (Inferenz) + Linux-Trainer (Modelle) | 🚧 **Teilweise erledigt** (E1–E5,E7,E9,E10 ✅ — E6,E8 warten auf Linux-Trainer) |

### 4.1 Prompt-Status A.1

| Prompt | Inhalt | Datei(en) | Status |
|---|---|---|---|
| P27 | EWMA-Gewichtung kinematischer Forecast + `TRACK_HISTORY_LEN=6` | `prediction.py`, `object_tracking.py`, `config.py` | ✅ erledigt |

### Pre-Conditions
- ✅ Phase B startet erst NACH vollständiger Phase A → **Phase A ist abgeschlossen**
- ✅ Linux-Rechner (Lenovo M910q, Ubuntu) vorhanden — Hailo DFC direkt installierbar
- ✅ Phase A hat alle Hooks für Linux-Rechner vorbereitet (`LOCAL_TRAINING`-Flag, rsync-Skripte, `/api/hailo/reload`)

---

## 5. Phase A — Stabilität ✅ VOLLSTÄNDIG ABGESCHLOSSEN

### 5.1 Task-Liste

Abarbeitungsreihenfolge war: A1 → A2 → A3 → A4 → A5 → A6 → A8 → A7 → A9 → A10

| # | Task | Datei(en) | Status |
|---|------|-----------|--------|
| A1 | Bugfix `parse_timestamp` | `assign_cape_from_forecast.py` | ✅ erledigt |
| A2 | `radar_download.py`: Timeout + log_api_failure + Retry | `radar_download.py` | ✅ erledigt |
| A3 | `blitz_api.py`: HTTP-Basic-Auth statt URL-Credentials | `blitz_api.py` | ✅ erledigt |
| A4 | Daten-Cleanup-Job (Rotation >90 Tage) | `scheduler.py`, `cleanup_old_data.py`, `config.py` | ✅ erledigt |
| A5 | Speicher-/Disk-Monitoring im Admin-Panel | `app.py`, `frontend/src/pages/Dashboard.jsx` | ✅ erledigt |
| A6 | nginx Basic-Auth für Admin-Panel | `install.sh`, nginx-Config | ✅ erledigt |
| A7 | Open-Meteo Bulk-Query (alle Zellen 1 Request) | `fetch_arome_openmeteo.py`, `fetch_700hpa_wind_per_object_slim.py` | ✅ erledigt |
| A8 | `LOCAL_TRAINING`-Flag einbauen (Trainer-Vorbereitung) | `config.py`, `scheduler.py`, `install.sh`, `app.py`, `Training.jsx` | ✅ erledigt |
| A9 | File-Locking bei JSON-Schreibvorgängen | `runtime_config.py` | ✅ erledigt |
| A10 | ConvLSTM MODEL_PATH via SAVE_PATHS + runtime_config | `radar_convlstm.py` | ✅ erledigt |

### 5.7 Phase A.6 — Produktreife Welle 6 ✅

| # | Task | Datei(en) | Status |
|---|------|-----------|--------|
| B37 | Forecast-Pfad segmentweise h[n]→h[n+1] in `annotate_locations` | `locations_check.py` | ✅ erledigt |
| B38 | Config-Rollback + Training-Range-Checks | `runtime_config.py`, `app.py` | ✅ erledigt |
| B39 | Täglicher API-Connectivity-Check (alle 5 externen APIs) | `api_health_check.py` (neu), `scheduler.py`, `app.py` | ✅ erledigt |


---

## B53 – 12h-Outlook Risikozonen (Frontend + Backend)

**Status:** ✅ Implementiert
**Datum:** 2026-06-02
**Dateien:** `app.py` (neue Route `/api/outlook_risk_grid`), Frontend (Leaflet-Layer + Legende)

### Problem
`outlook_12h.json` wurde korrekt berechnet (36 Punkte × 13 h, CAPE/Wind/Temp), aber in der 12h-Prognose-Ansicht der Karte wurden keine Risikozonen angezeigt.

### Lösung
- `/api/outlook_risk_grid`: Neues Flask-Endpoint, liest `outlook_12h.json`, berechnet Risikoscore pro Punkt und Stunde aus CAPE + Wind, cached Ergebnis (bis Datei-Änderung), gibt GeoJSON-ähnliches Dict zurück.
- Frontend: Neuer `CircleMarker`-Layer in der 12h-Prognose-Ansicht, Tooltip mit CAPE/Wind/Stunden-Offset, Legende ergänzt.
- Cache: File-mtime-basiert (kein unnötiger Re-Parse).

### Score-Formel
CAPE < 200 → 0.0 | 200–500 → 0.1–0.3 | 500–1000 → 0.3–0.6 | 1000–1500 → 0.6–0.8 | >1500 → 0.8–1.0 | Wind > 40 km/h → +0.1

### Benutzerhandbuch
Kapitel „12h-Prognose-Karte und Outlook-Risikozonen" ergänzt.

### 5.7.1 Phase A.6.1 — Hotfixes aus Produktions-Log-Analyse 2026-05-31 ✅ ABGESCHLOSSEN

**Analysiertes Log:** `wetterprojekt_logs_20260531_124939.txt` + `objects_20260531_124949.json`
**Ergebnis:** 1 echter Bug (B51), 1 Falsch-Befund (B52 zurückgezogen)

| # | Task | Datei(en) | Status |
|---|------|-----------|--------|
| B51 | Adaptiver Loop-Intervall: 3-Stufen-Modell eingeführt (aktive Zellen → 2 min; Nachbeobachtung 0–120 min → 5 min; Ruhe ≥ 120 min → 15 min). Der `if not radar_ok:` Skip-Pfad ignorierte `_last_cells_active_ts` und schlief immer 900 s — ebenfalls auf 3-Stufen-Logik umgestellt. `NO_CELLS_SLOW_INTERVAL_TIMEOUT_S` 3600 → 7200 s; `LOOP_INTERVAL_NACHBEOBACHTUNG_S = 300` neu in `config.py`. | `main.py`, `config.py` | ✅ erledigt |
| B52 | ~~`fetch_outlook_series.py`: `windspeed_700hPa` → `wind_speed_700hPa`~~ **ZURÜCKGEZOGEN** — `windspeed_700hPa` wird von Open-Meteo akzeptiert. Nach Neustart 07:18 läuft `outlook_series` fehlerlos (07:48–14:48 alle OK). Die 400-Fehler vor 07:18 kamen ausschließlich von `convective_inhibition`/`precipitable_water` — bereits durch B47 behoben. | — | ❌ Falsch-Befund |
| B53 | Erkennungs-Tuning bei aktiver Konvektion: `FILTER_CONFIG.min_object_area` 800 → 400 px (erfasst Zellen ab ≈ 6 km Durchmesser statt ≈ 9 km); `MORPH_CLOSE_SIZE` 7 → 5 (reduziert Merge-Tendenz bei dicht stehenden Zellen). Geprüft gegen objects_20260531_132235.json: 4 erkannte Zellen bei sichtbar mehr Strukturen im Radarbild. Alle anderen Nowcast/CAPE/MIN_CONTOUR_OVERLAP-Empfehlungen des Analyse-Tools als Falsch-Befunde zurückgewiesen (Code bereits korrekt). | `runtime_overrides.json` | ✅ erledigt |
| B54 | E-Mail-Versand für alle KI-Antworten: Neue Funktionen `send_chat_email()` und `send_filter_suggestion_email()` in `email_notifier.py`. Aufrufe in `app.py` nach `/api/ai_analysis/chat` und `/api/cell_filters/ai_analyze`. Verwendet `AI_ANALYSIS_CONFIG.report_email` — kein separates Konfigurationsfeld. Tägliche Analyse sendet bereits (unverändert). | `email_notifier.py`, `app.py` | ✅ erledigt |
| B55 | `fetch_geosphere_nowcast.py`: 2-Slot-Strategie — aktueller 15-min-Slot wird zuerst versucht (Niederschlag JETZT). Bei HTTP 422 (Slot noch in Berechnung) Fallback auf vorherigen Slot. Behebt `0 mm/h` bei Zellen die gerade erst entstanden sind (Zelle erscheint am Slot-Anfang → alter Slot hatte noch kein Gewitter). | `fetch_geosphere_nowcast.py` | ✅ erledigt |
| B56 | API-Logging vervollständigt: `fetch_outlook_series.py` hatte kein Logging (weder Erfolg noch Fehler sichtbar im Admin-Panel) → `log_http_response()` + `log_api_failure()` + `retry_get()` + HTTPError-Handler pro Batch. `fetch_synoptic_features.py`: `log_api_call()` → `log_http_response()` + `retry_get()`. `fetch_arome_openmeteo.py`: `log_api_call()` → `log_http_response()`. | `fetch_outlook_series.py`, `fetch_synoptic_features.py`, `fetch_arome_openmeteo.py` | ✅ erledigt |
| B57 | Vereinfachte Warn-E-Mail: statt Tabelle aller Horizonte nur noch „Zelle X trifft in ~N Minuten (ca. HH:MM Uhr)" + Karte-Button. 2-Frame-Bestätigung für kinematische Vorhersagen: Ort muss in 2 aufeinanderfolgenden Frames getroffen werden → kein Alarm bei einzelnem Ausreißer. Entwarnung nur wenn vorher Warnung gesendet. | `main.py`, `email_notifier.py` | ✅ erledigt |
| B59 | Polygon-basierte Orts-Treffer + richtungsabhängiges Wachstum: `current` → `_min_dist_to_polygon_km`. `forecast`/`slow_approach` → `_forecast_polygon_at_h(obj, f_lat, f_lon, h)`: verschiebt + skaliert aktuelles Polygon richtungsabhängig (scale_NS ≠ scale_EW). Wachstumsraten aus lineare Regression über `lat_span_km`/`lon_span_km` in History. `object_tracking.py` schreibt `lat_span_km`, `lon_span_km`, `area_km2` pro Frame. Fallback auf Pfad-Distanz wenn kein Polygon. | `object_tracking.py`, `locations_check.py` | ✅ erledigt |
| B58 | **Root Cause GeoSphere Nowcast 422:** API erwartet `lat_lon=46.526,14.548` (kombiniert), Code sendete `lat=46.526&lon=14.548` (getrennt) → HTTP 422 seit Inbetriebnahme. Bestätigt durch Response-Body `{"detail":[{"loc":["query","lat_lon"],"msg":"Field required"}]}`. Fix: `_qparams` auf `("lat_lon", f"{lat},{lon}")` umgestellt. Zusätzlich B55-Retry-Logik repariert: `abort_on_4xx=False` + 3 Retries durch `max_retries=1` + HTTPError-Abfang ersetzt (verhindert 63 s Wartezeitverschwendung/Zyklus). `api_health_check.py` ebenfalls korrigiert. | `fetch_geosphere_nowcast.py`, `api_health_check.py` | ✅ erledigt |

---

## B55 – Drei Korrekturen: CAPE-Toleranz, Size-Pixel-Scale, Ausblick-Stunden-Filter

**Status:** ✅ Implementiert
**Datum:** 2026-06-02
**Dateien:** `assign_cape_from_forecast.py`, `main.py`, `frontend/src/pages/Ausblick.jsx`, `tests/test_cape_timestamp_lookup.py`

### Fix 1 – CAPE Nearest-Match-Toleranz ±3h → ±2h
AROME-Modellläufe alle 3h → ±2h deckt alle Verfügbarkeitslücken ab. ±3h war meteorologisch grenzwertig (CAPE kann sich in 3h stark ändern). Nach B54-Formatfix trifft Exact-Match fast immer; ±2h ist ausreichender Fallback.

### Fix 2 – Size-Pixel-Scale: verarbeitetes Bild (P1 Codex-Finding)
`_img_height, _img_width = image.shape[:2]` verwendete das rohe heruntergeladene Radarbild (800×600). `detect_and_track_objects()` schneidet intern auf `BBOX_KAERNTEN_EXTENDED` zu und skaliert mit `UPSCALE_FACTOR=3` hoch. `area_px`/`radius_px` der Objekte stammen aus dem hochskalierten Bild. Pixel-Scale-Berechnung jetzt: `geo_utils.kml_bounds["img_width/height"]` (befüllt von `crop_and_upscale_to_bbox()`) + `BBOX_KAERNTEN_EXTENDED` als tatsächliche Bounds. Berechnung erfolgt NACH `detect_and_track_objects()`. Log: `[SIZE-REG] pixel_scale: NxMpx → km/px_x=0.17xx`.

### Fix 3 – Ausblick.jsx: Risiko-Marker nach Stunden-Slider filtern (P2 Codex-Finding)
`pt.max_score` zeigte Maximum über alle 12 Stunden. Bei Slider auf +1h wurden Risiken aus +12h als aktuell dargestellt. Fix: `pt.hourly.find(h => h.hour === hour)` mit Nearest-Fallback. Tooltip zeigt jetzt `+Nh` der tatsächlich ausgewählten Stunde.

## B54 – CAPE Timestamp Nearest-Match Fix

**Status:** ✅ Fix implementiert  
**Datum:** 2026-06-02
**Fehler-Log:** `[API-FAIL] GeoSphere-CAPE: no-forecast-for-2026-06-02T04:00+00:00 (fallback=True, http=None)`

### Root Cause
Zwei kombinierte Probleme:
1. **ISO-8601-Format-Mismatch:** Code suchte `T04:00+00:00` (ohne Sekunden), GeoJSON enthielt `T04:00:00+00:00` (mit Sekunden) → String-Vergleich findet keinen Match.
2. **Radar-Timestamp ohne UTC-Offset:** Radar-Frame-Zeit ist MESZ (UTC+2), Code hat nicht korrekt auf UTC umgerechnet, bevor er im Forecast (UTC) gesucht hat.

### Fix
- Neue Hilfsfunktionen `_parse_cape_ts()` und `_find_nearest_cape_ts()` in der CAPE-Lookup-Datei.
- Alle Timestamps werden zu `datetime`-Objekten (UTC, timezone-aware) normalisiert.
- Nearest-Neighbor-Suche mit ±3h Toleranz ersetzt exakten String-Vergleich.
- `API-FAIL` wird nur noch geloggt wenn **überhaupt keine** CAPE-Daten verfügbar sind (nicht bei Nearest-Match-Nutzung).
- `zoneinfo`-basierte Europe/Vienna-Konvertierung für korrekte MESZ↔UTC-Umrechnung.

### Neues Log-Verhalten
- Bei exaktem Match: `[CAPE] Suche CAPE für Zeitstempel: 2026-06-02T04:00:00+00:00` (wie bisher)
- Bei Nearest-Match: `[CAPE] Nearest-Match: 2026-06-02T06:00:00+00:00 (Δ=120 min von Ziel T04:00)`
- Kein `API-FAIL` mehr bei Nearest-Match innerhalb ±3h

**Bestätigter Normalbetrieb (kein Fix):**
- `auth/refresh 401` (09:16, 12:10) → abgelaufenes Refresh-Token (~1–3 h), erwartet
- `auth/refresh 401+200` (06:37, alter Code 107937) → B48 bereits behoben, in 130663 nicht mehr
- Flask `WARNING: Development server` → nginx proxied extern, kein neues Problem
- `retrain_interval lstm_trained=False` → kein Gewitterlag = keine Trainingsdaten, korrekt
- `ai_analysis übersprungen (only_if_cells=True)` → korrekt

**Hailo-Integrationsstatus (unverändert):**
- Phase 1 (Installation) ✅ — Phase 2 (HEF-Export) 🔲 — Phase 3 (Runtime) 🔲

---

### 5.8 Phase A.7 — Produktreife Welle 7: Zeitstempel-Korrektheit ✅

Alle Zeit- und Datumsangaben im Projekt müssen den Zeitpunkt der **Aufnahme
bzw. Erfassung** widerspiegeln — nicht den Verarbeitungszeitpunkt.

Systematische Analyse aller externen Schnittstellen und Zeitstempel-Verwendungen
ergab 7 Bugs (T1–T4, A3–A5) sowie 10 als korrekt bestätigte Stellen.

| # | Task | Datei(en) | Status |
|---|------|-----------|--------|
| B40 | `get_acquisition_timestamp()` Hilfsfunktion — liest HTTP Last-Modified aus `data/.kmz_last_modified` und gibt Wien-Lokalzeit zurück | `radar_download.py` | ✅ erledigt |
| B41 | `object_tracking.py`: "latest"-Modus und ValueError-Fallback nutzen `get_acquisition_timestamp()` statt `datetime.now()` | `object_tracking.py` | ✅ erledigt |
| B42 | `fetch_arome_openmeteo.py`: `_nearest_hour_str(ref_ts_str)` + `_fetch_arome_li_via_icon_eu(valid, ref_ts_str)` — Aufnahme-Zeitstempel für icon_d2 und GFS-LI-Slot-Selektion | `fetch_arome_openmeteo.py` | ✅ erledigt |
| B43 | `app.py`: `last_obj_utc` aus Dateinamen-Parse statt `os.path.getmtime()` — konsistent mit `last_radar_utc` | `app.py` | ✅ erledigt |
| B44 | `fetch_700hpa_wind_per_object_slim.py`: `_nearest_hour_str(ref_ts_str)` für 700-hPa-Slot und Cache-Key | `fetch_700hpa_wind_per_object_slim.py` | ✅ erledigt |
| B45 | `fetch_openmeteo_extended.py`: `_nearest_quarter_str(ref_ts_str)` + `_nearest_hour_str(ref_ts_str)` für alle 4 Requests (Böen, Druckflächen, LPI, GFS) | `fetch_openmeteo_extended.py` | ✅ erledigt |
| B46 | `fetch_synoptic_features.py`: `_nearest_hour(ref_ts_str)` für 500-hPa-Slot und Cache-Key | `fetch_synoptic_features.py` | ✅ erledigt |
| B80 | `debug_utils.py`: `debug_log()` verwendete `datetime.now()` (Lokalzeit CEST) statt `datetime.utcnow()`. Folge: DEBUG-Zeilen lagen 2 Stunden vor API-FAIL-Zeilen (die bereits UTC verwendeten). Fix: `datetime.now()` → `datetime.utcnow()` in `debug_log()`. | `debug_utils.py` | ✅ erledigt |

**Als korrekt bestätigt (kein Fix nötig):**

| Datei | Begründung |
|-------|-----------|
| `fetch_atmospheric_snapshot.py` — `_nearest_hour_str()` | Geplanter Job (alle 30 min, Frame-unabhängig) → `datetime.now()` korrekt |
| `assign_cape_from_forecast.py` — `_build_cape_url()` BBOX | `south,west,north,east` laut GeoSphere API-Spec verifiziert |
| `fetch_geosphere_nowcast.py` — Parameter-Format | `parameters=rr&parameters=ff&...` (wiederholt) korrekt für Nowcast-Endpoint |
| `fetch_tawes_gust.py` — `?parameters=RR,DD,...` | Kommasepariert korrekt für TAWES station/current-Endpoint |
| `cloud_height_from_eumetview.py` — WMS 1.1.1 + `srs=` | Axis-Order-Fix bereits vorhanden (1.3.0 würde BBOX-Achsen tauschen) |
| `blitz_api.py` — HTTP Basic Auth | Credentials nur im Header, nicht in URL |
| `fetch_openmeteo_extended.py` — LPI via `/v1/dwd-icon` | `/v1/forecast` liefert HTTP 400 für LPI — DWD-Endpoint korrekt |
| `radar_download.py` — `If-Modified-Since` | 304 vermeidet unnötigen Re-Download korrekt implementiert |
| `fetch_700hpa_wind_per_object_slim.py` — `get_700hpa_wind()` Einzelabfrage | Standalone-Funktion ohne Frame-Kontext — `_nearest_hour_str()` ohne Argument OK |
| `fetch_atmospheric_snapshot.py` — Bulk-Batching | Batches à 8 Locations korrekt, verhindert Open-Meteo-Timeout bei > 8 Orten |

### 5.6 Phase A.5 — Produktreife Welle 5 ✅

| # | Task | Datei(en) | Status |
|---|------|-----------|--------|
| B31 | No-cell vollständig: leere locations + KMZ + Auto-Entwarnung | `main.py` | ✅ erledigt |
| B32 | Training/Evaluation/Laden mit Runtime-Horizonten | `model_training.py` | ✅ erledigt |
| B33 | Promotion mit Compat-Check + Holdout-MAE-Validierung | `model_training.py` | ✅ erledigt |
| B34 | `ADMIN_REQUIRE_TOKEN=1` default in install.sh + Token-Endpoint nginx-only | `install.sh`, `app.py` | ✅ erledigt |
| B35 | Unit-Tests Einheitenkonsistenz (`tests/test_units.py`) | `tests/test_units.py` (neu) | ✅ erledigt |
| B36 | `package-lock.json` generieren für reproduzierbare Frontend-Builds | `install.sh` | ✅ erledigt |

### 5.5 Phase A.4 — Produktreife Welle 4 ✅

| # | Task | Datei(en) | Status |
|---|------|-----------|--------|
| B26 | No-cell-Frames immer als leeres JSON speichern | `main.py` | ✅ erledigt |
| B27 | Runtime-Horizonte in Dataset-Build + Modell-Kompatibilitätsprüfung | `dataset_builder.py`, `model_training.py` | ✅ erledigt |
| B28 | Cold-Start-Promotion mit Sample-Check + coverage_rate in Accuracy | `model_training.py`, `accuracy_tracker.py` | ✅ erledigt |
| B29 | fail-closed Token-Auth + `pytest.ini` | `app.py`, `pytest.ini` (neu), `tests/conftest.py` | ✅ erledigt |
| B30 | Echte Zeitdifferenzen im kinematischen Forecast (px/min aus Timestamps) | `object_tracking.py`, `prediction.py` | ✅ erledigt |

### 5.4 Phase A.3 — Produktreife Welle 3 ✅

| # | Task | Datei(en) | Status |
|---|------|-----------|--------|
| B22 | Lineage-Features in `ML_CELL_FEATURES` (`active_frames_norm`, `total_active_frames_norm`, `is_merged`, `is_split`) | `config.py`, `object_tracking.py` | ✅ erledigt |
| B23 | Drift-Detection: MAE-Trendüberwachung + E-Mail-Alarm | `drift_detector.py` (neu), `email_notifier.py`, `scheduler.py`, `app.py` | ✅ erledigt |
| B24 | Frontend Error-Boundary + Offline-Indikator | `frontend/src/ErrorBoundary.jsx` (neu), `frontend/src/App.jsx` | ✅ erledigt |
| B25 | Echter Day-Holdout für Test-Metriken (letzter Tag kein Training-Input) | `dataset_builder.py`, `model_training.py` | ✅ erledigt |


### 5.4 Phase A.3 — API-Resilienz-Hardening 🚧

| # | Task | Datei(en) | Status |
|---|------|-----------|--------|
| P-01 | `http_retry.py` mit `requests.Session` + `HTTPAdapter` + urllib3-`Retry` | `http_retry.py` | 🚧 in Arbeit |
| P-02 | `fetch_openmeteo_extended.py` auf `retry_get` umstellen + Stale-While-Error-Fallback | `fetch_openmeteo_extended.py` | 🚧 in Arbeit |
| P-03 | `fetch_atmospheric_snapshot.py` `_bulk_get` auf `retry_get`, Timeout 15→25 s, Batching > 8 Locations | `fetch_atmospheric_snapshot.py` | 🚧 in Arbeit |
| P-04 | `fetch_arome_openmeteo.py`: `lifted_index` aus icon_d2 entfernen, separat aus icon_eu holen (`_fetch_arome_li_via_icon_eu`), Timeout 15→25 s | `fetch_arome_openmeteo.py` | 🚧 in Arbeit |
| P-05 | `cloud_height_from_eumetview.py`: WMS-GetCapabilities-Version vereinheitlichen (1.3.0 → 1.1.1, identisch zu GetMap), Namespace-tolerantes Dimension-Parsing | `cloud_height_from_eumetview.py` | 🚧 in Arbeit |
| P-06 | `api_cache.py`: Funktion `cache_get_stale(key, max_stale_seconds)` ergänzt — Voraussetzung für P-02/P-04 | `api_cache.py` | 🚧 in Arbeit |
| P-07 | `config.py`: STATIC_EXCLUSION_ZONES Speikkogel Radius 15 → 8 km (verhindert False-Negatives östlich Wolfsberg) | `config.py` | 🚧 in Arbeit |
| P-08 | Doku-Updates Benutzerhandbuch §31 + HAILO_INTEGRATION §5.4 | `docs/WetterExtended_Benutzerhandbuch.md`, `docs/HAILO_INTEGRATION.md` | 🚧 in Arbeit |
| P-09 | `daily_analyzer.py`: UnboundLocalError `ML_FORECAST_HORIZONS_MIN` durch doppelten Import in `build_system_report()` fixen | `daily_analyzer.py` | 🚧 in Arbeit |
| P-10 | `app.py` `api_risk_grid()`: Bereichsradien reduziert (CELL_RANGE 60→30 km, TRACK_RANGE 30→20 km, BOLT_RANGE 30→20 km, ATM_RANGE 45→30 km, IR-Track 40→25 km, in_track-Schwelle 15→10 km) und als Runtime-Override konfigurierbar; `Configuration.jsx`: vollständige Parameter-Referenz mit Suche für alle 34 runtime_config-Keys | `app.py`, `frontend/src/pages/Configuration.jsx` | 🚧 in Arbeit |

**Status-Update:** Sobald ein Prompt eingespielt und verifiziert ist, Status auf ✅ erledigt.

- **UI-Paket Training + Live-Karte** (`Training.jsx`, `MapView.jsx`):
  Trainings-Schedule-Formular: erläuternde Hilfetexte unter jedem Feld (7 Felder).
  Live-Karte: KMZ-Download-Button entfernt (KMZ bleibt über FTP/Auto-Export verfügbar).
  Risikozonen-Status in Timing-Bar integriert (kompakter Inline-Span statt separater Banner).

#### Risk-Grid Stabilitätsfixes ✅

| Item | Beschreibung | Status |
|---|---|---|
| RG1 | `BBOX_KAERNTEN_EXTENDED` Import in `api_risk_grid()` | ✅ erledigt |
| RG2 | BBOX Dict-Format (north/south/east/west) korrekt verarbeiten | ✅ erledigt |
| RG3 | IR-Tracks einmalig vor Grid-Schleife laden | ✅ erledigt |
| RG4 | IR-Score vor Risk-Klassifikation addieren | ✅ erledigt |
| RG5 | `MapFullscreen.jsx` Risk-Grid-Fehleranzeige | ✅ erledigt |
| RG6 | Alle 3 `test_risk_grid_api.py`-Tests grün | ✅ erledigt |


### 5.4.1 Hintergrund

Bei aktiver Konvektion (mehrere Sturmzellen gleichzeitig) verbinden sich
4 Module simultan zu Open-Meteo, je mit Bulk-Requests von 5–20 Koordinaten.
Open-Meteo's CDN zeigt unter dieser Last zeitweise 502/504-Phasen und
TLS-EOF-Verbindungsabbrüche (siehe API-Health-Log 26.05.2026, 14:30–15:30).

Bei 0 aktiven Zellen sind 4 dieser Module inaktiv (Eingangs-Prüfung
`if not valid: return`), nur der `atmospheric_snapshot_job` (alle 30 min,
unabhängig von Zellen) zeigt die API-Probleme. Bei Konvektion vervielfacht
sich die Fehlerrate proportional zur Zellzahl — daher ist Phase A.3 vor
der nächsten Sommer-Konvektionsphase abzuschließen.

### 5.3 Phase A.2 — Produktreife Welle 2 ✅

| # | Task | Datei(en) | Status |
|---|------|-----------|--------|
| B16 | POST-Routen Token-Auth (`ADMIN_API_TOKEN`) | `app.py`, `frontend/src/api.js`, `install.sh` | ✅ erledigt |
| B17 | Einheitlicher HTTP-Retry-Wrapper | `http_retry.py` (neu), `blitz_api.py`, `fetch_arome_openmeteo.py`, `fetch_geosphere_nowcast.py`, `cloud_height_from_eumetview.py`, `fetch_700hpa_wind_per_object_slim.py` | ✅ erledigt |
| B18 | `requirements.lock` + `npm ci` | `install.sh` | ✅ erledigt |
| B19 | systemd Watchdog (`Type=notify`, `WatchdogSec=60`, Heartbeat-Thread) | `watchdog_heartbeat.py` (neu), `scheduler.py`, `app.py`, `main.py`, `install.sh` | ✅ erledigt |
| B20 | journald-Limit 200 MB (SD-Karten-Schutz) | `install.sh` (Drop-In `/etc/systemd/journald.conf.d/wetterprojekt.conf`) | ✅ erledigt |
| B21 | Wöchentliches Backup-Script (Modelle + Secrets) | `backup_wetterprojekt.sh` (neu), `scheduler.py` | ✅ erledigt |

### 5.2 Umgesetzte Implementierungen (tatsächlicher Code-Stand)

#### A1 — `parse_timestamp` Bugfix ✅
**Datei:** `assign_cape_from_forecast.py`
**Behoben:** Schleife verwendet nun korrekt `fmt` aus der Schleifen-Variable statt
hartecodierten Format-String. ISO-Format mit Zeitzone wird gesondert behandelt
(timezone-aware vs. naive).

#### A2 — `radar_download.py` Hardening ✅
**Datei:** `radar_download.py`
**Umgesetzt:**
- `_MAX_RETRIES = 3` mit `_RETRY_BACKOFF = [2, 5, 10]` (exponentiell)
- `_HEADERS` mit User-Agent `WetterExtended/1.0 (Raspberry Pi 5; Kaernten weather tracking)`
- Timeout 30 s am GET-Request
- `log_api_failure("ARSO-Radar", ...)` bei Timeout, HTTPError, ungültiger ZIP
- **Bonus:** `If-Modified-Since`-Header → 304 Not Modified bei unverändertem Bild
  (spart Bandbreite + API-Quota)
- `log_api_call()` für Dashboard-Statistik

#### A3 — `blitz_api.py` Basic-Auth ✅
**Datei:** `blitz_api.py`
**Umgesetzt:**
```python
# Credentials aus URL entfernt:
response = requests.get(url, auth=(USERNAME, PASSWORD), timeout=10)
```
- `log_api_failure` bei Timeout, HTTPError, allgemeinen Exceptions
- `log_api_call` für Dashboard-Statistik

#### A4 — Daten-Cleanup-Job ✅
**Neue Datei:** `cleanup_old_data.py`
**Modifikation:** `scheduler.py`, `config.py`

Konfiguration in `config.py`:
```python
DATA_RETENTION_DAYS = 90
DATA_CLEANUP_CRON_HOUR = 4
DATA_CLEANUP_CRON_MINUTE = 30
DATA_CLEANUP_RETENTION_OVERRIDE = {}   # per-Verzeichnis überschreibbar
DATA_CLEANUP_PATHS = [
    "train_data/radar/", "train_data/objects/", "train_data/weather/",
    "train_data/wind/", "train_data/cape/", "train_data/lightning/",
    "train_data/ir/", "train_data/ir_cells/", "train_data/cloud/",
    "train_data/arome/",
]
```
Loggt Anzahl gelöschter Dateien + freigegebenen Speicher in
`train_data/evaluation/cleanup_log.jsonl`. Scheduler-Job `data_cleanup`
läuft täglich um 04:30 (nach Nightly-Retrain um 03:00). Job ist immer
aktiv, unabhängig von `LOCAL_TRAINING`.

#### A5 — Disk-Monitoring ✅
**Modifikation:** `app.py`, `frontend/src/pages/Dashboard.jsx`

Endpoint `/api/disk` liefert `total_gb`, `used_gb`, `free_gb`, `used_pct`,
`warning` (>80%), `critical` (>90%). Dashboard zeigt farbcodierte Status-Karte
(grün/gelb/rot) + kritisches Banner wenn >90%.

#### A6 — nginx Basic-Auth ✅
**Modifikation:** `install.sh` (Phase 7d — nginx)

- Zufallspasswort via `openssl rand -base64 16` beim ersten Setup
- Gespeichert in `.admin_password` (Modus 600)
- `htpasswd` bei Neuinstallation generiert; bei Upgrade aus `.admin_password`
  wiederhergestellt falls `/etc/nginx/.htpasswd` fehlt
- **Sonderfall `/karte`:** ohne Auth erreichbar (öffentliche Leaflet-Karte)
- API-Endpunkte `/api/objects`, `/api/forecast` u.a. ebenfalls ohne Auth
  (nur-lesend, für eingebettete Karten)

#### A7 — Open-Meteo Bulk-Query ✅
**Dateien:** `fetch_arome_openmeteo.py`, `fetch_700hpa_wind_per_object_slim.py`

Beide Dateien nutzen komma-separierte Koordinaten — ein Request für alle Zellen:
```python
lats = ",".join(f"{obj['lat']:.4f}" for _, obj in valid)
lons = ",".join(f"{obj['lon']:.4f}" for _, obj in valid)
bulk_url = f"{OPEN_METEO_URL}?latitude={lats}&longitude={lons}&hourly=..."
```
Zusätzlich: `api_cache.py` mit Memory + Disk-Cache (TTL 30 min für icon_d2,
60 min für icon_global) verhindert redundante Requests.
`fetch_atmospheric_snapshot.py` (neu) holt Bulk-Werte für Kärnten-Referenzpunkte
unabhängig von Zellen.

#### A8 — `LOCAL_TRAINING`-Flag ✅
**Dateien:** `config.py`, `scheduler.py`, `install.sh`, `app.py`, `Training.jsx`

```python
# config.py
LOCAL_TRAINING: bool = True
```
- `scheduler.py`: Guard-Block in `create_scheduler()` — Training-Jobs
  (rebuild_dataset, retrain_interval, retrain_nightly, convlstm_weekly)
  nur wenn `LOCAL_TRAINING=True`
- `install.sh`: `--no-training` Flag schreibt `LOCAL_TRAINING=False`
  in `runtime_overrides.json`
- `app.py`: `/api/local_training` Endpoint
- `Training.jsx`: gelbes Banner wenn deaktiviert
- `/api/hailo/reload` (POST): wird von `sync_models_to_pi.sh` nach rsync
  aufgerufen um HEF-Cache zu leeren

#### A9 — File-Locking ✅
**Datei:** `runtime_config.py`
```python
# Lesen: Shared Lock (parallele Leser OK)
fcntl.flock(f, fcntl.LOCK_SH)

# Schreiben: Exclusive Lock auf tmp-Datei
fcntl.flock(f, fcntl.LOCK_EX)
# + atomic os.replace() + os.fsync() für SD-Karten-Sicherheit
```
Zusätzlich `threading.RLock` für Intra-Prozess-Safety.

#### A10 — ConvLSTM MODEL_PATH ✅
**Datei:** `radar_convlstm.py`
```python
def _get_model_path() -> str:
    try:
        import runtime_config
        override = runtime_config.get("CONVLSTM_MODEL_PATH", None)
        if override and isinstance(override, str):
            return override
    except Exception:
        pass
    return os.path.join(SAVE_PATHS["models"], "current", "radar_convlstm.keras")

MODEL_PATH = _get_model_path()  # Rückwärtskompatibilität
```
Kein Hardcoding. Überschreibbar via `runtime_overrides.json`.

#### A7 — Vollständiges API-Request/Response-Logging ✅
**Dateien:** `debug_utils.py`, `blitz_api.py`, `radar_download.py`,
`cloud_height_from_eumetview.py`, `fetch_openmeteo_extended.py`,
`fetch_atmospheric_snapshot.py`, `fetch_geosphere_nowcast.py`

**Umgesetzt:**
- `log_api_call()`: Keine Kürzung mehr (`_MAX_URL`, `_MAX_PREVIEW` entfernt)
- Neues Log-Schema: `body_json` / `body_text` / `binary` statt `body_preview`
- `truncated` ist immer `false` — nie mehr Kürzungshinweis im Dashboard
- Neuer Helper `log_http_response(service, method, response, duration_ms, saved_to)`:
  nimmt `requests.Response`-Objekt, entscheidet automatisch JSON/Text/Binär
- Binäre Antworten (KMZ, TIFF): Content-Length, SHA-256, `saved_to` werden geloggt
- Alle Call-Sites auf `log_http_response` umgestellt

#### A8 — Dashboard auf letzten Request/Response reduziert ✅
**Datei:** `frontend/src/pages/Dashboard.jsx`

**Umgesetzt:**
- 24h-Statistiktabelle aus Dashboard entfernt (gehört auf `/logs`)
- Neues Panel „Letzter API-Request / Response" mit Service-Dropdown
- `RequestBlock`-Komponente: zeigt URL und Payload sauber
- `ResponseBlock`-Komponente: rendert `body_json` formatiert, `body_text` direkt,
  `binary`-Antworten als Metadaten-Box (SHA-256, Dateigröße, Pfad)
- Kein doppeltes JSON-Escaping mehr
- `hours`-Validierung in `/api/api_calls/last` (HTTP 400 statt 500 bei ungültigem Wert)

#### A9 — Forecast-Horizonte zur Laufzeit aus runtime_config ✅
**Datei:** `prediction.py`

**Umgesetzt:**
- Neue interne Funktion `_get_horizons()` liest aus `runtime_config`
- Fallback auf `ML_FORECAST_HORIZONS_MIN` aus `config.py`
- Alle internen Verwendungen von `ML_FORECAST_HORIZONS_MIN` in `predict_positions()`
  durch `_get_horizons()` ersetzt

#### A10 — INTENSITY_BANDS aus Admin-Konfiguration ✅
**Dateien:** `object_tracking.py`, `config.py`, `app.py`

**Umgesetzt:**
- `INTENSITY_BANDS_DEFAULT` in `config.py` als JSON-serialisierbares Default
- `object_tracking.py` liest Bänder zur Laufzeit via `_rc.get("INTENSITY_BANDS", ...)`
- Neue API-Endpunkte: `GET /api/intensity_bands`, `POST /api/intensity_bands`
- Änderungen wirken sofort im nächsten Tracking-Zyklus


#### A11 — GeoSphere CAPE + 700hPa Wind: vollständiges Response-Logging ✅
**Dateien:** `assign_cape_from_forecast.py`, `fetch_700hpa_wind_per_object_slim.py`

**Umgesetzt:**
- `assign_cape_from_forecast.py`: `log_api_call` ohne Body → `log_http_response` mit Timing
- `fetch_700hpa_wind_per_object_slim.py`: Bulk-Request und Einzelabfrage beide mit `log_http_response`
- GeoJSON-Response (CAPE) und Open-Meteo JSON (700hPa Wind) jetzt vollständig im Dashboard sichtbar

#### A12 — Forecast-Horizonte End-to-End + Konsistenz-Assert ✅
**Dateien:** `app.py`, `MapView.jsx`, `model_training.py`

**Umgesetzt:**
- `/api/system_consistency`: prüft Admin-Horizonte vs. Modell-Meta, fehlende Modell-Dateien, DEM-Tiles
- `training_meta.json` speichert jetzt Horizonte für Konsistenz-Prüfung
- `MapView.jsx`: Horizonte werden von `/api/horizons` geladen (kein statisches Array)

#### A13 — ML-Modus Nachweis im Admin ✅
**Dateien:** `app.py`, `frontend/src/pages/Dashboard.jsx`

**Umgesetzt:**
- `/api/forecast_stats`: aggregiert `forecast_mode` aus Objekt-JSONs der letzten N Stunden
- Dashboard-Card „Forecast-Modus": zeigt aktiven Modus (ML/Fallback) + 24h-Statistik
- Gelbe Border-Markierung wenn Fallback aktiv

#### A14 — DEM Healthcheck im Admin ✅
**Dateien:** `app.py`, `frontend/src/pages/Dashboard.jsx`

**Umgesetzt:**
- `/api/dem_status`: Kachel-Zähler, fehlende Tiles, Mosaic-Status, Training-Verwendung
- Dashboard-Card „DEM-Kacheln": Anzeige x/8 Kacheln + Status-Label

#### A15 — Cache-Status im Admin sichtbar ✅
**Dateien:** `app.py`, `frontend/src/pages/Logs.jsx`

**Umgesetzt:**
- `/api/cache_status`: FRESH/STALE/MISSING + letzter Abruf + nächster erlaubter Abruf je Namespace
- Logs-Seite: neue Tabelle „API-Cache Status"
- Erfüllt Zieldefinition: Fremdrequests minimieren + Aktualisierungsintervalle berücksichtigen


### 5.3 Definition of Done (für Referenz)

1. Code-Änderung steht im Repo (manuell committed nach Test)
2. Mindestens 1 Test-Aufruf zeigt dass es funktioniert
3. Falls UI-Änderung: visuell verifiziert
4. Falls Scheduler-Job: in einem Lauf erfolgreich ausgeführt
5. Keine bestehende Funktion bricht (smoke-test Live-Loop)

---

## 6. Phase B — Hailo + U-Net + Linux-Trainer ⏳ OFFEN

### 6.1 Voraussetzungen
- ✅ Phase A vollständig abgeschlossen
- ⏳ Linux-Rechner mit Ubuntu 22.04 + Docker beschaffen
- ⏳ Hailo Developer Zone Account anlegen (kostenlos)
- ⏳ Mindestens 4 Wochen Radar-Trainingsdaten auf Pi sammeln (~50 000 Frames)

### 6.2 Schritte

| # | Schritt | Wo | Dauer | Status |
|---|---------|-----|-------|--------|
| B1 | Linux-Rechner aufsetzen (Ubuntu 22.04, Docker, Hailo DFC) | Linux-PC | 1 Tag | ⏳ |
| B2 | Repo auf Linux-Rechner klonen, venv, requirements | Linux-PC | 2 h | ⏳ |
| B3 | `LOCAL_TRAINING=False` auf Pi setzen via `--no-training` | Pi | 5 min | ⏳ |
| B4 | `wetterprojekt.service` auf Linux NICHT aktivieren (kein Live-Loop) | Linux | manuell | ⏳ |
| B5 | `hailo_inference.py` produktionsreif einspielen (Code §11) | Pi | 30 min | ⏳ |
| B6 | `tools/sync_*.sh` Skripte einrichten (Datenfluss Pi ↔ Linux) | Pi + Linux | 1 Tag | ⏳ |
| B7 | Sync-cron auf beiden Rechnern einrichten | Pi + Linux | 1 h | ⏳ |
| B8 | U-Net-Architektur in `unet_nowcast.py` implementieren | Linux | 2 Tage | ⏳ |
| B9 | Erstes U-Net-Training auf Linux | Linux | 1–2 Tage | ⏳ |
| B10 | ONNX-Export (`tools/hailo/export_onnx.py`) | Linux | 1 h | ⏳ |
| B11 | DFC-Build (HEF) auf Linux mit Docker (`tools/hailo/compile.py`) | Linux | 1 Tag | ⏳ |
| B12 | HEF + Meta-JSON zum Pi syncen (automatisch via Sync-Skript) | automatisch | 5 min | ⏳ |
| B13 | Test-Inferenz auf Pi mit echtem Hailo (`hailo_inference.py`) | Pi | 1 Tag | ⏳ |
| B14 | U-Net in `prediction.py` ergänzend integrieren | Pi | 1 Woche | ⏳ |
| B15 | Closed-Loop-Verifikation U-Net vs. LSTM/LGBM | Pi | 2 Wochen | ⏳ |

### 6.3 Rollen des Linux-Rechners (beide gleichwertig)

**Rolle 1 — Modell-Training:**
- LSTM, LightGBM, ConvLSTM, U-Net trainieren
- `scheduler.py` mit `LOCAL_TRAINING=True` läuft auf Linux
- `dataset_builder.py` rebuild auf Linux
- Pi sendet Trainingsdaten per rsync, Linux sendet Modelle zurück

**Rolle 2 — Hailo DFC-Build (zwingend x86-Linux):**
- Hailo Dataflow Compiler (DFC) läuft **nur auf x86-Linux** — nicht auf ARM/Pi
- Keras → ONNX Export
- INT8-Quantization mit Calibration-Daten (200–500 reale Radar-Patches)
- HEF-Erzeugung via Docker-Container
- HEF per rsync zum Pi, Pi lädt via `/api/hailo/reload` neu

### 6.4 Datenfluss (Phase B aktiv)

```
┌────────────────────────────┐         ┌─────────────────────────────┐
│   Raspberry Pi 5 (Edge)    │         │  Linux-PC (Trainer + DFC)   │
│   LOCAL_TRAINING = False   │         │  LOCAL_TRAINING = True      │
├────────────────────────────┤         ├─────────────────────────────┤
│                            │         │                             │
│ ● Live-Loop (main.py)      │         │ ● scheduler.py (Training)   │
│ ● HSV + Tracking           │         │ ● dataset_builder.py        │
│ ● Externe APIs             │         │ ● model_training.py         │
│ ● Hailo-Inferenz (HEF)     │         │ ● ConvLSTM-Training         │
│ ● Forecast + KMZ           │         │ ● U-Net-Training            │
│ ● Admin-Panel              │         │ ● ONNX-Export               │
│ ● Datensammlung            │         │ ● DFC Build (Docker→HEF)    │
│ ● accuracy_eval            │         │ ● Kein main.py / kein       │
│ ● data_cleanup             │         │   wetterprojekt.service     │
│                            │         │                             │
│  train_data/ ──►rsync──►   │         │  train_data/                │
│  (alle 30 min)             │         │                             │
│                            │         │                             │
│  models/current/ ◄─rsync◄  │         │  models/current/            │
│  models/hailo/   ◄─rsync◄  │         │  models/hailo/ + onnx/      │
│  (nach jedem Training/DFC) │         │                             │
└────────────────────────────┘         └─────────────────────────────┘
```

### 6.5 Sync-Skripte

**Auf Pi: `tools/sync_train_data_to_trainer.sh`** (cron alle 30 min)
```bash
#!/usr/bin/env bash
set -euo pipefail
TRAINER_HOST="${TRAINER_HOST:?Bitte TRAINER_HOST in .env setzen}"
TRAINER_USER="${TRAINER_USER:-horst}"
TRAINER_PATH="${TRAINER_PATH:-/home/horst/wetterprojekt}"

rsync -avz --partial \
  --include="*.json" --include="*.png" --include="*.geojson" \
  --include="*.tif" --include="*/" --exclude="*" \
  /home/ki-pi/wetterprojekt/train_data/ \
  "${TRAINER_USER}@${TRAINER_HOST}:${TRAINER_PATH}/train_data/"
```

**Auf Linux-Trainer: `tools/sync_models_to_pi.sh`** (nach jedem Training)
```bash
#!/usr/bin/env bash
set -euo pipefail
PI_HOST="${PI_HOST:?Bitte PI_HOST in .env setzen}"
PI_USER="${PI_USER:-ki-pi}"
PI_PATH="${PI_PATH:-/home/ki-pi/wetterprojekt}"

rsync -avz --delete \
  /home/horst/wetterprojekt/train_data/models/current/ \
  "${PI_USER}@${PI_HOST}:${PI_PATH}/train_data/models/current/"

rsync -avz --delete \
  --include="*.hef" --include="*.meta.json" --exclude="*" \
  /home/horst/wetterprojekt/models/hailo/ \
  "${PI_USER}@${PI_HOST}:${PI_PATH}/models/hailo/"

ssh "${PI_USER}@${PI_HOST}" \
  "curl -s -u admin:\$(cat ${PI_PATH}/.admin_password) -X POST http://localhost:5000/api/hailo/reload"
```

### 6.6 SSH-Key-Setup (Phase B Anfang)
- SSH-Key zwischen Pi und Linux einrichten (passwortlos für rsync)
- `TRAINER_HOST`/`PI_HOST` in jeweiliger `.env` setzen
- Test: `ssh horst@<linux-ip>` ohne Passwort

---

## B52 – Size-Regresser (Phase A: vollständig implementiert, Phase B: U-Net-Extension)

**Status:** ✅ Implementiert (Phase A – LightGBM + geometrischer Fallback)
**Datum:** 2026-06-02
**Datei:** `size_regressor.py` (neu), `main.py` (ergänzt), `scheduler.py` (ergänzt), `app.py` (ergänzt)

### Übersicht

| Komponente | Phase A | Phase B |
|---|---|---|
| `geometric_size()` | Pixel→km, immer verfügbar | bleibt als Plausibilitätsprüfung |
| `SizeRegressor.predict()` | LightGBM (wenn trainiert), sonst geometric | **U-Net Output-Kanal** |
| `record_size_label()` | JSONL-Sink für Training | weiter Trainingsdaten für U-Net-Finetuning |
| `maybe_trigger_training()` | AUTO bei ≥50 Samples | Hailo-DFC Recompile statt Training |
| `/api/size_regressor_status` | Status + MAE | Status + Hailo-Inference-Latenz |

### Trainings-Parameter (LightGBM, Phase A)
- Min-Samples: 50, Retrain alle 200 neuen Samples
- Features: area_px, radius_px, aspect_ratio, CAPE, Wind, Temp, Wolkenhöhe, lat/lon, Tageszeit-Zyklus, DOY-Zyklus
- Targets: area_km2 (MAE in km²), radius_km (MAE in km)
- Plausibilitätsprüfung: Modell darf max. 10× vom geometrischen Fallback abweichen

### Felder in jedem Objekt-Dict (ab B52)
`area_km2`, `radius_km`, `aspect_ratio`, `size_source` (`"geometric"` oder `"lgbm"` oder Phase B: `"unet"`)

### Phase B – Umstellungsplan
1. U-Net Output-Kanal für Zellgröße beim DFC-Kompilieren definieren
2. `SizeRegressor.predict()` durch Hailo-Inference ersetzen (gleiche Signatur)
3. `source = "unet"` im Rückgabe-Dict setzen
4. `maybe_trigger_training()` → triggert Hailo-DFC-Recompile statt LightGBM-Training

### Training-Dateien
- Labels: `train_data/size_labels/size_labels.jsonl`
- Modell: `models/size_regressor.pkl`
- Meta: `models/size_regressor_meta.json`

### Log-Tags
- `[SIZE-REG]` — alle Size-Regresser Meldungen

---

## B60 – Anti-Self-Distillation im Size-Regresser

**Status:** ✅ Implementiert  
**Datum:** 2026-06-03  
**Datei:** `main.py`  
**Quelle:** Codex P2-Finding (commit `bfccb0004f`)

### Root Cause
`record_size_label(obj, timestamp)` wurde NACH `obj.update(_size)` aufgerufen.
Sobald ein LGBM-Modell geladen ist, enthält `obj["area_km2"]`/`obj["radius_km"]` zu diesem
Zeitpunkt LGBM-Vorhersagewerte. Diese wurden als Trainingsziele in `size_labels.jsonl`
geschrieben → zirkuläres Feedback → Self-Distillation → systematische Verzerrung bei
jedem weiteren Retraining-Zyklus.

### Fix
Geometrisches Label (Pixel → km via `geometric_size()`) wird berechnet und gespeichert
**bevor** `predict()` die Objekt-Felder überschreibt. Training-Dataset enthält ausschließlich
unabhängige geometrische Messungen — auch nach erstem LGBM-Training wächst das Dataset korrekt.

```python
# B60-Reihenfolge in main.py:
_geo_label = dict(obj)
_geo_label.update(geometric_size(..., _km_px_x, _km_px_y))
record_size_label(_geo_label, timestamp)   # ← geometrisch, vor LGBM
_size = _sr.predict(...)
obj.update(_size)                          # ← LGBM erst danach
```

---

## B61 – Ausblick-Seite: CircleMarker-Layer durch Rectangle-Raster ersetzt

**Status:** ✅ Implementiert  
**Datum:** 2026-06-03  
**Datei:** `frontend/src/pages/Ausblick.jsx`  
**Quelle:** Nutzer-Feedback (Kreise statt Raster sichtbar)

### Root Cause
`Ausblick.jsx` renderte zwei überlagerte Layer mit identischen Daten (beide lesen
`outlook_12h.json`):

1. `current?.cells → Rectangle` (0.05°×0.05°, korrekt wie auf `/map`)
2. `outlookRiskGrid?.grid → CircleMarker` (variabler Radius — sichtbare Kreise)

Der `CircleMarker`-Layer lag optisch über den Rechtecken. Zusätzlich wurden Daten
redundant von zwei Endpunkten geladen (`/api/outlook` + `/api/outlook_risk_grid`).

### Fix
`outlookRiskGrid`-State, `/api/outlook_risk_grid`-Fetch und CircleMarker-Renderblock
vollständig entfernt. Legende-Unterabschnitt „12h-Outlook Risiko" mit Kreissymbolen
entfernt. `CircleMarker` aus React-Leaflet-Import entfernt.  
Ergebnis: identisches Rectangle-Raster wie auf der Hauptkarte (`/map`).  
Benutzerhandbuch: „farbige Kreise" → „Rasterflächen (~5×5 km)" aktualisiert.

---

## B62 – Ausblick: Wind-Only Falschalarm unterbunden

**Status:** ✅ Implementiert
**Datum:** 2026-06-04
**Datei:** `convective_outlook.py`
**Quelle:** Screenshot-Analyse (CAPE 0 · LI +4.5 → Risiko Mäßig durch Böen 77 km/h)

### Root Cause
In `_cell_severity()` konnte `gust_pred >= 70` den risk=2-Zweig auslösen ohne jede
Konvektionsinstabilität. `rain` und `hail_index` sind implizit durch CAPE > 0 abgesichert,
`gust_pred` hatte keine solche Voraussetzung. Nicht-konvektive Böen (Föhn, Kaltfront ohne
Gewitter) erzeugten daher Mäßig-Risikofelder im konvektiven 12h-Ausblick.

### Fix
`gust_pred >= 70` als risk=2-Trigger nur noch aktiv wenn `inst >= 0.05`
(≈ CAPE > 100 J/kg oder LI < -0.3). Einzige geänderte Zeile:
```python
# vorher:
elif base >= 0.35 or hail_index >= 0.8 or rain >= 18 or gust_pred >= 70:
# nachher (B62):
elif base >= 0.35 or hail_index >= 0.8 or rain >= 18 or (gust_pred >= 70 and inst >= 0.05):
```
Konvektive Szenarien (CAPE > 0, negative LI) werden nicht beeinträchtigt.

### B63–B71 – Codex-Review-Nachträge

| # | Datei | Bug | Status |
|---|-------|-----|--------|
| B63 | `main.py` | `_count_lightning_near()` zählte Blitze in einer lat/lon-Box (~20×20 km) statt im 10-km-Kreis → `lightning_count_10km` überhöht, verfälscht `hail_prob`/`lightning_jump`. Fix: Box als Vorfilter + exakte Haversine-Distanzprüfung ≤ radius_km. (Codex PR #22, vom Review-File übersehen.) | ✅ erledigt |
| B64 | `frontend/src/pages/AiSuggestions.jsx` | Bild-Upload akzeptierte `image/*` (inkl. SVG/HEIC/BMP/TIFF) → Claude-API lehnt diese ab, KI-Request scheitert ohne erkennbaren Grund. Fix: Whitelist JPEG/PNG/GIF/WebP in `addImages()` + `accept`-Attribut; abgelehnte Dateien werden gemeldet. (Codex PR #134, vom Review-File übersehen.) | ✅ erledigt |
| B65 | `dem_feature.py` | `_height()` klemmte Out-of-bounds-Raster-Indizes auf Randwert → falsche DEM-Werte nahe BBOX-Rand. Fix: Return None statt clamp. (Codex PR #22, Phase C, mit B10 bündeln.) | ✅ erledigt |
| B66 | `object_tracking.py` | Runtime-BBOX ohne Typ/Wertebereichsprüfung an `crop_and_upscale_to_bbox()` → fehlerhafter Admin-Eintrag = Absturz. Fix: `_validate_bbox()` Hilfsfunktion, Fallback auf config.py-Default. (Codex PR #256.) | ✅ erledigt |
| B67 | `email_notifier.py` | `send_ai_report_email()` rief `result.get()` ohne isinstance-Guard auf — `run_analysis()` kann None liefern → AttributeError. Fix: Guard vor erstem `.get()`-Zugriff. (Codex PR #182.) | ✅ erledigt |
| B68 | `app.py` | Cache-Status-Panel zeigte EUMETView-Capabilities-Cache als UNKNOWN — `_DEFAULT_TTLS` fehlte der korrekte Namespace-Key `eumetview:capabilities`. Fix: Key ergänzt. (Codex PR #278.) | ✅ erledigt |
| B69 | `watchdog_heartbeat.py` | Ping-Intervall hartkodiert 25 s — bei WatchdogSec < 50 s würde systemd Service neu starten. Fix: `_derive_interval()` aus `WATCHDOG_USEC` ableiten (max. 25 s). (Codex PR #294.) | ✅ erledigt |
| B70 | `frontend/src/pages/Logs.jsx` | Nach Log-Clear wurde `loadHealth()` nur bei aktivem `api_fehler`-Tab aufgerufen. Fix: Bedingungslos aufrufen. (Codex PR #209.) | ✅ erledigt |
| B71 | `frontend/src/pages/MapView.jsx` | IR-Layer-Legende „CB > 10.000" implizierte Anzeigefilter statt Detektionsschwelle. Fix: Label → „CB / IR-Vorläufer", Tooltip präzisiert. (Codex PR #375.) | ✅ erledigt |
| B72 | `fetch_openmeteo_extended.py` | LPI-Request an `/v1/dwd-icon` verwendete `lightning_potential_index` statt korrektem `lightning_potential` — Kommentar nannte außerdem fälschlich `icon_eu`. Folge: HTTP 400 / `lpi` immer 0.0. Fix nach Verifikation mit curl: Parameter, Kommentare und Parser auf `lightning_potential`. (Codex PR #462.) | ✅ erledigt |
| B73 | `ir_cell_detection.py` | `cells.append()` rief `round(cape_val, 1)` und `round(li_val, 2)` auf ohne None-Guard — `_lookup_atm()` gibt `(None, None)` wenn `atmosphere_latest.json` noch nicht existiert (immer nach Neustart, erster Zyklus). Folge: IR-Detection crasht komplett, 0 IR-Cells gespeichert. Fix: `round(x, n) if x is not None else 0.0` für cape_val und li_val. | ✅ erledigt |
| B74 | `ir_cell_detection.py` | Verworfene Cluster im Log immer als „Cluster 0" angezeigt — `cell_idx` wird nur bei akzeptierten Clustern inkrementiert. Fix: `label_num/n_labels` statt `cell_idx` in CAPE/LI-Filter-Log. (Kosmetisch, P3.) | ✅ erledigt |
| B75 | `app.py` | `_DEFAULT_TTLS` im Cache-Status-Panel hatte falsche/veraltete Namespace-Keys — `geosphere_tawes`→`geosphere_tawes_all`, `blitzortung`→`blitzortung_last_strikes`; `openmeteo_extended` durch 4 Sub-Namespaces ersetzt; 7 tote Keys entfernt (kein cache_key()-Aufruf im Code); Ghost-Entry `eumetview:capabilities` aus B68-Rückstand entfernt. Panel zeigt jetzt TAWES/Blitz mit korrekter TTL. (Vollständig-Audit aller cache_key()-Aufrufe.) | ✅ erledigt |

### 5.10 Phase A.10 — Bug-Fix-Welle 10

| # | Task | Datei(en) | Status |
|---|------|-----------|--------|
| B76 | GeoSphere Nowcast HTTP 400: `start`/`end`-Parameter im Format `YYYY-MM-DDThh:mm:ss+00:00` wurden von der API abgelehnt. GeoSphere Forecast-API erwartet `YYYY-MM-DDThh:mm` (keine Sekunden, kein Z-Suffix). Fix: Format-Strings von `%Y-%m-%dT%H:%M:00Z` auf `%Y-%m-%dT%H:%M` geändert. | `fetch_geosphere_nowcast.py`, `api_health_check.py` | ✅ erledigt |
| B77 | `_DEFAULT_TTLS` im Cache-Status-Panel fehlten Einträge für `openmeteo_icon_global` (3600 s) und `openmeteo_synoptic_500` (3600 s). Panel zeigte `—` statt korrekter TTL. Folge aus unvollständigem B75-Audit. | `app.py` | ✅ erledigt |

### 5.11 Phase A.11 — Bug-Fix-Welle 11

| # | Task | Datei(en) | Status |
|---|------|-----------|--------|
| B84 | `whatsapp_notifier.py`: `send_test_wa()` delegierte an `_send_whatsapp()` welche nur `True`/`False` zurückgibt. CallMeBot-Fehlertexte (z.B. „Not Registered", „API Key not Valid") aus dem HTTP-Response-Body gingen verloren — Benutzer sah nur `failed=['+43...']` ohne Grund. Fix: HTTP-Call in `send_test_wa` inline mit gezieltem `urllib.error.HTTPError`-Catch; Response-Body im `error`-Feld zurückgegeben. `app.py`: `log_api_call` um `error`-Feld ergänzt → Dashboard zeigt jetzt tatsächlichen CallMeBot-Text. | `whatsapp_notifier.py`, `app.py` | ✅ erledigt |
| B78 | `locations_check.py` + `app.py`: Zellgeschwindigkeit 3× zu hoch — `UPSCALE_FACTOR` fehlte bei `speed_kmh`-Berechnung aus `vx`/`vy`. Beweis: Screenshot zeigt 64.4 km/h im Orts-Treffer vs. 21.5 km/h im Zellen-Popup (Faktor 3.0 = UPSCALE_FACTOR exakt). Fix: `obj.get("speed_kmh")` verwenden (bereits korrekt berechnet von `object_tracking.py`). Betroffen: Orts-Treffer-Anzeige, `is_slow_arrow`, Risk-Grid-Stationär-Boost. | `locations_check.py`, `app.py` | ✅ erledigt |
| B79 | `MapView.jsx` + `MapFullscreen.jsx`: Grammatikfehler „1 Frames" im Zellen-Popup bei `active_frames === 1`. Fix: Ternary für Singular/Plural. | `frontend/src/pages/MapView.jsx`, `frontend/src/pages/MapFullscreen.jsx` | ✅ erledigt |

### 5.13 Phase A.13 — Bug-Fix-Welle 13

| # | Task | Datei(en) | Status |
|---|------|-----------|--------|
| B91 | Popup zeigte alle treffenden Forecast-Horizonte statt nur den frühesten. Alarm wurde bei jedem Orts-Treffer gesendet unabhängig vom Eintreffzeitpunkt. Fix: (1) Frontend (`MapView.jsx`, `MapFullscreen.jsx`): nur frühester Horizont-Eintrag im Popup, Anzahl weiterer in grau. (2) Backend (`main.py`): Vorwarnzeit-Guard vor `_ready_to_warn.add()` — Alarm nur wenn frühester Horizont ≤ `WARN_MAX_HORIZON_MIN`. (3) `config.py`: neuer Default `WARN_MAX_HORIZON_MIN = 20`. (4) Admin-Panel (`Horizons.jsx`): neues Eingabefeld "Vorwarnzeit" (5–60 min, Schritt 5), persistiert via `runtime_overrides.json`. | `main.py`, `config.py`, `MapView.jsx`, `MapFullscreen.jsx`, `Horizons.jsx` | ✅ erledigt |

### 5.12 Phase A.12 — Bug-Fix-Welle 12

| # | Task | Datei(en) | Status |
|---|------|-----------|--------|
| B81 | `whatsapp_notifier.py` + `main.py`: Stille WhatsApp-Fehlschläge — kein Log wenn Empfänger-String leer, keine Empfänger geparsed, oder WhatsApp-Feld im Ort fehlt. Fix: `debug_log` an allen 3 Stellen ergänzt. Diagnose: `[WA] Kein WhatsApp-Eintrag für {Ort}` / `[WA] keine gültigen Empfänger` / `[WA] Warnung NICHT gesendet`. | `whatsapp_notifier.py`, `main.py` | ✅ erledigt |
| B82 | `main.py` + `whatsapp_notifier.py`: Risk-Alert Cooldown von 1× täglich auf 1× 2 Stunden geändert. `_RISK_ALERT_LOG` speichert jetzt Epoch-Timestamp statt Datumsstring. Rückwärtskompatibel (alte Datumsstrings → Cooldown abgelaufen → Alarm erlaubt). | `main.py`, `whatsapp_notifier.py` | ✅ erledigt |
| B83 | `MapView.jsx` + `MapFullscreen.jsx`: Risikozonen-Popup zeigte LI doppelt (in `atm`-dominantLabel UND als Detail-Zeile). Zusätzlich fehlten Regen/Böe/Hagel im Popup. Fix: LI aus `dominantLabel` entfernt; Severity-Proxy (Regen/Böe/Hagel) aus bereits vorhandenen `info`-Feldern (cape, pw, ship, lapse_700_500) direkt im Frontend berechnet und angezeigt — identisch zur Formel in `convective_outlook.py`. | `frontend/src/pages/MapView.jsx`, `frontend/src/pages/MapFullscreen.jsx` | ✅ erledigt |

### 5.13 Phase A.13 — Bug-Fix-Welle 13 (Log-Analyse 2026-06-08)

**Analysiertes Log:** `wetterprojekt_logs_20260608_093303.txt`  
**objects-JSON:** `objects_20260608_093259.json` → leer `[]` (kein Gewitter, Normalbetrieb)

**Bestätigter Normalbetrieb (kein Fix):**
- `rebuild_dataset samples=0` → erwartet (keine Gewitterzellen = keine Trainingssequenzen)
- `openmeteo_*/AROME/SYNOPTIC` STALE/kein API-Call → erwartet (objektabhängig, keine Zellen)
- `geosphere_nowcast MISSING` → erwartet (objektabhängig, keine Zellen aktiv)
- `[LOOP] langer Intervall (900s)` → korrektes Verhalten (>120 min Ruhe)
- `[RISK-ALERT] Connection refused` → bekanntes Race-Condition-Fenster beim Service-Neustart, P2, deferred

| # | Task | Datei(en) | Status |
|---|------|-----------|--------|
| B84 | `Progress.jsx`: Leere Charts ohne Empty-State-Erklärung — wenn keine Modell-Versionen vorhanden (`versions = []`), wurden drei leere Recharts-Diagramme und eine leere Tabelle angezeigt ohne jede Erklärung. Nutzer konnte nicht unterscheiden ob Fehler oder normaler Datenmangel. Fix: `loaded`-State ergänzt; Amber-Banner wenn `loaded && versions.length === 0`; Charts und Tabelle nur bei `versions.length > 0`. | `frontend/src/pages/Progress.jsx` | ✅ erledigt |
| B85 | `email_notifier.py` + `drift_detector.py`: Drift-Alert-Email ohne Cooldown — `send_drift_alert()` hatte keinen Cooldown (anders als `send_warning_email` mit 15 min). Im Fallback-Modus (keine ML-Modelle, MAE systemisch erhöht) wurde stündlich ein Drift-Alarm versendet. Fix (1): 6h dateibasierter Cooldown in `send_drift_alert()` via `_DRIFT_COOLDOWN_FILE` (`train_data/evaluation/drift_mail_cooldown.json`). Fix (2): `_has_ml_model()`-Guard in `check_and_alert()` — kein E-Mail-Alarm wenn `train_data/models/current/` und `v_*`-Verzeichnisse fehlen (kinematischer Fallback-Modus). | `email_notifier.py`, `drift_detector.py` | ✅ erledigt |
| B86 | `app.py`: Risk-Grid Tooltip zeigte CAPE, SHIP, cloud_height_m als `null` bei `dominant='atm'` (keine aktiven Sturmzellen). Ursache: `best_cape`, `best_ship`, `best_cloud_top_m` wurden nur aus Zell-Objekten befüllt, nie aus dem ATM-Snapshot. Fix: Im ATM-Instabilitäts-Loop (Abschnitt 3) werden jetzt `best_cape`, `best_ship` (Proxy: cape×lapse/14000) und `best_cloud_top_m` aus `aloc`-Feldern des Atmosphären-Snapshots übertragen. | `app.py` | ✅ erledigt |
| B91 | `main.py` + Admin/Popup: Vorwarnzeit für Orts-Alarme ist über `WARN_MAX_HORIZON_MIN` konfigurierbar (Default 20 min). E-Mail/WhatsApp werden nur ausgelöst, wenn Horizon 0 aktuell getroffen ist oder der früheste Forecast-Horizont innerhalb der Schwelle liegt. Orts-Popups zeigen nur noch den frühesten Forecast-Horizont und fassen weitere Treffer grau zusammen. | `config.py`, `main.py`, `frontend/src/pages/Horizons.jsx`, `frontend/src/pages/Configuration.jsx`, `frontend/src/pages/MapView.jsx`, `frontend/src/pages/MapFullscreen.jsx` | ✅ erledigt |
| B92 | `fetch_geosphere_nowcast.py`: GeoSphere Nowcast fragte den laufenden 15-min-Slot ab (`floor` bis `floor+15`) und erhielt dadurch HTTP 400, solange der Slot noch nicht abgeschlossen war. Fix: immer den letzten abgeschlossenen Slot (`floor-15` bis `floor`) abfragen; zusätzlicher Fallback auf den davorliegenden abgeschlossenen Slot. | `fetch_geosphere_nowcast.py` | ✅ erledigt |
| B93 | `fetch_geosphere_nowcast.py`: Nowcast wurde pro Zelle einzeln abgefragt. Fix: ein Bulk-Request mit repeated `lat_lon`-Parametern für alle gültigen Zellen; die Feature-Reihenfolge wird auf die Eingabekoordinaten gemappt, bei unvollständiger Bulk-Antwort greift ein Einzelabfrage-Fallback. | `fetch_geosphere_nowcast.py` | ✅ erledigt |

### 5.14 Phase A.14 — Bug-Fix-Welle 14

| # | Task | Datei(en) | Status |
|---|------|-----------|--------|
| B89 | `severity_dataset._gust_kmh()`: `arome_ff10m` wurde fälschlich als Böen-Fallback genutzt, obwohl es die mittlere 10-m-Windgeschwindigkeit aus AROME und kein Böenwert ist. Fix: Kandidatenliste auf echte Böenquellen begrenzt (`nowcast_ffx_kmh`, `FFX`, `wind_gust_10m_kmh`). Dadurch verwenden Fallback-Ausgabe und zukünftige Severity-Trainingssamples keine überhöhten Böen-Targets aus mittlerem Hintergrundwind mehr. | `severity_dataset.py`, `tests/test_severity_dataset_b89.py` | ✅ erledigt |


## B76 — GeoSphere Nowcast HTTP 400: Timestamp-Format-Fehler

**Status:** ✅ Implementiert  
**Datum:** 2026-06-07  
**Dateien:** `fetch_geosphere_nowcast.py`, `api_health_check.py`  
**Schwere:** P1 (stille Falschdaten — Nowcast-Werte fehlen wenn Gewitterzellen aktiv)

### Root Cause
Die GeoSphere Dataset API (Forecast-Modus) erwartet `start`/`end`-Parameter im
Format `YYYY-MM-DDThh:mm` (keine Sekunden, kein Z-Suffix).
Der Code sendete `%Y-%m-%dT%H:%M:00Z` = z.B. `2026-06-06T19:00:00Z`.
Folge: HTTP 400 "Bad Request" für jeden Nowcast-Call wenn Gewitterzellen aktiv.

### Symptome
- API-Fehler-Panel: `geosphere_nowcast` HTTP 400 bei 17:50–19:14 UTC am 2026-06-06
  (Zellen aktiv), `GeoSphere-Health` HTTP 400 um 03:15 UTC am 2026-06-07
- Cache-Status: `geosphere_nowcast` Status = MISSING (nie ein erfolgreicher Call)
- Nowcast-Felder (rr, ff, ffx, gust_warning, heavy_rain_warning) immer Defaultwert

### Fix
Format-Strings in `_nowcast_slots` (2 Stellen) und `api_health_check._check_geosphere()`
(2 Stellen):

```
# Vorher (falsch):
_floor.strftime("%Y-%m-%dT%H:%M:00Z")  # → "2026-06-06T19:00:00Z"

# Nachher (korrekt):
_floor.strftime("%Y-%m-%dT%H:%M")       # → "2026-06-06T19:00"
```

Quelle: https://dataset.api.hub.geosphere.at/v1/docs/user-guide/mode.html

## B65 – DEM: Out-of-Bounds-Koordinaten zurückweisen statt klemmen

**Status:** ✅ Implementiert
**Datum:** 2026-06-04
**Datei:** `dem_feature.py`
**Quelle:** Codex-Inline-Review PR #22 (P1)

### Root Cause
`_height()` klemmte Raster-Indizes mit `max()`/`min()` auf den gültigen Bereich.
Koordinaten außerhalb des DEM-Mosaiks lieferten dadurch den nächstgelegenen
Rasterrandwert statt `None`. Randnahe Samples konnten so `dem_elevation_m`,
`dem_slope_toward_cell` und `dem_barrier_ahead` verfälschen.

### Fix
`_height()` prüft berechnete Raster-Indizes jetzt explizit auf Out-of-bounds
und gibt in diesem Fall `None` zurück. Gültige Indizes werden unverändert aus
dem Mosaic gelesen; NaN-Werte bleiben weiterhin `None`.

## 7. U-Net-Architektur (Phase B)

### 7.1 Zweck
Vorhersage des Radarbilds bei T+10/+20/+30/+45/+60 min aus den letzten
4 Radar-Frames. Statt nur Zellzentren zu projizieren wird das gesamte
Niederschlagsfeld extrapoliert — inklusive Neuentstehung, Auflösung,
Verformung.

### 7.2 Input/Output

| Aspekt | Wert |
|--------|------|
| Input-Shape | (1, 256, 256, 4) — 4 Frames, Single-Channel dBZ-Proxy |
| Output-Shape | (1, 256, 256, 5) — 5 Horizonte als separate Kanäle |
| Sliding-Window | 256×256 Patches mit 128 px Overlap über 1600×600 Radar |
| Tiles pro Frame | ~30 Tiles (6×5 mit Overlap) |
| Inferenz pro Tile auf Hailo | ~80 ms |
| Gesamt-Inferenz pro Frame | ~2,4 s — passt in 120 s Loop |

### 7.3 Architektur

| Aspekt | Wert |
|--------|------|
| Encoder | 4 Downsampling-Blöcke (Conv-Conv-Pool) |
| Bottleneck | 256 Filter |
| Decoder | 4 Upsampling-Blöcke mit Skip-Connections |
| Parameter | ~2 Mio |
| Training auf Pi 5 CPU | nicht praktikabel (~20 h/Epoche) |
| Training auf Linux mit CPU (z. B. i5-12400) | ~3 h/Epoche |
| Training auf Linux mit GPU | ~10 min/Epoche |
| HEF-Größe nach INT8-Quantization | ~5 MB |

### 7.4 DFC-Kompatibilität
Verwendet ausschließlich Conv2D, MaxPool, UpSampling2D, Concatenate, ReLU,
Sigmoid — alle DFC-getestet. Keine BatchNorm im Critical-Path. ONNX-Opset 11.

### 7.5 Integration in `prediction.py`
U-Net wird **ergänzend** zum bestehenden Forecast-System genutzt:
- LSTM/LGBM bleiben aktiv (Punkt-Vorhersage pro Zelle)
- U-Net liefert Bildfeld-Vorhersage
- Beide werden im Admin-Panel angezeigt
- Validierung beider Quellen per `accuracy_tracker.py`

Falls U-Net signifikant besser ist (Hit-Rate +20% oder mehr), wird es zum
Primärsystem und LSTM/LGBM zum Fallback.

---

## 8. Linux-Trainer-Rechner — Spezifikation

### 8.1 Anforderungen

| Komponente | Minimum | Empfohlen |
|-----------|---------|-----------|
| Architektur | x86_64 (kein ARM) | x86_64 |
| OS | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS |
| RAM | 16 GB | 32 GB |
| Speicher | 100 GB SSD frei | 500 GB SSD frei |
| CPU | 4 Kerne, ≥ 2,5 GHz | 8 Kerne, ≥ 3 GHz |
| GPU | nicht zwingend | NVIDIA mit ≥ 6 GB VRAM (Training 10× schneller) |
| Netzwerk | Gigabit-Ethernet | Gigabit-Ethernet |

### 8.2 Optionen (vom Aufwand her geordnet)

| Option | Kosten | Vorteile | Nachteile |
|--------|--------|----------|-----------|
| **WSL2 auf vorhandenem Windows-PC** | 0 € | Sofort verfügbar | Wenn PC aus, kein Training; rsync schwieriger |
| **Alter Laptop mit Ubuntu 22.04** | 0 € | Wenn vorhanden ideal | Langsamer, evtl. zu wenig RAM |
| **Mini-PC (Intel N100, 16 GB)** | 200–250 € | Klein, leise, 24/7-Betrieb | Kein GPU, langsam für U-Net |
| **Mini-PC mit dedizierter GPU** | 500–800 € | U-Net-Training schnell | Lauter, mehr Strom |
| **Refurbished Workstation (Intel Xeon)** | 300–600 € | Viel CPU-Leistung | Größer, lauter |
| **Cloud-VM (Hetzner CCX)** | ~30 €/Monat | Skalierbar | Datenfluss-Latenz, monatliche Kosten |
| **Mac mini / MacBook** | — | — | **NICHT möglich** — Hailo DFC läuft nur auf Linux-x86 |

### 8.3 Empfehlung
**Mini-PC mit Intel N100 (16 GB RAM)** als Einstieg. Reicht für:
- LSTM/LGBM/ConvLSTM-Training
- U-Net-Training auf CPU (3–6 h pro Epoche — akzeptabel)
- DFC-Build (Docker)
- 24/7-Betrieb möglich
- Geringer Stromverbrauch (~10 W)

Falls U-Net-Training zu langsam wird → später GPU dazu kaufen (PCIe x16
sollte verfügbar sein).

### 8.4 WSL2-Setup (falls Windows-PC verwendet wird)

```powershell
# In PowerShell als Admin:
wsl --install -d Ubuntu-22.04
# Nach Reboot Ubuntu-Setup
```

```bash
# In Ubuntu (WSL):
sudo apt-get update
sudo apt-get install -y docker.io
sudo usermod -aG docker $USER
# Neu in WSL einloggen
docker --version

# Hailo Developer Zone Account anlegen: https://hailo.ai/developer-zone/
# PAT erstellen, dann:
docker login quay.io -u <hailo-user> -p <hailo-pat>
docker pull quay.io/hailo-ai/hailo_ai_sw_suite:2024.10
```

---

## 9. HEF-Build-Pipeline (Phase B)

### 9.1 Workflow

```
Linux-Trainer:
  1. Modell trainieren (Keras/TensorFlow)
  2. Keras → ONNX exportieren
  3. Calibration-Daten vorbereiten (200–500 reale Radar-Patches)
  4. DFC-Docker starten: ONNX + Calib → HEF
  5. Meta-JSON erzeugen
  6. HEF + Meta in models/hailo/ ablegen
  7. rsync zum Pi (sync_models_to_pi.sh)
  8. Pi lädt HEF-Cache via /api/hailo/reload neu
```

### 9.2 `tools/hailo/compile.py` (auf Linux, im Docker)

```python
"""
Hailo DFC Compile-Script.
Läuft im Hailo-DFC-Docker-Container auf dem x86-Linux-Trainer.
Konvertiert: ONNX → HAR → HEF (INT8-Quantization).
"""
import argparse
import numpy as np
from hailo_sdk_client import ClientRunner


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--onnx",       required=True)
    parser.add_argument("--calib",      required=True, help="Pfad zur calib.npz")
    parser.add_argument("--output",     required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--hw-arch",    default="hailo8")
    args = parser.parse_args()

    runner = ClientRunner(hw_arch=args.hw_arch)

    # 1. ONNX → HAR
    runner.translate_onnx_model(
        args.onnx,
        args.model_name,
        start_node_names=["input_1"],
        end_node_names=None,
    )

    # 2. INT8-Quantization mit Calibration-Daten
    calib = np.load(args.calib)
    calib_data = calib["patches"].astype(np.float32)
    runner.optimize(calib_data)

    # 3. Compile → HEF
    runner.compile()
    runner.save_hef(args.output)
    print(f"[OK] HEF: {args.output}")


if __name__ == "__main__":
    main()
```

### 9.3 `tools/hailo/make_meta.py` (auf Linux)

```python
"""Erzeugt .meta.json-Datei neben dem HEF."""
import argparse, json
from datetime import datetime, timezone

SPECS = {
    "unet_nowcast": {
        "input_shape":  [1, 256, 256, 4],
        "input_name":   "input_1",
        "output_name":  "conv2d_24",
        "output_dtype": "float32",
        "classes":      ["t+10", "t+20", "t+30", "t+45", "t+60"],
    },
}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--version",    required=True)
    parser.add_argument("--hef",        required=True)
    parser.add_argument("--output",     required=True)
    parser.add_argument("--samples",    type=int,   default=0)
    parser.add_argument("--val-acc",    type=float, default=0.0)
    args = parser.parse_args()

    spec = SPECS[args.model_name]
    meta = {
        "model_name":          args.model_name,
        "version":             args.version,
        "compiled_at_utc":     datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_shape":         spec["input_shape"],
        "input_name":          spec["input_name"],
        "output_name":         spec["output_name"],
        "input_dtype":         "float32",
        "output_dtype":        spec["output_dtype"],
        "classes":             spec["classes"],
        "training_samples":    args.samples,
        "validation_accuracy": args.val_acc,
    }
    with open(args.output, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"[OK] Meta: {args.output}")

if __name__ == "__main__":
    main()
```

### 9.4 Build-Befehl

```bash
# Auf Linux-Trainer nach Training:
docker run --rm \
  -v ~/wetterprojekt/train_data:/work \
  -v ~/wetterprojekt/tools/hailo:/scripts \
  quay.io/hailo-ai/hailo_ai_sw_suite:2024.10 \
  python3 /scripts/compile.py \
    --onnx   /work/onnx/unet_nowcast.onnx \
    --calib  /work/calib/unet_nowcast_calib.npz \
    --output /work/../models/hailo/unet_nowcast.hef \
    --model-name unet_nowcast \
    --hw-arch hailo8
```

---

## 10. Phase C — Skalierung ⏳ OFFEN (nach Phase B)

### 10.1 Offene Bugs aus Phase A (verschoben auf Phase C)

| # | Datei | Bug | Status |
|---|-------|-----|--------|
| B10 | `dem_feature.py` | DEM-Kachel hardcoded — muss aus `SAVE_PATHS` + `runtime_config` kommen | Phase C |
| B11 | `cloud_height_from_eumetview.py` | `print` statt `debug_log`, kein `log_api_failure` | Phase C |
| B12 | Lightning-Config | `lightningmaps.org` ist inoffiziell — bessere Quelle suchen | Phase C |

### 10.2 Geplante Verbesserungen

- DEM-Kacheln für ganz Kärnten flexibel konfigurierbar
- Cloud-Höhe: vollständiges Fehler-Logging
- Lightning: offizielle Quelle (z. B. UBIMET, DWD-LINET) einbinden
- KI-Analyse vertiefen (Anthropic-API-Auswertung erweitern)
- Weitere Modelle falls U-Net nicht ausreicht
- Modell-Ensemble (Kombination LSTM/LGBM + U-Net)

---

## 11. Verzeichnis-Konventionen

### 11.1 Auf dem Pi

```
~/wetterprojekt/
├── *.py                            # Module im Root
├── config.py
├── runtime_config.py
├── runtime_overrides.json          # gitignored
├── install.sh
├── requirements.txt
├── .env                            # gitignored
├── .admin_password                 # gitignored (Modus 600)
├── frontend/
│   ├── src/
│   └── dist/                       # gitignored
├── tools/
│   ├── hailo/                      # Für Linux-Trainer (laufen dort)
│   │   ├── compile.py
│   │   └── make_meta.py
│   ├── sync_train_data_to_trainer.sh    # Pi: Daten zum Trainer
│   └── sync_models_to_pi.sh             # Linux: Modelle zum Pi
├── docs/
│   ├── HAILO_INTEGRATION.md
│   └── zieldefinition.txt
├── models/
│   └── hailo/                      # HEF-Dateien (gitignored)
│       ├── unet_nowcast.hef
│       └── unet_nowcast.meta.json
├── train_data/                     # gitignored
│   ├── radar/, objects/, weather/, wind/, cape/, lightning/, ...
│   ├── arome/, cloud/, ir/, ir_cells/
│   ├── models/                     # versioniert
│   │   ├── current → v_2026-...
│   │   └── v_2026-05-15T03-00-00Z/
│   ├── onnx/                       # ONNX-Exports
│   ├── calib/                      # INT8-Calibration-Daten
│   └── evaluation/                 # Logs, cleanup_log.jsonl, api_health.jsonl
├── data/                           # Live-Cache (gitignored)
└── logs/                           # gitignored
```

### 11.2 Auf dem Linux-Trainer

Identisches Layout. `train_data/` wird durch rsync vom Pi gefüllt, `models/`
wird auf Linux geschrieben und durch rsync zum Pi gesynct.
Auf Linux **kein** `wetterprojekt.service` (kein Live-Loop), aber
`wetterprojekt-scheduler.service` aktiv (für Training-Jobs).

### 11.3 Binaries die NICHT ins Git gehören ✅ (in .gitignore implementiert)

Alle folgenden Typen sind im `.gitignore` eingetragen und automatisch ausgeschlossen.

- `*.hef` — Hailo-Modelle (Phase B, via rsync Pi ← M910q)
- `*.keras`, `*.h5` — Keras/TF-Modelle
- `*.txt.lgb` — LightGBM-Modelle
- `*.joblib`, `*.pkl` — Scaler / Pickle
- `*.onnx` — ONNX-Exports (Phase B)
- `*.npz` — NumPy-Archive (Datasets, Calibration-Daten)
- `*.parquet` — Tabular Datasets
- `*.png`, `*.kmz`, `*.gif` — generierte Bilder/Exports
- `models/hailo/` — HEF-Verzeichnis
- alles in `data/`, `logs/`, `train_data/`

**Distribution:** Initialmodell-Bootstrap per `scp` oder GitHub Release. Phase B HEF via `sync_models_to_pi.sh`.

**Verifikation:**
```bash
git check-ignore -v *.keras models/hailo/unet_nowcast.hef
```

---

## 12. `hailo_inference.py` (produktionsreifer Wrapper für Phase B)

Diese Datei ersetzt die bestehende Stub-Version im Repo vollständig.
Wird in Phase B Task B5 eingespielt, sobald der erste HEF verfügbar ist.

```python
# hailo_inference.py
"""
Hailo-8 Inferenz-Wrapper für WetterExtended.

Architektur:
  - Singleton VDevice (ein Handle pro Prozess)
  - Thread-safe über _LOCK (RLock)
  - Lazy-Load der HEF-Dateien beim ersten Aufruf
  - Latenz-Logging → train_data/evaluation/hailo_latency.jsonl
  - CPU-Fallback wenn Hailo nicht verfügbar oder HEF fehlt

Unterstützte Modelle (Phase B):
  unet_nowcast  (1, 256, 256, 4) → (1, 256, 256, 5) — Radar-Nowcasting
"""

import json
import os
import threading
import time
from typing import Optional

import numpy as np

try:
    from debug_utils import debug_log, log_api_failure
except Exception:
    def debug_log(msg): print(msg)
    def log_api_failure(*a, **kw): pass

from config import SAVE_PATHS

_HEF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "hailo")

_MODEL_SPECS: dict = {
    "unet_nowcast": {
        "hef":          os.path.join(_HEF_DIR, "unet_nowcast.hef"),
        "meta":         os.path.join(_HEF_DIR, "unet_nowcast.meta.json"),
        "input_shape":  (1, 256, 256, 4),
        "output_shape": (1, 256, 256, 5),
        "description":  "Radar Nowcasting (5 Horizonte)",
    },
}

_LATENCY_FILE = os.path.join(
    SAVE_PATHS.get("evaluation", "train_data/evaluation/").rstrip("/"),
    "hailo_latency.jsonl",
)

_LOCK = threading.RLock()
_vdevice = None
_network_group_cache: dict = {}
_hef_cache: dict = {}
_hailo_available: Optional[bool] = None

# ... (vollständige Implementierung siehe §11 in Dokumentversion 4.0)
```

---

## 13. Externe APIs — kritische Constraints

| API | URL | Limit | Bemerkung |
|-----|-----|-------|-----------|
| ARSO Radar | `https://meteo.arso.gov.si/uploads/probase/www/nowcast/inca/inca_si0zm_latest.kmz` | keine offizielle Quote | öffentlich, kein Key; If-Modified-Since reduziert Traffic |
| Open-Meteo icon_d2 | `https://api.open-meteo.com/v1/forecast?models=icon_d2` | 10 000/Tag (free) | **A7 erledigt: Bulk-Query + Cache** |
| Open-Meteo icon_global 700hPa | `https://api.open-meteo.com/v1/forecast` | gleiche Quote | **A7 erledigt: Bulk-Query + Cache** |
| GeoSphere CAPE | `https://dataset.api.hub.geosphere.at/v1/grid/forecast/nwp-v1-1h-2500m` | keine offizielle Quote | öffentlich, kein Key |
| EUMETView WMS | `https://view.eumetsat.int/geoserver/...` | keine offizielle Quote | langsam, manchmal Ausfälle |
| Copernicus DEM | `https://copernicus-dem-30m.s3.amazonaws.com` | keine | nur Erstdownload nötig |
| lightningmaps.org | siehe `config.py` | inoffiziell | **NICHT für Produktion — Phase C: bessere Quelle** |
| Blitzortung | `https://data.blitzortung.org/Data/Protected/...` | Account nötig | **A3 erledigt: HTTP-Basic-Auth** |
| Anthropic API | `https://api.anthropic.com` | abhängig vom Plan | nur wenn `AI_ANALYSIS_CONFIG['enabled']` |

---

## 14. Aktueller Repo-Stand (Mai 2026)

### 14.1 Was funktioniert
- **3-Stage Kalman-Matching (Mai 2026):** Zell-ID-Persistenz durch Kalman-Predicted-Polygon-Overlap (Stage 1), Zentroid-Distanz-Fallback (Stage 2), klassischer Overlap-Fallback (Stage 3). Wissenschaftliche Basis: SORT (Bewley et al. 2016), Enhanced TITAN (Han et al. 2009). ✅
- HSV-Segmentierung + Kalman-Tracking (`object_tracking.py`)
- **Human-in-the-Loop Filter-Verfeinerung** (`cell_filters.py` + Filter-Galerie):
  Benutzer-Polygon → HSV-Extraktion → PNG-Speicherung → KI-Vorschläge via Anthropic API
- LSTM, LightGBM-Punkt + Quantile (`model_training.py`)
- ConvLSTM-Modell (`radar_convlstm.py`) — MODEL_PATH via SAVE_PATHS + runtime_config
- 5 Forecast-Horizonte (10/20/30/40/60 min)
- Zell-Prognose-Animation (`MapView.jsx` / `ForecastGhostLayer`): Kontur wandert
  gestrichelt entlang des Forecast-Pfades bis +60 min, rein clientseitig ✅
- Closed-Loop-Verifikation (`accuracy_tracker.py`)
- KI-Analyse via Anthropic API (`daily_analyzer.py`)
- React/Vite Admin-Panel mit 14 Seiten (inkl. Atmosphäre)
- KMZ-Export mit Pfeilen + Unsicherheits-Ellipsen
- `install.sh` mit `--mode=full|upgrade`, `--no-hailo`, `--no-node`, `--no-training`
- Hailo-apt-Installation in `install.sh`
- Scheduler mit allen Jobs; LOCAL_TRAINING-Guard aktiv
- nginx Basic-Auth mit Zufallspasswort; `/karte` ohne Auth
- Daten-Rotation via `cleanup_old_data.py` täglich 04:30
- Disk-Monitoring im Dashboard (`/api/disk`)
- Open-Meteo Bulk-Query + API-Cache (`api_cache.py`)
- Atmosphären-Snapshot 36-Punkt-Raster für Kärnten (`fetch_atmospheric_snapshot.py`, `ATM_SNAPSHOT_LOCATIONS` in `config.py`): 9×4-Gitter ~24×28 km, lückenlose Abdeckung des gesamten BBOX bei ATM_RANGE 20 km (Worst-Case 18,4 km), 5 Batches à 8 Locations via `_bulk_get_batched()`, 720 Req/Tag (7,2 % Limit) ✅
- File-Locking (`fcntl.flock`) + Atomic-Write in `runtime_config.py`
- `LOCAL_TRAINING`-Flag in config, scheduler, install.sh, app.py, Training.jsx
- `/api/hailo/reload` Endpoint für rsync-Post-Hook
- API-Requests-Statistik im Dashboard (`/api/api_calls`)
- Gewitterrisiko-Grid-Layer in MapView + MapFullscreen (`/api/risk_grid`):
- E-Mail-Benachrichtigungen (`email_notifier.py`): SMTP STARTTLS, HTML-Mails
  mit Karten-Link, pro Ort mehrere Empfaenger (;-getrennt), Cooldown 15/5 min;
  SMS-Versand (sms_notifier.py) aus main.py entfernt
- nginx /karte Trailing-Slash-Fix: Regex-Match `~ ^/karte(/.*)?$` statt
  Exact-Match `= /karte`; live in install.sh und auf System angewendet
  Grid 0.05° über Kärnten, 3 Quellen (Zellen, Blitze, LI), farbige
  Flächen ohne Rand (gelb/orange/rot), Risikozonen standardmäßig aktiv

- **UI-Paket Risikozonen/IR-Vorläufer** (`MapView.jsx`, `MapFullscreen.jsx`, `app.py`):
  Risikozonen-Layer default aktiviert; IR-Vorläufer-Toggle zu Checkbox umgebaut
  (konsistent mit Radar/Blitze/Risikozonen); 1×/2×/4×-Geschwindigkeitsbuttons
  auf `/karte` entfernt; Wolkentop im Risikozonen-Hover-Tooltip ergänzt
  (max aus EUMETView Atm-Snapshot + cloud_top_height_msl der Sturmzellen);
  IR-Vorläufer-Schwellwert dokumentiert: BT < 230 K ≈ 9.800 m MSL

- **UI-Rename CB > 10.000** (`MapView.jsx`, `MapFullscreen.jsx`):
  Alle sichtbaren UI-Texte „IR-Vorläufer" wurden in „CB > 10.000" umbenannt.
  Checkbox-Label, Tooltip-Titel und title-Attribute aktualisiert.
  Farbkodierung dokumentiert: Violett = BT < 230 K, Rot = Overshooting Top BT < 215 K.
  Interne Variablennamen (showIrCells, irCells) unverändert.

- **Fix-Paket Zugbahn + Wolkenhöhe** (`app.py`, `MapView.jsx`, `MapFullscreen.jsx`):
  Forecast-Segment-Mindestlänge 2 km eingeführt (Nullsegmente → kein false-positive
  in_forecast_track); Dominant-Overwrite-Bug behoben (dominant="track" wird nicht mehr
  durch dominant="atm" überschrieben); Wolkenhöhe im Risikozonen-Tooltip und
  IR-Vorläufer-Tooltip jetzt in Meter (statt km) mit Tausender-Trennpunkt;
  IR-Vorläufer-Tooltip zeigt jetzt auch cloud_height_m aus ir_cell_detection.py

- **Fix-Paket Mai 2026** (Reihenfolge + Vollständigkeit der Objekt-Pipeline):
  Blitzdaten werden jetzt vor `assign_convective_indices()` geholt
  (`lightning_count_10km` korrekt für hail_prob2); Objekt-JSON wird erst
  nach vollständiger Anreicherung (wind_shear, hail_prob, stationary_marker,
  location_hits) gespeichert; q10/q90-Unsicherheits-Pfeile werden korrekt
  als Lat/Lon gespeichert; `/api/risk_grid` verwendet Runtime-Horizonte;
  nginx gibt `/api/lightning` + `/api/risk_grid` öffentlich frei;
  KMZ-Download via `/api/export/forecast.kmz` + Button in MapView;
  Antwortzeiten (duration_ms) in API-Statistik; Timestamp-basierte
  Trainingsziel-Suche in `dataset_builder.py` (build_dataset +
  build_classification_dataset); Source-Modus-Toggle (Volltext/Gekürzt)
  in KI-Analyse-Chat; Runtime-BBOX in preprocess_image und
  detect_and_track_objects.
- **Konvektive Diagnose-Indizes** (`compute_convective_indices.py`):
  SHIP, Lapse Rate 700-500, 0–6-km-Scherung, CIN, PW, Lightning Jump,
  hail_prob2 — alle rein rechnerisch ohne neuen API-Aufruf
- **Risikozonen-Layer mit Hover-Tooltip** (`MapView.jsx`, `MapFullscreen.jsx`):
  Diagnose-Werte als Tooltip ueber farbigen Flaechen, unterdrueckt wenn
  Sturmzelle drueber
- **Forecast-Zugbahn im Risk-Grid** (`/api/risk_grid`): Punkt-zu-Linien-Distanz
  fuer den gesamten Pfad, Korridor 30 km

### Konvektions-Ausblick (12 h) — Phasen-Status

| Phase | Inhalt | Status |
|---|---|---|
| O1 | 12-h-Zeitreihe der konvektiven Felder (`fetch_outlook_series.py`) | ✅ erledigt (Prompt 7) |
| O2 | Stündliche Risiko-/Schwere-Raster (`convective_outlook.py`) | ✅ erledigt (Prompt 8) |
| O3 | Ausblick-Seite mit Zeit-Slider (`/ausblick`) | ✅ erledigt (Prompt 9) |

### 14.2 Was fehlt noch

#### Konvektive Diagnose — Phasen-Status

| Phase | Inhalt | Status |
|---|---|---|
| K1 | Open-Meteo icon_global Pressure-Request um T500/T700/CIN/PW erweitern | ✅ erledigt |
| K2 | Atmosphaeren-Snapshot um dieselben 4 Parameter erweitern | ✅ erledigt |
| K3 | `compute_convective_indices.py` (SHIP, Lapse, 0-6-km-Shear, Lightning Jump) | ✅ erledigt |
| K4 | `ML_CELL_FEATURES` um 11 neue Features erweitert | ✅ erledigt |
| K5 | `main.py` Pipeline-Integration | ✅ erledigt |
| K6 | `/api/risk_grid` Forecast-Zugbahn + Hovertext-Daten | ✅ erledigt |
| K7 | MapView/MapFullscreen Hover-Tooltip auf Risk-Rectangles | ✅ erledigt |
| K8 | Modelle nach Deployment einmalig neu trainieren | ⏳ automatisch beim naechsten Cron-Slot |
| K9 | Isotonic-Kalibrierung von hail_prob2 mit Bodendaten | 🔜 Phase D (braucht Schadensdaten) |
| K13 | Schwere-Trainingsdatensatz Regen/Böen (`severity_dataset.py`) | ✅ erledigt (Prompt 2) |
| K14 | Schwere-Modelltraining LightGBM Regen/Böen (`severity_training.py`) | ✅ erledigt (Prompt 3) |
| K15 | Schwere-Vorhersage in Pipeline + Karten-Popup (`severity_predict.py`) | ✅ erledigt (Prompt 4) |
| K16 | Schwere-Verifikation Regen/Böen + `/api/severity_accuracy` (`severity_verification.py`) | ✅ erledigt (Prompt 5) |
| K10 | Hazard-spezifische Module (Wind/Rain/Tornado getrennt) | ✅ erledigt (Prompt 2–5; Tornado offen) |
| K12 | Erweiterte Features: DCAPE, 0-1/0-3-km-Shear, SRH, CAPE-/LI-Trend, VIL-Proxy (`compute_extra_features.py`) | ✅ erledigt (Prompt 1) |
| K11 | ALDIS-Blitze (statt Blitzortung.org) | ❌ verworfen — Blitzortung.org bleibt |
- Hailo-Inferenz nicht produktionsreif (`hailo_inference.py` ist Stub — Phase B: Task B5)
- U-Net nicht implementiert — Phase B: Task B8
- Linux-Rechner nicht angeschafft — Phase B: Voraussetzung
- `tools/sync_*.sh` fehlen noch im Repo — Phase B: Task B6
- DEM-Kacheln hardcoded in `dem_feature.py` — Phase C
- `cloud_height_from_eumetview.py`: `print` statt `debug_log`, kein `log_api_failure` — Phase C
- Lightning-Quelle `lightningmaps.org` inoffiziell — Phase C

### 14.3 Bestehende systemd-Services auf Pi
- `wetterprojekt.service` — main.py Live-Loop
- `wetterprojekt-scheduler.service` — scheduler.py
- `wetterprojekt-admin.service` — app.py Flask + nginx

---

## 15. Bekannte Bugs — Status

| # | Datei | Bug | Status |
|---|-------|-----|--------|
| B1 | `assign_cape_from_forecast.py` | `parse_timestamp`: `fmt` nicht benutzt | ✅ **behoben (A1)** |
| B2 | `radar_download.py` | Kein Timeout am GET, kein log_api_failure | ✅ **behoben (A2)** |
| B3 | `blitz_api.py` | Username/Passwort in URL → in Logs | ✅ **behoben (A3)** |
| B4 | Systemweit | Trainingsdaten wachsen unbegrenzt | ✅ **behoben (A4)** |
| B5 | `app.py` | Keine Authentifizierung | ✅ **behoben (A6)** |
| B6 | `fetch_arome_openmeteo.py` | 1 API-Call pro Zelle statt Bulk | ✅ **behoben (A7)** |
| B7 | `runtime_config.py` | Atomic-Write ok, kein File-Lock | ✅ **behoben (A9)** |
| B8 | `radar_convlstm.py` | MODEL_PATH hardcoded | ✅ **behoben (A10)** |
| B9 | `fetch_700hpa_wind_per_object_slim.py` | Kein `log_api_failure`, kein Bulk | ✅ **behoben (A7)** |
| B10 | `dem_feature.py` | DEM-Kachel hardcoded | ⏳ Phase C |
| B11 | `cloud_height_from_eumetview.py` | `print` statt `debug_log`, keine log_api_failure | ⏳ Phase C |
| B12 | Lightning-Config | `lightningmaps.org` ist inoffiziell | ⏳ Phase C |
| B13 | `weather_api.py` | TAWES-Request ohne Cache → überschreitet 10-min-Intervall | ✅ **behoben (P04)** |
| B14 | `debug_utils.py` | `api_call_summary()` ohne last_ts/last_url → kein Detail im Dashboard | ✅ **behoben (P01/P02/P03)** |
| B15 | `daily_analyzer.py` | KI-Report enthält keine lokale Konfiguration → keine Konfig-Empfehlungen möglich | ✅ **behoben (P05)** |
| B16 | `prediction.py`, `object_tracking.py` | Forecast-Einheiten mischen px/Frame mit Minuten (kein Frame-Intervall), zwei unterschiedliche PX_TO_KMH-Werte | 🚧 **in Behebung (A.1 Welle 1, Prompt P01)** |
| B17 | `dataset_builder.py`, `prediction.py`, `intensity_regression.py` | `pixel_to_geo(obj["x"], obj["y"])` mit pre-upscale-Koordinaten → falsche Geo-Zuordnung für ML-Features | 🚧 **in Behebung (Prompt P02)** |
| B18 | `accuracy_tracker.py` | Pixel-Fehler vergleicht skalierte Forecast-Koords mit pre-upscale Ist-Koords; keine differenzierten Verifikations-Buckets | 🚧 **in Behebung (Prompt P03)** |
| B19 | `app.py` | Flask lauscht auf `0.0.0.0:5000` → nginx-Basic-Auth umgehbar | 🚧 **in Behebung (Prompt P04)** |
| B20 | `radar_download.py` | `zf.extractall()` ohne Pfadprüfung → Zip-Slip-Risiko | 🚧 **in Behebung (Prompt P05)** |
| B21 | `tests/test_locations_e2e.py` | `sys.exit()` auf Modulebene bricht pytest-Collection ab | 🚧 **in Behebung (Prompt P06)** |
| B22 | `model_training.py` | Zufälliger Train/Val-Split bei Zeitreihen + Promotion bei <20 Samples / 2 % Toleranz | 🚧 **in Behebung (Prompt P07)** |
| B23 | `kmz_export.py` | Keine aktuellen Zellen, keine Konturen, keine Location-Hits; Farb-Lookup bricht bei String-Keys | 🚧 **in Behebung (Prompt P08)** |
| B58 | `requirements.txt` | `psutil` fehlt als Runtime-Dependency — CPU-Monitor-Job schreibt kein `cpu_history.jsonl` auf sauberer Installation. Fix: `psutil>=5.9` in `requirements.txt` ergänzt. | ✅ erledigt |
| B59 | `main.py` | `_hit_is_kinematic()`: Current-Hits (Horizont-Key 0 = Zelle JETZT im Radius) wurden durch 2-Frame-Bestätigung verzögert. Fix: Prüfung ob `0 in loc_hit["hits"]` — wenn ja, sofort False zurückgeben (kein Defer). Akutwarnungen erfolgen jetzt in jedem Fall sofort. | ✅ erledigt |
| B60 | `main.py` | Rückgabewert von `send_allclear_email()` ignoriert — `_location_warned` wurde auch bei SMTP-Fehler/Cooldown bedingungslos geleert. Folge: nach gescheiterter Entwarnung keine neue Warnung für denselben Ort. Fix: `ok = send_allclear_email(...)` — `discard()` nur wenn `ok == True`. | ✅ erledigt |
| B61 | `debug_utils.py` | `api_call_summary()` zählte nur `status >= 400` als Fehler. Terminale Retry-Fehler aus `http_retry.py` (status=0) und Records mit `error`-Feld wurden nicht gezählt → Dashboard zeigte 0 Fehler trotz Netzwerkausfällen. Fix: `_status == 0` und `bool(rec.get("error"))` als weitere Fehlerbedingungen; `int(... or 0)` schützt gegen `None`-Status. | ✅ erledigt |
| B92 | **Tendenz-Felder pro Zelle (Backend).** `object_tracking.py` schreibt zusätzlich `size_trend` (-1/0/+1, relative Flächenänderung ggü. Vorframe). `prediction.py` klassifiziert je Zelle `intensity_tendency`/`size_tendency`/`tendency_source`: ML-Regressoren (`delta_core_ratio_pred`/`delta_area_pred`) wenn vorhanden, sonst kinematischer Fallback (`trend`/`size_trend`). Neue Config-Schwellwerte `TENDENCY_CORE_DELTA_STABLE=0.05`, `TENDENCY_AREA_PCT_STABLE=0.10`. Grundlage für Popup-Anzeige (Frontend P-T02). | `config.py`, `object_tracking.py`, `prediction.py` | ✅ erledigt |

### Neue Fach-Features in Phase C (geplant und umgesetzt)

| Feature | Beschreibung | Status |
|---|---|---|
| **Human-in-the-Loop Filter (HitL)** | Vom Benutzer markierte Zellen erweitern HSV-Filter; gespeicherte Polygon-PNGs dienen als Trainings-Quelle für ein künftiges U-Net auf dem Hailo-8 | ✅ **eingespielt** (Mai 2026) |
| HitL als U-Net-Trainings-Pipeline | Polygon-PNGs (mit Maske) als labels für ein semantisches Segmentierungs-Modell — Hailo-8 erzielt > 100 FPS bei 256×256 px | ⏳ geplant |
| **Dashboard API-Request Detail** | Klick auf Service-Zeile im Dashboard öffnet Panel mit letzten Requests (Timestamp, HTTP-Status, URL). Schnittstellen mit öffentlichem Browser-Zugang zeigen direkten Link (z.B. https://tawes.at/#knt) | ✅ **eingespielt** (Mai 2026) |
| **TAWES Cache-Konsolidierung** | `weather_api.py` nutzt jetzt `api_cache` mit TTL=600s — entspricht 10-min TAWES-Aktualisierungsintervall. Kein unnötiger Doppel-Request mehr neben `fetch_tawes_gust.py` | ✅ **eingespielt** (Mai 2026) |
| **KI-Analyse sendet vollst. Konfig** | `build_system_report()` überträgt alle effektiven Config-Werte + `runtime_overrides.json` an die KI. Secrets (TOKEN, KEY, PASS, ...) werden automatisch durch `***REDACTED***` ersetzt. KI kann nun Konfigurations-Empfehlungen machen | ✅ **eingespielt** (Mai 2026) |
| **WhatsApp-Benachrichtigungen via CallMeBot** | Neues Modul `whatsapp_notifier.py`: Gewitterwarnung, Entwarnung und Risiko-Stufe-3-Alarm per WhatsApp. Konfiguration pro Ort als `+Nr:APIKey`-Paar im `whatsapp`-Feld der `LOCATIONS_WATCHLIST`. Kein globaler API-Key nötig. Cooldown identisch zu `email_notifier.py`. `Locations.jsx` um WhatsApp-Spalte erweitert. | ✅ **eingespielt** (Juni 2026) |
| **KI-Analyse: Vollständige Tagesdaten** | `daily_analyzer.py`: `_load_recent_objects()` durch `_load_storm_day_summary()` ersetzt. Liest `cells_log.jsonl` (Sturm-Tagesübersicht: Frames, Peak, Zeitfenster, Lineages), aggregiert Orts-Treffer aus allen `locations_YYYY-MM-DD_HH-MM-SS.json` Dateien des Analyse-Fensters, lädt Top-3 Peak-Frames mit vollständigen Zelldaten (CAPE, Blitzcount, Severity, Hagel). Neue Funktion `_load_journal_error_digest()` wertet systemd-Journal beider `wetterprojekt`-Services auf Tracebacks/Exceptions aus (dedupliziert, Top-10). | ✅ **eingespielt** (Juni 2026) |
| **KI-Analyse: Token-Vorfilterung (Symptom-Gate + AST-Skelett)** | `daily_analyzer.py`: `_collect_source_context()` um optionalen `report`-Parameter erweitert. Bei automatischer Analyse werden nur symptom-relevante Dateien als Volltext geladen; alle anderen als kompaktes AST-Skelett (Signaturen + Docstrings, ~80–90 % Token-Einsparung). Mapping in `_SYMPTOM_FILE_MAP`: accuracy → prediction/tracker/tracking, api → fetch-Module, model → training/builder/convlstm, storm → tracking/prediction. `_extract_ast_skeleton()` nutzt Python-`ast`-Modul. `source_context` wird nach `storm_day_summary` und `journal_errors` gesammelt, damit das Symptom-Gate alle Metriken sieht. Interaktiver Chat bleibt unverändert (`report=None`). | ✅ **eingespielt** (Juni 2026) |
| **WhatsApp Test-Funktion** | `whatsapp_notifier.send_test_wa(wa_str)`: neue öffentliche Funktion ohne Cooldown; sendet neutrale Testnachricht an alle Empfänger des wa_str; gibt `{ok, sent_to, failed, error}` zurück. `POST /api/whatsapp/test` in `app.py`: REST-Endpunkt analog zu `api_ai_analysis_test_email`; loggt in `api_call_counts.jsonl` unter Service `callmebot_whatsapp`. `Locations.jsx`: inline „Test"-Button pro Ort mit Loading-State und per-row Ergebnis (`✓ Gesendet: +43...` / `✗ Fehler`). | ✅ **eingespielt** (Juni 2026) |

---

## 16. Konventionen für Prompts und Code

### 16.1 Sprache
- Antworten auf Deutsch
- Code-Kommentare auf Deutsch (außer wenn API-Pattern es nahelegt)
- Variable-Namen auf Englisch

### 16.2 Code-Lieferung
- Code im Chat zeigen, nicht in Artifacts
- Bei Datei-Änderung klar angeben:
  - **"vollständige Datei ersetzen"** ODER
  - **"Abschnitt X durch Y ersetzen"** mit exakten Such-/Ersatz-Strings
- Bei mehreren Änderungen in einer Datei: jede einzeln dokumentieren
- Verifikations-Befehl mitliefern
- **Binaries nie in Prompts** — als downloadbare Dateien bereitstellen

### 16.3 Atomare Prompts

Jeder Code-Prompt enthält:
1. Dateiname exakt
2. Was die Änderung bewirkt (auf Deutsch)
3. Falls partial: exakter Such-String + exakter Ersatz-String
4. Falls neu: vollständiger Datei-Inhalt
5. Verifikations-Befehl
6. Bekannte Risiken / Voraussetzungen

### 16.4 Was zu vermeiden ist
- Keine Mock-Modelle, keine Beispiel-Code-Skizzen
- Keine Vermutungen über Imports oder Pfade — projekt-spezifisch prüfen
- Keine Stub-Implementierungen mit `TODO`-Kommentaren
- Keine Massenänderungen über mehrere Dateien gleichzeitig — pro Prompt eine Datei

### 16.5 Verifikation
- Vor jedem Lieferungsschritt: `project_knowledge_search` aufrufen
- Bei Behauptungen über bestehenden Code: zitierte Suchergebnisse als Evidenz
- Bei Reviews: Tabelle "Behauptung vs. Realität"

---

## 17. Infrastruktur & Security

### SEC-01 — nginx Rate-Limiting + fail2ban
**Status:** ✅ Implementiert
**Datum:** 2026-06-04
**Auslöser:** 3 Reconnaissance-Scan-Wellen in 3h (73 Requests, alle 404 — Spring Boot Actuator, .env, AWS-Credentials, Docker-Configs)

**Maßnahmen:**
- nginx `limit_req_zone wetter_api` 60r/m, Burst 30: verhindert Scan-Bursts nach Burst-Erschöpfung (HTTP 429)
- nginx `limit_req_zone wetter_auth` 10r/m, Burst 5: Login-Endpunkt gegen Credential-Stuffing
- fail2ban Jail `nginx-recon`: Ban nach 20×404 in 60s für 1h
- fail2ban Jail `nginx-ratelimit`: Ban nach 10×429 in 60s für 2h
- `ignoreip = 127.0.0.1/8` verhindert Self-Ban bei internen Health-Checks

---

## 18. Risiken

| Risiko | WSK | Auswirkung | Mitigation |
|--------|-----|------------|------------|
| Hailo DFC kompiliert U-Net-Layer nicht | mittel | Build schlägt fehl | Nur DFC-getestete Layer verwenden |
| INT8-Quantization verschlechtert U-Net | mittel | Qualität bricht ein | INT16-Modus als Fallback testen |
| rsync schlägt fehl → Pi mit altem Modell | niedrig | Sub-optimale Vorhersage | Modell-Versionierung greift, alte Version bleibt aktiv |
| Linux-Trainer fällt aus | mittel | Kein Modell-Update | Pi-CPU-Training als Fallback (`LOCAL_TRAINING=True` zurücksetzen) |
| Hailo-Treiber-Update bricht API | niedrig | Inferenz fällt auf CPU | CPU-Fallback in `hailo_inference.py` |
| Calibration-Daten zu klein | hoch | Schlechte INT8-Quantization | Mindestens 200 reale Patches |
| SD-Karte voll | niedrig | Pi crasht | **Behoben durch A4** (cleanup_old_data.py) |

---

## 19. Quick-Start für neue Chat-Session

```
Nutzer in neuer Session:
  "Lies HAILO_INTEGRATION.md und mach weiter mit Phase B"

Claude:
  1. Sucht im Project-Knowledge nach HAILO_INTEGRATION.md
  2. Prüft: Phase A vollständig (ja) → Phase B ist nächste Phase
  3. Prüft Voraussetzungen: Linux-Rechner vorhanden?
  4. Falls ja: liefert atomaren Prompt für Task B1
  5. Wartet auf Bestätigung
  6. Liefert nächsten Task
```

---

## 20. Glossar

| Begriff | Bedeutung |
|---------|-----------|
| HEF | Hailo Executable Format — kompiliertes NPU-Modell |
| HAR | Hailo Archive — Zwischenformat im Compile-Prozess |
| DFC | Dataflow Compiler — Hailo-Toolchain, nur x86-Linux |
| HailoRT | Hailo Runtime — Treiber + Python-API auf dem Pi |
| VDevice | Virtuelles Device — Hailo-8-Abstraktion für Inferenz |
| INT8 / INT16 | Quantization-Bit-Tiefe — INT8 schneller, INT16 präziser |
| U-Net | Encoder-Decoder-Architektur mit Skip-Connections für Bild-zu-Bild-Aufgaben |
| Nowcasting | Kurzfrist-Wettervorhersage (0–6 h) |
| Edge-Rechner | Hier: Raspberry Pi 5 mit Live-Loop und Inferenz |
| Trainer-Rechner | Hier: x86-Linux-PC mit Training, DFC-Build und ONNX-Export |
| Closed-Loop-Verifikation | Vergleich Vorhersage vs. tatsächliche Beobachtung nach Eintritt |
| MAE | Mean Absolute Error — durchschnittlicher absoluter Fehler |
| ARSO | Slovenian Environment Agency — liefert Radar-KMZ |
| GeoSphere | Geosphere Austria — österreichischer Wetterdienst, liefert CAPE |
| EUMETView | EUMETSAT WMS-Service für Satellitendaten |
| LOCAL_TRAINING | Flag in config.py: True = lokales Training, False = Modelle kommen extern |
| api_cache.py | Zentrales Cache-System (Memory + Disk + TTL) für alle externen API-Calls |

---

**ENDE DOKUMENT**

Bei Unklarheiten oder Konflikten zwischen diesem Dokument und Anweisungen in
einer neuen Chat-Session gilt dieses Dokument als verbindlich, sofern der
Nutzer es nicht explizit ändert.

---

## 16. Phase E — IR-Sat Pre-Convection Tracking ⏳ OFFEN

### 16.1 Motivation

Das Radar-Tracking erkennt eine Sturmzelle erst, sobald sie Niederschlagskerne ≥ 54 dBZ produziert (Rot/Violett im ARSO INCA si0zm). Konvektive Wolken (Cumulonimbus-Amboss) sind aber im MSG IR108 schon 15–30 min früher als kalte Wolkentops (BT < 230 K) sichtbar.

Phase E ergänzt deshalb das bestehende Radar-Tracking um eine **zweite Tracking-Pipeline auf Basis des bereits gecachten IR108 TIFFs**. Es entstehen keine neuen externen API-Aufrufe — das TIFF wird heute schon alle 15 min für `cloud_top_height_msl` geladen.

Ziel ist:
1. Vorlaufzeit für Warnungen um 15–30 min verlängern
2. Andere Zugbahn der Wolke (300 hPa) gegenüber dem Niederschlag (700 hPa) als ML-Information nutzen
3. Lebenszyklusphase (wachsend / reif / zerfallend) per BT-Trend in `intensification_prob` einfließen lassen
4. Overshooting-Top-Detection als zusätzlicher Hagel-Prädiktor
5. Pseudo-Zellen ohne Radar-Echo als Vorwarn-Markierungen auf Karte und Risk-Grid

Bestehende Operativ-Vorbilder: EUMETSAT NWC SAF RDT, DWD KONRAD3D, Google MetNet-3.

### 16.2 Architektur-Entscheidungen (verbindlich)

- **Datenquelle:** Ausschließlich das bereits gecachte EUMETView IR108 TIFF aus `cloud_height_from_eumetview.py`. Kein neuer WMS-Layer, kein neuer Endpunkt.
- **Update-Rate IR-Pipeline:** An MSG-Full-Earth-Scan gekoppelt (15 min). Wenn das TIFF im Cache älter als 15 min ist, läuft die IR-Pipeline nicht erneut.
- **Räumliche Auflösung:** MSG IR108 ≈ 3 km im Sub-Sat-Punkt → für Kärnten ≈ 5 km. Bewusst gröber als ARSO 1 km — IR-Cells sind Vorläufer, nicht Ersatz.
- **300-hPa-Höhenwind:** Wird in den bestehenden Open-Meteo icon_global Bulk-Request integriert (kein neuer Request, identische Quote).
- **Tracking:** Eigenes Kalman pro IR-Cell, getrennt von `object_tracking.py`. Keine Vermischung der ID-Räume — Radar-Zellen behalten ihre IDs, IR-Cells haben Präfix `ir_`.
- **ML-Modelle:** Eigenes LightGBM für IR-Trajektorien (300-hPa-Steuerstrom). Das bestehende Radar-LightGBM/LSTM bekommt zusätzliche Features aus dem IR-Matching, wird aber nicht ersetzt.
- **Training:** Wie bei Phase B auf dem Linux-Trainer (`LOCAL_TRAINING=True`), Pi macht nur Inferenz.
- **Pseudo-Zellen in `/api/objects`:** Hinter Query-Param `include_ir=1` ausgeblendet (Default: aus), damit bestehende Frontend-Logik unverändert weiterläuft.
- **KMZ-Export:** Eigene KMZ-Folder „IR-Cells (Vorläufer)" und „Radar-Cells". Pfeil-Style gestrichelt für IR-Cells.

### 16.3 Task-Liste

Abarbeitungsreihenfolge: E4 → E1 → E2 → E3 → E5 → E7 → E9 → E6 → E8 → E10

| # | Task | Datei(en) | Status |
|---|------|-----------|--------|
| E1 | `ir_cell_detection.py` (neu): BT-Threshold-Mask aus IR108-TIFF, Connected Components mit Filter Größe/CAPE/LI, Output `train_data/ir_cells/ir_cells_<ts>.json` | `ir_cell_detection.py` (neu), `config.py` | ✅ erledigt |
| E2 | `ir_cell_tracking.py` (neu): Kalman-Tracking analog `object_tracking.py`, getrennter ID-Raum (`ir_<n>`), Optical Flow auf konsekutiven IR-TIFFs | `ir_cell_tracking.py` (neu) | ✅ erledigt |
| E3 | IR↔Radar Lineage-Matching: jede Radar-Zelle bekommt `ir_match_id`, jede IR-Zelle bekommt `radar_match_ids` (mehrere möglich beim Split) | `main.py`, `ir_cell_tracking.py` | ✅ erledigt |
| E4 | Open-Meteo icon_global Bulk-Request um **300 hPa Wind + Geopotential** erweitern (Bulk-Request, kein neuer API-Endpoint) | `fetch_700hpa_wind_per_object_slim.py`, `fetch_atmospheric_snapshot.py`, `api_cache.py` (TTL) | ✅ erledigt |
| E5 | `ML_CELL_FEATURES` um 10 neue Features erweitert: `bt_min_k`, `bt_mean_k`, `bt_trend_k_per_min`, `cloud_age_min`, `anvil_extension_km`, `overshooting_top`, `ir_only_precursor`, `wind_speed_300hPa`, `wind_dir_300_cos`, `wind_dir_300_sin` | `config.py`, `dataset_builder.py`, `prediction.py` | ✅ erledigt |
| E6 | `model_training.py`: Eigenes LightGBM-Trajektorien-Modell für IR-Cells (5 Horizonte, 300-hPa-Steuerstrom). Holdout-Validierung, Promotion-Logik analog Radar | `model_training.py`, `prediction.py` | ✅ erledigt |
| E7 | `/api/risk_grid` um Quelle `ir_cell` erweitern (eigene Farb-Variante: schraffiert). `/api/objects?include_ir=1` liefert auch Pseudo-Zellen | `app.py` | ✅ erledigt |
| E8 | Intensification-Prediction: `ir_to_radar_prob_<horizon>` — Wahrscheinlichkeit, dass IR-Zelle in 15/30/45 min ein Radar-Echo erzeugt. LightGBM-Binary-Classifier | `model_training.py`, `prediction.py` | ⏳ offen |
| E9 | KMZ-Export erweitern: getrennte Folder, gestrichelter Style für IR-Cells, `forecast.kmz` enthält beide Object-Typen | `kmz_export.py` (oder bestehender Export-Pfad) | ✅ erledigt |
| E10 | Atmosphäre-Seite + MapView/MapFullscreen-Legende ergänzen. Toggle „🛰 IR-Vorläuferzellen anzeigen" (default aus). | `MapView.jsx`, `MapFullscreen.jsx` | ✅ erledigt |
| E11 | UI-Verbesserungen: Risikozonen default aktiv, IR-Vorläufer als Checkbox, 1×/2×/4×-Buttons auf /karte entfernt, Wolkentop im Risikozonen-Tooltip (max aus Atm-Snapshot + Sturmzellen-cloud_top_height_msl) | `MapView.jsx`, `MapFullscreen.jsx`, `app.py` | ✅ erledigt | Benutzerhandbuch um Abschnitt 30 „IR-Sat Pre-Convection Tracking" ergänzt | `frontend/src/pages/Atmosphaere.jsx`, `frontend/src/pages/MapView.jsx`, `frontend/src/pages/MapFullscreen.jsx`, `docs/WetterExtended_Benutzerhandbuch.md` | ✅ erledigt |

### 16.4 Pre-Conditions

- ✅ Phase A (Stabilität) abgeschlossen
- ⏳ Phase B (Hailo+U-Net) — kann parallel oder vor Phase E laufen, kein harter Block
- ✅ EUMETView IR108 TIFF wird bereits gecacht (`cloud_height_from_eumetview.py`)
- ✅ `runtime_config` + `SAVE_PATHS["ir_cells"]` schon vorhanden
- ✅ Linux-Trainer existiert für E6/E8 Training

### 16.5 Schwellwerte (Defaults, runtime-überschreibbar)

| Konstante | Default | Bedeutung |
|---|---:|---|
| `IR_CONVECTION_BT_THRESHOLD_K` | 230.0 | Pixel mit BT ≤ Wert gelten als konvektiver Wolkentop |
| `IR_OVERSHOOTING_TOP_BT_K` | 215.0 | BT-Schwelle für Overshooting-Top-Detection |
| `IR_MIN_CELL_AREA_PX` | 30 | Mindestgröße einer IR-Cell (≈ 270 km² @ 3 km Pixel) |
| `IR_MIN_CAPE_J_KG` | 200.0 | IR-Cell wird nur als konvektiv gewertet wenn CAPE ≥ Wert |
| `IR_MAX_LI_C` | -0.5 | IR-Cell wird nur als konvektiv gewertet wenn LI ≤ Wert |
| `IR_TRACK_MAX_MISSING` | 2 | Wie viele 15-min-Slots eine IR-Cell ohne Detektion überlebt |
| `IR_INTENSIFICATION_BT_TREND_K_PER_MIN` | -1.5 | ΔBT/Δt unterhalb dieses Werts = rapide Vertiefung |

### 16.6 Was Phase E NICHT umfasst (Abgrenzung)

- Keine Änderung am HSV-Segmentierungs-Algorithmus für Radar
- Keine zusätzlichen externen APIs (keine neue Lightning-Quelle, kein ALDIS)
- Keine Änderung an `hail_prob` / `hail_prob2`. Erst Phase E.8 könnte `hail_prob3` einführen (Overshooting-Top-basiert)
- Kein U-Net auf IR (das ist Phase B, U-Net bleibt auf ARSO-Radar)
- Keine direkte Hailo-Beschleunigung für IR-Tracking (bleibt CPU)

### 16.7 Erfolgsmetriken

- Vorlaufzeit-Gewinn: median Δt(IR-Detect → erste Radar-Echo) ≥ 15 min über 30-Tage-Holdout
- Hit-Rate IR→Radar: Anteil IR-Cells die innerhalb 60 min ein Radar-Echo erzeugen ≥ 60 %
- False-Positive-Rate (IR-Cell ohne Radar-Echo binnen 90 min) ≤ 25 %
- Modell-MAE der IR-Cell-Trajektorie ≤ 8 km @ Horizon 30 min (im Mittel)
- Closed-Loop-Verifikation analog `accuracy_tracker.py` ist erweitert
4. Was die Änderung bewirkt
Phase E wird damit formal in der Roadmap verankert:

Tabelle in §4 zeigt sofort, dass es Phase E gibt mit klarem Status („⏳ Offen — Detail siehe §16").
Neuer §16 ist atomar und enthält Motivation, Architektur-Entscheidungen (verbindlich), 10 Tasks E1–E10, Pre-Conditions, alle Schwellwerte als Default-Werte, klare Abgrenzung zu Phase B, und messbare Erfolgskriterien.
Keine Code-Änderung in dieser Phase — nur die Roadmap. Die nächste Iteration kann dann atomare Prompts P-E01, P-E02 … für Claude Code generieren, einer pro Task.
Reihenfolge E4 → E1 → … → E10 ist bewusst: 300-hPa-Wind zuerst, weil sowohl E5 (Features) als auch E6 (Modell) ihn brauchen. E10 als letztes, weil Frontend erst sinnvoll ist, wenn Backend Daten liefert.

---

### 5.7 Phase A.6 — Hotfixes aus Produktions-Log-Analyse 2026-05-29 ✅ ABGESCHLOSSEN

**Analysiertes Log:** `wetterprojekt_logs_20260529_202402.txt`
**Ergebnis:** 1 kritischer Bug, 1 Medium-Bug, alle anderen Meldungen = Normalbetrieb

| # | Task | Datei(en) | Status |
|---|------|-----------|--------|
| B47 | Open-Meteo 400 Bad Request (2 Stufen): 1. `wind_speed_700hPa` → `windspeed_700hPa`, `wind_direction_700hPa` → `winddirection_700hPa` (Prompt 01). 2. `precipitable_water` + `convective_inhibition` entfernt — nicht in ICON verfügbar (Prompt 01b). | `fetch_outlook_series.py` | ✅ erledigt |
| B50 | `convective_outlook._cell_severity()`: PW-Fallback 25 mm bei CAPE≥200 wenn `precipitable_water` fehlt (ICON liefert es nicht) — verhindert dauerhaft-0 Regenrate im Risk-Grid | `convective_outlook.py` | ✅ erledigt |
| B48 | JWT Token-Rotation Multi-Tab Race Condition: BroadcastChannel in AuthContext.jsx | `frontend/src/context/AuthContext.jsx` | ✅ erledigt |
| B49 | `--mode=full` löscht `users.db` nicht mehr — Benutzerkonten bleiben bei Vollinstallation erhalten | `install.sh`, `docs/WetterExtended_Benutzerhandbuch.md` | ✅ erledigt |

**Bestätigter Normalbetrieb (kein Fix):**
- Keine Radar-Zellen erkannt (klarer Tag) → korrekt
- 0 Dataset-Samples → erwartet ohne Zellen
- Wolkenhöhe 0m alle Punkte → korrekt (IR-Pixel alle > 265K)
- Adaptiver Loop 900s (Ruhe > 60 min) → korrekt
- HEALTH-WARN 0 Samples → informativer Hinweis, kein Code-Bug

**Hailo-Integrationsstatus (unverändert):**
- Phase 1 (Installation) ✅ — Phase 2 (HEF-Export) 🔲 — Phase 3 (Runtime) 🔲
