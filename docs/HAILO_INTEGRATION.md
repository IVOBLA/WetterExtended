# HAILO_INTEGRATION.md
# WetterExtended — Hailo-Integration, Phasen-Roadmap & Multi-Rechner-Architektur

**Dokumentversion:** 5.1 (Phase A ✅ abgeschlossen | Phase B vorbereitet)
**Stand:** Mai 2026
**Sprache:** Deutsch (verbindlich)
**Zweck:** Übergabe-Dokument für neue Chat-Sessions. Jede hier dokumentierte
Entscheidung ist verbindlich und wird in einer neuen Session NICHT erneut
diskutiert.

---

## B135 – Debug-Export: Hauptjournal zeitrichtig (UTC-Epoch) + neueste Zeilen
Status: ERLEDIGT
Ursache: _journalctl_export_text nutzte strftime-Datums-String für --since (von journalctl
         als Lokalzeit/CEST interpretiert → Fenster 2h zu früh) und --lines=2000 ohne --until
         (lieferte die ÄLTESTEN 2000 Zeilen). Folge: wetterprojekt.service.log endete ~21h vor
         Exportzeit, die verbosen aktuellen Zeilen des Hauptdienstes fehlten (Beleg: Export
         2026-06-14 deckte nur 06-13 05:19–10:24 UTC ab, obwohl Dienst bis 06-14 07:05 lief).
Fix: --since/--until als UTC-Epoch (@<sek>), -n 5000 für die neuesten Zeilen im Fenster,
     Timeout 10→20s. Signatur um 'now' erweitert; Aufrufstelle angepasst. app.py-Live-Anzeige
     (_journalctl_unit_lines, bereits -n) unverändert.
Dateien: debug_export.py, tests/test_b135_journal_export_window.py (neu)

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
- **Raspberry Pi 5 B (8 GB)** — Hauptrechner, in Betrieb
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
### B121 – tracking_memory Persistenz + korrekter Loop-Intervall nach Neustart ✅
- **Symptom:** Zellen OYNHJFV9 + TFHWG0FD erhalten `lineage=new` statt `lineage=split`
  nach einem Admin-ausgelösten Service-Neustart während ILO9G570 aktiv war.
- **Beleg:** `log_clear_state.json` → `cleared_at_utc=14:33:15Z`;
  systemd `Starting...` 37s später; `_last_cells_active_ts=None` obwohl ILO9G570
  nur 3 min vorher aktiv war — ausschließlich durch Neustart erklärbar.
- **Ursache A:** `tracking_memory` ist in-memory, nach Neustart leer →
  kein Parent-Polygon → 3-Stage-Matching → `lineage=new`.
- **Ursache B:** `_last_cells_active_ts=None` nach Neustart → `_elapsed_skip=inf`
  → 900s-LOOP-SKIP sofort beim ersten 304-Zyklus → 15 min Blindflug
  mitten im aktiven Gewitter.
- **Fix A:** `save_tracking_snapshot()` schreibt `tracking_memory` nach jedem
  Tracking-Zyklus als JSON (ohne `kf`, numpy→list). Datei:
  `train_data/evaluation/tracking_memory_snapshot.json`.
  `load_tracking_snapshot()` lädt beim Modulimport (nur wenn Alter <
  `INACTIVE_CELL_TRACK_DURATION_S`). Gibt Snapshot-Alter zurück.
- **Fix B:** `main_loop()` ruft `load_tracking_snapshot()` vor dem While-Loop auf
  und setzt `_last_cells_active_ts = time.time() - snap_age_s` wenn Snapshot
  vorhanden → kein falscher 900s-Skip mehr nach Neustart bei aktivem Gewitter.
- **Dateien:** `object_tracking.py`, `main.py`, `tests/test_b121_tracking_snapshot.py`

| P28 | **Live-Daten: Inaktive Zellen (12 h) + Frames + Geschwindigkeit.** Neue Gruppe „Inaktive Zellen (letzte 12 h)" in `/live`. Neuer Backend-Endpoint `GET /api/objects/history` mit 60 s In-Memory-Cache liest gespeicherte Object-JSON-Dateien rückwärts, dedupliziert per Cell-ID (neuester Stand), filtert live IDs aus `tracking_memory` heraus. Neue „Frames"-Spalte (`total_active_frames`) in beiden Tabellen. Spalte „VX/VY" ersetzt durch „Geschw." (`speed_kmh` km/h + `direction_deg` °), beide bereits von `object_tracking.py` vorberechnet. | `app.py`, `frontend/src/pages/LiveDaten.jsx`, `tests/test_p28_inactive_cells_history.py` | ✅ erledigt |
| P2-1 | **Radar-Dedup: SHA256 als zweite Prüfebene.** Nach erfolgtem 200-Download wird SHA256 des KMZ-Inhalts mit gespeichertem Vorgänger-Hash (`data/.kmz_content_sha256`) verglichen. Bei Übereinstimmung → `False` (kein Tracking-Zyklus). Schützt vor CDN-Fällen wo ARSO gleichen Inhalt mit neuem `Last-Modified` liefert. `If-Modified-Since`-Mechanismus bleibt Primärschutz. | `radar_download.py`, `tests/test_p2_1_radar_hash_dedup.py` | ✅ erledigt |

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
| P2-2 | **Stiller Config-Ladefehler → Health-Status.** `runtime_config._load()` schluckte `json.JSONDecodeError` still → falsche oder fehlende Overrides blieben unsichtbar. Fix: `_LAST_LOAD_ERROR` Modul-Variable; `get_load_error()` API; `api_health_check._check_runtime_config()` integriert in `check_all_apis()` → erscheint im Dashboard-API-Health. | `runtime_config.py`, `api_health_check.py`, `tests/test_p2_2_config_health.py` | ✅ erledigt |
| P1-1 | **Sicherheit: sensible GET-Endpunkte waren anonym lesbar.** `_jwt_auth_check` ließ pauschal alle GET/HEAD ohne Token zu → `/api/config`, `/api/logs`, `/api/system/…`, `/api/email_config`, `/api/notification`, `/api/users` u.a. öffentlich abrufbar. Fix: Allowlist `_SENSITIVE_READ_PREFIXES`; GET/HEAD auf diesen Präfixen erfordern mind. viewer-Level. Öffentliche Karte (/api/objects, /api/forecast, /api/horizons, Bilder) bleibt offen. | `app.py`, `tests/test_get_auth_hardening.py` | ✅ erledigt |

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

### 6.2.1 Phase-B-Ausbau (offen)

- [ ] **B94-Ausbau (Phase B):** Pixelgenaue stratiforme Umgebung entlang des
      Weggefährten-Korridors direkt aus der HSV-Maske.
- [ ] **B95-Ausbau (Phase B):** Zeitlich passenden Atmosphären-Slot je Horizont
      verwenden (statt aktuellem Snapshot), sobald stündliche Snapshot-Historie
      vorgehalten wird.

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
| B16 | `prediction.py`, `object_tracking.py` | Forecast-Einheiten mischen px/Frame mit Minuten (kein Frame-Intervall), zwei unterschiedliche PX_TO_KMH-Werte | ✅ **behoben (P01)** — `PX_TO_KMH` einmalig in `config.py`, Single Source of Truth |
| B17 | `dataset_builder.py`, `prediction.py`, `intensity_regression.py` | `pixel_to_geo(obj["x"], obj["y"])` mit pre-upscale-Koordinaten → falsche Geo-Zuordnung für ML-Features | ✅ **behoben (P02)** — `obj["lat"]`/`obj["lon"]` direkt verwendet statt Neuberechnung |
| B18 | `accuracy_tracker.py` | Pixel-Fehler vergleicht skalierte Forecast-Koords mit pre-upscale Ist-Koords; keine differenzierten Verifikations-Buckets | ✅ **behoben (P03)** — Vergleich durchgängig über `_haversine_km()` auf Geo-Koordinaten |
| B19 | `app.py` | Flask lauscht auf `0.0.0.0:5000` → nginx-Basic-Auth umgehbar | ✅ **behoben (P04)** — Default-Bind `127.0.0.1` (`ADMIN_BIND_HOST`) |
| B20 | `radar_download.py` | `zf.extractall()` ohne Pfadprüfung → Zip-Slip-Risiko | ✅ **behoben (P05)** — `_safe_extract_kmz()` |
| B21 | `tests/test_locations_e2e.py` | `sys.exit()` auf Modulebene bricht pytest-Collection ab | ✅ **behoben (P06)** — `sys.exit()` nur noch innerhalb `__main__`-Funktion |
| B22 | `model_training.py` | Zufälliger Train/Val-Split bei Zeitreihen + Promotion bei <20 Samples / 2 % Toleranz | ✅ **behoben (P07)** — `sklearn.train_test_split` mit `stratify`; weitere Härtung via B242/P58 |
| B23 | `kmz_export.py` | Keine aktuellen Zellen, keine Konturen, keine Location-Hits; Farb-Lookup bricht bei String-Keys | ✅ **behoben (P08)** — `current_objects`/`location_hits`/`contour` im Export |
| B58 | `requirements.txt` | `psutil` fehlt als Runtime-Dependency — CPU-Monitor-Job schreibt kein `cpu_history.jsonl` auf sauberer Installation. Fix: `psutil>=5.9` in `requirements.txt` ergänzt. | ✅ erledigt |
| B59 | `main.py` | `_hit_is_kinematic()`: Current-Hits (Horizont-Key 0 = Zelle JETZT im Radius) wurden durch 2-Frame-Bestätigung verzögert. Fix: Prüfung ob `0 in loc_hit["hits"]` — wenn ja, sofort False zurückgeben (kein Defer). Akutwarnungen erfolgen jetzt in jedem Fall sofort. | ✅ erledigt |
| B60 | `main.py` | Rückgabewert von `send_allclear_email()` ignoriert — `_location_warned` wurde auch bei SMTP-Fehler/Cooldown bedingungslos geleert. Folge: nach gescheiterter Entwarnung keine neue Warnung für denselben Ort. Fix: `ok = send_allclear_email(...)` — `discard()` nur wenn `ok == True`. | ✅ erledigt |
| B61 | `debug_utils.py` | `api_call_summary()` zählte nur `status >= 400` als Fehler. Terminale Retry-Fehler aus `http_retry.py` (status=0) und Records mit `error`-Feld wurden nicht gezählt → Dashboard zeigte 0 Fehler trotz Netzwerkausfällen. Fix: `_status == 0` und `bool(rec.get("error"))` als weitere Fehlerbedingungen; `int(... or 0)` schützt gegen `None`-Status. | ✅ erledigt |
| B92 | **Tendenz-Felder pro Zelle (Backend).** `object_tracking.py` schreibt zusätzlich `size_trend` (-1/0/+1, relative Flächenänderung ggü. Vorframe). `prediction.py` klassifiziert je Zelle `intensity_tendency`/`size_tendency`/`tendency_source`: ML-Regressoren (`delta_core_ratio_pred`/`delta_area_pred`) wenn vorhanden, sonst kinematischer Fallback (`trend`/`size_trend`). Neue Config-Schwellwerte `TENDENCY_CORE_DELTA_STABLE=0.05`, `TENDENCY_AREA_PCT_STABLE=0.10`. Grundlage für Popup-Anzeige (Frontend P-T02). | `config.py`, `object_tracking.py`, `prediction.py` | ✅ erledigt |
| B94 | **Weggefährten-Einfluss als ML-Feature.** Neue `ML_CELL_FEATURES`: `neighbor_count_ahead`, `neighbor_max_core_ahead`, `neighbor_min_dist_km_ahead`, `strat_area_ahead_px`. `object_tracking.py` berechnet sie im zweiten Durchlauf über alle Frame-Zellen (Keil 40 km/±45° in Bewegungsrichtung). Config: `NEIGHBOR_AHEAD_*`. | `config.py`, `object_tracking.py` | ✅ erledigt |
| B95 | **Pfad-Wetter als ML-Feature.** Atmosphärische Werte (CAPE/LI/CIN/Lapse/700-hPa-Wind) an den vorhergesagten Forecast-Positionen, plus `path_cape_trend` (CAPE Ende−Start). Quelle: `atmosphere_latest.json` (kein neuer API-Call, zieldef. Z.28). Berechnung in `prediction.py` NACH Forecast-Setzung, für ML- und Kinematik-Pfad. Config: `PATH_ATM_MAX_DIST_KM`. Feature-Dimension geändert → Neutraining nötig (MODELL-VERSIONEN=0 → kein Verlust). | `config.py`, `prediction.py` | ✅ erledigt |
| P-T06 | **Zell-Überleben bis zum Ort.** `annotate_locations()` unterdrückt Forecast-/Slow-Treffer, wenn eine Zelle laut `intensity_tendency`/`size_tendency` (+ ML `delta_core_ratio_pred`) den Ort voraussichtlich nicht mehr erreicht (exponentieller Zerfall, Halbwertszeit + Mindestfraktion konfigurierbar). current-Hits unberührt. Hits tragen zusätzlich `survival_frac`/Tendenzen. Config: `CELL_DECAY_SUPPRESS_ENABLED`, `CELL_DECAY_HALF_LIFE_MIN`, `CELL_SURVIVAL_MIN_FRAC`. | `config.py`, `locations_check.py`, `tests/test_location_survival.py` | ✅ erledigt |
| B96 | **Fix: numpy-SimpleNamespace-Mock korrumpiert Phase-9-Test-Sammlung.** `tests/test_eumetview_parser.py` setzte `sys.modules.setdefault("numpy", types.SimpleNamespace(...))` auf Modulebene → blieb in sys.modules haften → rasterio und pandas in nachfolgenden Test-Dateien erhielten den Mock statt echtes numpy → 2 Collection-Errors. Fix: numpy-Mock entfernt (cloud_height_from_eumetview.py hat HAS_NUMPY-Guard), `pytest.importorskip("numpy")` ergänzt. Neues `tests/conftest.py` mit `pytest_configure`-Hook schützt sys.modules["numpy"] vor allen künftigen SimpleNamespace-Mocks auf Modulebene. | `tests/conftest.py` (neu), `tests/test_eumetview_parser.py`, `tests/test_severity_dataset_b89.py` | ✅ erledigt |

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
---

### B98/B99 Admin-Panel- und Warnlogik-Erweiterungen ✅

| ID | Änderung | Dateien | Status |
|---|---|---|---|
| B98 | **Einmal-pro-Zelle-Warnung + alle Cooldowns konfigurierbar.** Gewitterwarnung (`send_warning_*`) feuert jetzt einmal pro (Ort, Zell-ID) — `_warned_cells`-Dict in `main.py` trackt bereits gewarntes Zell-ID je Ort; bei Entwarnung geleert. Alle Cooldown-Konstanten aus `email_notifier.py`, `whatsapp_notifier.py` werden über `_get_cooldown()` aus `config.py`/`runtime_config` gelesen (`WARN_COOLDOWN_S`, `ALLCLEAR_COOLDOWN_S`, `DRIFT_ALERT_COOLDOWN_H`, `RISK_ALERT_COOLDOWN_S`). Neue `Configuration.jsx`-Gruppe „Benachrichtigungen & Cooldowns". | `config.py`, `main.py`, `email_notifier.py`, `whatsapp_notifier.py`, `Configuration.jsx` | ✅ erledigt |
| B99 | **Trainingsbereitschaft im Admin-Panel.** `MIN_SEQUENCES_LSTM=50`, `MIN_SEQUENCES_LGBM=30` in `config.py` (ersetzt Hardcoding in `model_training.py`). Neuer API-Endpoint `/api/training_readiness`: liest `dataset.npz`, berechnet fehlende Sequenzen je Modell. `Training.jsx`: neue Readiness-Karte mit Fortschrittsbalken, Modell-Tabelle und Fehlzahl oben auf der Seite. | `config.py`, `model_training.py`, `app.py`, `Training.jsx` | ✅ erledigt |
| B100 | **LSTM Feature-Mismatch → Service-Crash.** `prediction.py:415` warf ungefangene `ValueError` wenn gespeichertes LSTM-Modell weniger Features erwartet als der aktuelle Code liefert (23 vs. 102 nach B94/B95-Erweiterungen). Service crashte bei jeder aktiven Gewitterzelle (restart-counter=4). Fix: Dimension-Check `lstm_model.input_shape[-1]` vor `predict()` + `try/except ValueError` → `has_lstm=False` + kinematischer Fallback für den laufenden Zyklus, kein Crash. Modell bleibt erhalten und wird beim nächsten Training (≥50 Sequenzen) automatisch mit korrekter Dimension neu erstellt. | `prediction.py`, `tests/test_lstm_feature_mismatch.py` | ✅ erledigt |
| B104 | **GeoSphere-Nowcast als Forecast-Endpunkt.** `nowcast-v1-15min-1km` ist ein Forecast-Endpunkt; die B92/B93-Slot-Logik fragte abgeschlossene Vergangenheits-Slots mit `start`/`end` ab → HTTP 400 (Debug-ZIP 2026-06-09), `nowcast_*`-Features blieben 0.0 → Böen-/Starkregenwarnung unterschätzt. Fix: `forecast_offset=0`, kein `start`/`end`; Bulk-`lat_lon`-Wiederholung + Feature-Reihenfolge erhalten; Parser nimmt ersten Zeitschritt; Cache rotiert mit 15-min-Raster (TTL 720 s); 0 Objekte → kein Request. `api_health_check.py` auf gleichen Query-Stil angeglichen. **Ersetzt B92/B93 Slot-Strategie.** Test `test_b92_nowcast_slots_only_include_completed_slots` durch `test_b104_*` ersetzt. | `fetch_geosphere_nowcast.py`, `api_health_check.py`, `tests/test_geosphere_nowcast_b88.py` | ✅ erledigt |
| B105 | `fetch_geosphere_nowcast.py` | GeoSphere Nowcast 400-Fehler (Diagnose + Bbox-Guard). Logs 2026-06-09 zeigen konsistente HTTP 400 für Zellkoordinaten in Grenzbereichen (Steiermark, Kärntner Westgrenze). Fix: (1) 400-Response-Body wird jetzt geloggt (`[NOWCAST] 400-Body: ...`). (2) Koordinaten außerhalb des INCA-Rasters (45.6–49.38°N, 8.2–17.64°E) erhalten Default-Werte ohne API-Call. (3) `fallback_used=False` → `fallback_used=True` korrigiert (Defaults werden tatsächlich verwendet). | ✅ erledigt |
| B105 | **Fix (P0-1): Zellgeschwindigkeit ~3× zu niedrig.** Kalman wird mit `original_cx/cy` gefüttert → `vx/vy` sind Original-px/Frame; `PX_TO_KMH=10` ist km/h pro Original-px/Frame. An 3 Stellen wurde fälschlich durch `UPSCALE_FACTOR` dividiert (`speed_kmh`-Precompute + `_clamp_kalman_velocity` in `object_tracking.py`, Fallbacks in `locations_check.py`/`app.py`) → Speed 1/3 zu niedrig, Slow-/Stationär-Erkennung & Kalman-Clamp verfälscht. Fix: neue Single-Source-Funktion `config.speed_kmh_from_px(vx,vy)` = `hypot*PX_TO_KMH` (kein /UF); Clamp nutzt `PIXEL_TO_KMH=PX_TO_KMH`. Polygon-Vorhersage/`pred_centroids`/`prediction.py` (×UF bzw. px/min) waren korrekt und bleiben unverändert. | `config.py`, `object_tracking.py`, `locations_check.py`, `app.py`, `tests/test_speed_units.py` | ✅ erledigt |
| P1-4 | **Sicherheit: `/api/config` ohne Schlüssel-Validierung.** Der Handler rief `runtime_config.patch(data)` ungeprüft auf → beliebige Schlüssel (inkl. `UPSCALE_FACTOR`, Secrets) konnten nach `runtime_overrides.json` geschrieben werden. `UPSCALE_FACTOR` korrumpiert das Koordinatensystem gespeicherter Objekte; Secrets gehören in `.env`. Fix: Sperrliste + Helper (`is_forbidden_override_key`/`forbidden_keys_in`) in `runtime_config.py`; `patch()` entfernt verbotene Schlüssel defensiv (Defense-in-Depth); `/api/config` lehnt sie mit HTTP 400 ab. | `runtime_config.py`, `app.py`, `tests/test_config_override_guard.py` | ✅ erledigt |
| B106 | **Nested Secrets in Runtime-Overrides (PR #551).** `forbidden_keys_in()` war nur Top-Level – verschachtelte Felder wie `GITHUB_VERIFY_CONFIG.token` konnten persistiert werden. Fix: `_find_forbidden_paths()` rekursiv, liefert vollständige Pfade (z.B. `GITHUB_VERIFY_CONFIG.token`). `/api/config` gibt bei nested-Secret-Payloads HTTP 400 mit Pfadliste zurück. `_SENSITIVE_READ_PREFIXES` um `/api/system_consistency` erweitert (PR #550). | `runtime_config.py`, `app.py` | ✅ erledigt |
| B106 | **install.sh Phase 7d: `\\$host` in nginx-Heredoc bricht mit `host: unbound variable` ab.** Im bash unquotierten Heredoc (`<<NGINXCONF`) expandiert `\\$host` zu `\` + bash-Variable `$host` (nicht gesetzt) → ERR-Trap → Abbruch. Fix: drei Blöcke (`/api/`, `/api/auth/login`, `/api/admin/export`) auf einfachen Backslash umgestellt (`\$host`) — identisch zu den bereits korrekt geschriebenen `/api/logs`-Blöcken. Alte nginx-Config blieb intakt (tee wurde nie aufgerufen). | `install.sh` | ✅ erledigt |
| B107 | **Fix: 8 Phase-9-Testfehler nach P1-1.** (A) `_jwt_auth_check` rief das module-level-gebundene `get_current_user` auf → `monkeypatch("auth.get_current_user")` griff nicht → 401 für alle Tests mit gesichertem GET. Fix: `import auth as _a_mod; _a_mod.get_current_user()` in `_jwt_auth_check`. (B) `test_api_logs_*`-Tests ohne Auth-Mock nach P1-1 ergänzt. (C) `test_clamp_uses_original_px_units` Multiplikator 1.5→1.2 (kaskadierter Delta-Clamp mit 1.5 = korrekt aber Test-Assertion falsch). (D) Phase-9-ERR-Trap: `set+e` deaktiviert nur `errexit`, nicht `trap ERR` → mit `pipefail` bricht Phase 9 trotzdem ab. Fix: `trap '' ERR` vor pytest, `trap on_error ERR` danach. | `app.py`, `tests/test_debug_export.py`, `tests/test_speed_units.py`, `install.sh` | ✅ erledigt |
| B107 | `fetch_outlook_series.py` | Open-Meteo 700-hPa-Windvariablen falsch benannt (PR #445). `windspeed_700hPa` und `winddirection_700hPa` → `wind_speed_700hPa` und `wind_direction_700hPa`. Vorher wurden keine Scherungs-/Höhenwinddaten im Outlook geliefert. Konsistent mit `fetch_700hpa_wind_per_object_slim.py`. | ✅ erledigt |
| B108 | **Design: WhatsApp sendet keine Entwarnungen.** Der bestehende WA-Entwarnung-Block in `main.py` wurde durch eine explizite Design-Kommentar-Zeile ersetzt. `send_allclear_wa()` in `whatsapp_notifier.py` bleibt vorhanden (nicht aufgerufen). | `main.py` | ✅ erledigt |
| B108 | `prediction.py`, `config.py` | path_*-Features Kinematic-First (PR #533). Train/Inference-Skew eliminiert. `_append_kinematic()` setzt kinematische forecast_lat_H/forecast_lon_H, dann `_compute_path_weather()` befüllt path_*-Felder VOR `_build_sequence()`. ML-Inference überschreibt Forecast-Positionen, aber path_* in der Sequenz bleiben deterministisch kinematisch (Train=Inference). Alter B95-Block am Funktionsende entfernt. Neutraining nötig (kein Verlust: keine Modelle vorhanden). | ✅ erledigt |
| B109 | `ir_cell_tracking.py`, `main.py` | IR-Precursor-Flag-Persistenz (PR #388). `update_ir_tracking()` persistierte State bevor Radar-Matching `ir_only_precursor=0.0` setzte. `api_risk_grid()` las veralteten State → radar-gematchte Tracks als IR-Only-Precursor gewertet. Fix: neue Funktion `mark_radar_matched_tracks(matched_ir_ids)` persistiert Match-Status sofort nach Radar-Matching in `main.py`. | ✅ erledigt |
| B110 | LSTM-Trainingsdatei | Keras-Callbacks beim Lazy-Reimport (PR #558). `_build_lstm()` importierte `tensorflow.keras.callbacks` nicht neu → `EarlyStopping`/`ModelCheckpoint` blieben `None` nach fehlgeschlagenem ersten Import. Fix: `_kc = _optional_import("tensorflow.keras.callbacks")` in `_build_lstm()`, Guards in `train_lstm()`. | ✅ erledigt |
| P-M05 | **Stationäres Wachstum als Orts-Treffer.** `locations_check.py` `annotate_locations`: stationäre Zellen (speed < min_speed_kmh) werden nicht mehr nur reaktiv per current-Hit erfasst — bei positiver Wachstumsrate (`_directional_growth_rates`) wird das wachstums-projizierte Polygon (`_forecast_polygon_at_h`, Zentrum ortsfest) gegen den Ortsradius geprüft → neuer Treffertyp `growth_approach` mit Vorwarnung. Warn-Pipeline hit_type-agnostisch → keine `main.py`-Änderung. P-T06-Survival gilt. Config: `LOCATION_GROWTH_APPROACH_ENABLED`, `LOCATION_GROWTH_MIN_RATE_KM_PER_MIN`. | `config.py`, `locations_check.py`, `tests/test_location_growth.py` | ✅ erledigt |
| P-M01 | **Feldbasierter optischer Fluss (Flächenmittel).** `optical_flow_features.py`: `of_vx/of_vy/of_speed/of_divergence` werden über das Zellpolygon (skalierte Kontur) gemittelt statt am Schwerpunkt punktabgetastet; NaN-Flow-Pixel (Merge-Lücken) werden ignoriert. `of_available=0` signalisiert jetzt zuverlässig fehlenden Flow. ETITAN/TRC-Prinzip; robust gegen Merge-Schwerpunktsprünge. Feature-Anzahl unverändert (kein Modell-Gate). | `optical_flow_features.py`, `tests/test_optflow_area_mean.py` | ✅ erledigt |
| P0-2 | **ML-Horizont-Konsistenz End-to-End.** `_build_lstm()` nutzte `len(ML_FORECAST_HORIZONS_MIN)` (compile-time) statt `_get_training_horizons()` (runtime) → LSTM-Output-Dim passte bei Horizon-Override nicht zu LightGBM. `meta["horizons_trained"]`/`meta["horizons"]` speicherte ebenfalls compile-time-Wert → `_check_model_compatibility()` erkannte Runtime-Divergenz nicht. Fix: `_build_lstm(n_horizons)` parametrisch; `train_lstm()` übergibt Runtime-Anzahl; Meta nutzt `_get_training_horizons()`. Wirkt erst beim nächsten Training. | `model_training.py`, `tests/test_p0_2_horizons_consistency.py` | ✅ erledigt |

### B115 – Service-Crash: UnboundLocalError debug_log in update_tracking_memory ✅
- **Symptom:** wetterprojekt.service stürzt im Merge-Pfad ab (≥7×/24h im Export 2026-06-10).
- **Ursache:** funktionslokaler `from debug_utils import debug_log` im B94-except machte
  debug_log für die gesamte Funktion lokal → UnboundLocalError bei früheren Aufrufen.
- **Fix:** lokalen Import entfernt; globaler Modul-Import wird verwendet.
- **Folge:** behebt Mit-Ursache der leeren Karte/Dashboard nach Crash-Neustart.
- **Test:** tests/test_b115_debug_log_scope.py (AST-Scope-Check).

### B101 – `_build_lstm` TypeError bei None-Keras-Klassen (behoben)
- **Datei:** `model_training.py`
- **Problem:** `_build_lstm()` rief `LSTM(64, ...)` auf ohne zu prüfen ob
  `LSTM` (Modul-Level-Variable) noch `None` ist. Das passiert wenn TF beim
  Modul-Import nicht verfügbar war (Pytest-Collection-Reihenfolge).
- **Fix:** Lazy-Re-Import der Keras-Klassen am Anfang von `_build_lstm()`
  via `global`-Deklaration + `_optional_import()`. Klarer `RuntimeError`
  statt kryptischem `TypeError` wenn TF wirklich fehlt.
- **Tests:** `tests/test_p0_2_horizons_consistency.py` — alle 2 betroffenen
  Tests jetzt PASSED (TF installiert) oder SKIPPED (TF fehlt).

### B102 – `test_p2_1_radar_hash_dedup` AttributeError namespace (behoben)
- **Datei:** `tests/test_p2_1_radar_hash_dedup.py`
- **Problem:** `monkeypatch.setattr(rd.requests, "get", ...)` schlug fehl
  mit `AttributeError: namespace() has no attribute 'get'`, weil
  `rd.requests` je nach Test-Reihenfolge ein `types.SimpleNamespace`
  (ohne `.get`) war statt das echte `requests`-Modul.
- **Fix:** `requests` wird als ganzer Namespace im `radar_download`-Modul
  ersetzt (`monkeypatch.setattr(rd, "requests", mock_ns)`).
  Zusätzlich wird `radar_download` vor jedem Test aus `sys.modules`
  entfernt (`monkeypatch.delitem`) damit kein gecachtes Modul verwendet
  wird. Hilfsfunktion `_make_requests_mock()` zentralisiert Mock-Erstellung.
- **Tests:** `tests/test_p2_1_radar_hash_dedup.py` — alle 3 Tests PASSED.
| B111 | `Logs.jsx` | Nginx-Logs in UI sichtbar (PR #544). Feste Tab-Liste durch dynamische Generierung ersetzt. `nginx_error` und `nginx_access` erscheinen als Tabs wenn das Backend sie liefert. | ✅ erledigt |
| B112 | `MapView.jsx`, `MapFullscreen.jsx` | first_seen Timestamp-Parsing (PR #524). `new Date(ts + 'Z')` erzeugte falsche UTC-Interpretation der Vienna-Lokalzeit (Fehler bis -2h). Neue Funktion `parseViennaLocalTimestamp()` parst ohne Z-Suffix. | ✅ erledigt |

| B113 | `MapView.jsx`, `MapFullscreen.jsx` | IR-Tooltip-Label (PR #375). `CB > 10.000` nur wenn `cloud_height_m >= 10000`, sonst `IR-Vorläufer`. Fix in MapView und MapFullscreen. | ✅ erledigt |
| B114 | AI-Report-E-Mail-Datei | HTML-Escaping im AI-Report (PR #182). LLM-generierte Felder (title, description, action, priority) werden mit `html.escape()` bereinigt bevor HTML-Einbettung. | ✅ erledigt |

### B116 – GeoSphere-Nowcast HTTP 400: Parameter 'ffx' entfernt ✅
- **Symptom:** 93/95 API-Fehler im Export 2026-06-10 = geosphere_nowcast HTTP 400.
- **Ursache:** nowcast-v1-15min-1km liefert kein 'ffx'. 400-Body:
  {"detail":"Parameters {'ffx'} do not exist or access is denied"}.
- **Fix:** Nowcast-Request nur noch rr+ff. nowcast_ffx_kmh=0.0 (Feld bleibt).
  Böen weiterhin aus TAWES/AROME; Severity-Dataset ignoriert nowcast_ffx_kmh als Böenquelle.
  api_health_check + B88-Test angepasst.
- **Test:** test_b116_no_ffx_parameter, test_b116_bulk_url_has_no_ffx,
  test_b116_gust_kmh_ignores_nowcast_ffx_field.

### B117 – Track-Kontinuität: Merge-ID-Stabilität + akkumulierter Zustand ✅
- **Symptom:** history/active_frames immer 1, first_seen jeden Frame neu,
  gemergte Zellen erhalten jeden Frame neue ID → KEINE Trainings-Sequenzen.
- **Ursache A:** akkumulierte Felder wurden nur auf obj_clean (Kopie) gesetzt,
  nicht in tracking_memory zurückgeschrieben.
- **Ursache B:** Merge mintete bedingungslos generate_id() → endlose Neuvergabe.
- **Fix A:** history/first_seen/active_frames/total_active_frames werden in
  tracking_memory[obj_id] persistiert.
- **Fix B:** Merge-Zelle erbt ID des dominanten Parents (größter Overlap) und
  führt dessen Kalman/History fort; übrige Parents werden korrekt beendet.
- **Test:** tests/test_b117_track_continuity.py.

- **B118 — Merged-Zellen auf der Karte hervorgehoben** (`MapView.jsx`, `MapFullscreen.jsx`):
  Neue Helfer-Funktion `cellStroke(lineage)` differenziert die Rand-Strichstärke
  je Lineage. Bisher hatten alle Zellen `weight: 2` und nur eine andere Randfarbe,
  wodurch gemergte Zellen kaum erkennbar waren. Jetzt: merged → weight 4 +
  dashArray '10,6' (auffällig gestrichelt), split → weight 3 + '4,4',
  new/continued → weight 2 durchgezogen. MapView erhält zusätzlich eine
  Zelltyp-Legende. MapFullscreen nur visuelle Differenzierung (kein Inline-Legenden-Balken).
  Benutzersichtbares Feature → Benutzerhandbuch v2.5 aktualisiert.

- **B119 — `max_tokens` False Positive: KI-Analyse-Einstellungen still verworfen**
  (`runtime_config.py`, `app.py`, `daily_analyzer.py`, `export_security.py`,
  `tests/test_config_override_guard.py`):
  `max_tokens` enthält den Substring `TOKEN` → wurde an 4 Stellen fälschlich als
  Secret eingestuft. Kritischste Folge: `patch({"AI_ANALYSIS_CONFIG": {…}})` erkannte
  `AI_ANALYSIS_CONFIG.max_tokens` als verbotenen Pfad, strich das gesamte Dict still
  aus `partial` und speicherte nichts — Endpoint gab trotzdem `200 OK` zurück.
  Admin sah nach Reload die alten Werte. Nebeneffekt: Admin-Konfigurationsseite und
  KI-Analyse-Report zeigten `max_tokens: "***REDACTED***"`.
  Fix: `_FORBIDDEN_KEY_ALLOWLIST` / `_REDACT_KEYS_EXCEPTIONS` / `_SECRET_KEY_EXCEPTIONS` /
  `_SENSITIVE_KEY_ALLOWLIST` mit `MAX_TOKENS` + `MAX_TOKENS_PER_CHUNK`.
  Echte Secrets (GITHUB_TOKEN, token, UPSCALE_FACTOR) weiterhin korrekt gesperrt.
  Kein benutzersichtbares Feature → kein Handbuch-Update.
  Test: 4 neue B119-Tests in `tests/test_config_override_guard.py`.

- **B120 — Korrektur `test_b117_track_continuity.py`** (`tests/test_b117_track_continuity.py`):
  Testfehler durch falsche Return-Type-Annahme: `update_tracking_memory()` gibt eine
  einfache `list` zurück (nicht 2-Tuple). Das 2-Tuple-Entpacken `objs, _ = ...` brach
  bei 0 oder 1 erkannten Zellen. Zusätzlich fehlten alle nötigen Mocks (`pixel_to_geo`,
  `calculate_core_ratio`, `get_dem_features`, `get_valley_features`,
  `compute_stratiform_environment`) — ohne diese filterte der Bbox-Check alle
  Testzellen heraus. Testfile vollständig neu erstellt nach dem Muster aus
  `test_object_tracking_regression.py`. Die B117-Logik in `object_tracking.py`
  war korrekt und bleibt unverändert. Kein Benutzerhandbuch-Update.

### P-T08 – Per-Horizont-Maskierung, partielle Abdeckung & Radaralter ✅
- **Problem:** `build_dataset()` verlangte, dass eine Zelle bei ALLEN Horizonten
  (+10…+60) existiert (`if any(oid not in fmap ...): continue`). Zellen die < ~80 min
  leben lieferten 0 Samples. Forecast verlangte ebenfalls alle LGBM-Modelle
  (`has_lgbm = all(...)`).
- **Fix Dataset:** Per-Horizont-Maskierung mit `NaN`. Sample gültig sobald ≥1
  Horizont vorhanden. `scaler_y` NaN-bewusst gefittet (`np.nanmean/nanstd`).
  `validate_sample` NaN-tolerant; Jump-Check übersprungen wenn +30 maskiert.
- **Fix Training:** `train_lgbm` filtert pro (Horizont,Achse) die NaN-Zeilen und
  trainiert nur ab `MIN_SEQUENCES_LGBM_PER_HORIZON` (=15) gültigen Samples →
  +10/+20 zuerst. LSTM nutzt `_masked_mse` (ignoriert NaN-Ziele); `load_lstm` und
  Holdout-Eval laden mit `compile=False`. Holdout-MAE auf `np.nanmean`.
- **Fix Forecast:** `has_lgbm` all→any; `_predict_lgbm_vector` liefert NaN für
  fehlende Horizonte; Forecast mischt pro Horizont ML (Modell vorhanden) und
  kinematischen Fallback (aus `_temp_fc`). Jeder Forecast wird mit `radar_age_min`,
  `effective_lead_min` (= Horizont − Radaralter) und `stale` annotiert.
- **Priorität:** präzise +10/+20-Vorhersage (kürzeste Horizonte erreichen die
  Datenmenge zuerst). Erfüllt `zieldefinition.txt` Z.5/6 (ML wenn vorhanden,
  sonst kinematisch).
- **Dateien:** `config.py`, `dataset_builder.py`, `data_quality.py`,
  `model_training.py`, `prediction.py`, `tests/test_pt08_partial_horizon.py`
- **Hinweis:** Neutraining erforderlich (Dataset-Format/Scaler geändert).

### B122 – Echte Radar-Valid-Time aus KML `<TimeStamp>` ✅
- **Problem:** `get_acquisition_timestamp()` nutzte HTTP `Last-Modified`
  (Publikationszeit auf dem ARSO-Server) als Aufnahmezeit (B40/B41). Diese läuft
  der echten Radar-Messung um Minuten nach → leicht verschobene Sequenz-Zeitabstände
  (ML/Kinematik) und überschätztes P-T09-Radaralter.
- **Quelle verifiziert** an echter `latest.kml`: `<TimeStamp><when>2026-06-11T05:15:00Z`
  und PNG-Name `inca_si0zm_20260611-0515+0000.png` → beide = `2026-06-11_07-15-00`
  (07:15 CEST).
- **Fix:** Neue Quellen-Priorität in `get_acquisition_timestamp()`:
  (1) KML `<TimeStamp><when>` (ISO-UTC, Primärquelle),
  (2) PNG-Dateiname-Pattern (Fallback),
  (3) HTTP Last-Modified (bisheriges Verhalten, letzter Fallback).
  Neue Helfer `_acq_from_kml_timestamp`, `_acq_from_kml_pngname`,
  `_acq_from_last_modified`; Konstante `_LATEST_KML_FILE`.
- **Wirkung:** genauere Zeitbasis für ML-Sequenzen, Kinematik-Δt, Objekt-Dateinamen
  und P-T09-Radaralter. Erfüllt `zieldefinition.txt` (Erfassungszeitpunkt) präziser.
- **Dateien:** `radar_download.py`, `object_tracking.py` (Log-Text),
  `tests/test_b122_kml_valid_time.py`

| B123 | **`test_debug_export.py`: Auth-Mock patcht nur `app.get_current_user` — 8 Tests scheitern mit 401.** `_auth(monkeypatch)` setzte nur `app.get_current_user`; der `before_request`-Hook prüft jedoch `auth.get_current_user()` (B107-Modul-Referenz). Da `/api/admin/` in `_SENSITIVE_READ_PREFIXES` liegt, liefert `before_request` 401 bevor die Route erreicht wird. Fix: `_auth()` patcht zusätzlich `auth.get_current_user`; `test_export_requires_admin_returns_401_for_unauthenticated` desgleichen mit `None`. Produktionscode unverändert. | `tests/test_debug_export.py` | ✅ erledigt |
| B124 | **`fetch_outlook_series.py`: Budget-Guard nur im äußeren Batch-Loop → 4 statt 3 Requests bei `MAX_REQUESTS_PER_RUN=3`.** Innerer `for hourly in (_HOURLY_FULL, _HOURLY_MIN):`-Loop prüfte Budget nicht vor dem zweiten Fallback-Versuch. Batch 2 konnte beide Versuche (FULL+MIN) machen, auch wenn das Budget nach Versuch 1 erschöpft war. Fix: `if requests_used >= MAX_REQUESTS_PER_RUN: break` am Anfang des inneren Loops. | `fetch_outlook_series.py` | ✅ erledigt |

### P-T09 – Veraltete Radardaten in der Warnlogik ✅
- **Problem:** P-T08 berechnete `stale`/`effective_lead_min` pro Forecast, die
  Warnlogik (`main.py`/`locations_check.py`) nutzte sie nicht. Forecast-Warnungen
  aus veralteten Radarbildern (ARSO-Lücken) wurden wie frische behandelt.
- **Schwelle (Betreiber-Wahl, Option 1):** Forecast gilt als veraltet sobald
  `radar_age_min ≥ horizon` (`effective_lead_min ≤ 0`).
- **Fix:** `main.py` schreibt `radar_age_min` auf ALLE Objekte (unabhängig vom
  ML-Status → wirkt auch im kinematischen Betrieb). `annotate_locations` annotiert
  jeden Forecast-/Slow-Treffer mit `radar_age_min`, `effective_lead_min`, `stale`.
  Stale-Treffer umgehen die 2-Frame-Verzögerung (`_hit_is_kinematic` → wie current).
  E-Mail und WhatsApp erhalten den Hinweis „Radardaten N min alt — Position unsicher".
- **Bewusst:** Warnung wird NICHT unterdrückt (veraltetes Bild ≠ keine Gefahr),
  nur gekennzeichnet. P-T06-Überlebensprüfung bleibt unverändert.
- **Dateien:** `main.py`, `locations_check.py`, `email_notifier.py`,
  `whatsapp_notifier.py`, `tests/test_pt09_stale_warning.py`

### B115 — Claude-Code-Report-Mail: Eigene Config + Admin-Panel + git fetch (2026-06-11) ✅

**Problem:** `analysis_result.json` (Claude-Code-Routine, Branch `debug-export-latest`)
wurde nie per E-Mail versendet. Früherer Ansatz (B115/B115b) integrierte das Feature
fälschlicherweise in `AI_ANALYSIS_CONFIG` — Ausführung war nicht unabhängig.

**Lösung:**
- Eigene `CLAUDE_CODE_REPORT_CONFIG` Dict in `config.py` (enabled, cron_hour/minute,
  branch, report_email) — vollständig unabhängig von `AI_ANALYSIS_CONFIG`
- Eigene API-Endpoints `GET/POST /api/claude_code_report/config` in `app.py`
- APScheduler-Job `claude_code_report` liest ausschließlich `CLAUDE_CODE_REPORT_CONFIG`
- Abruf via `git fetch` + `git show origin/branch:file` (SSH, kein extra Token,
  kein Branch-Wechsel im Arbeitsverzeichnis)
- Neue `send_claude_code_report_email()` in `email_notifier.py` für das
  Claude-Code-Format (fehler/loesungen/verbesserungen/prompts/zusammenfassung)
- Eigene Konfigurationskarte in `AiSuggestions.jsx` mit eigenem State + Save-Button
- Guards: enabled=False / email leer / fetch-Fehler / Datei >26h → nur Log

**Berührte Dateien:** `config.py`, `email_notifier.py`, `app.py`, `scheduler.py`,
`frontend/src/pages/AiSuggestions.jsx`, `tests/test_claude_code_report_mail.py`

**Testen:** `python3 -m pytest tests/test_claude_code_report_mail.py -v`

## Langzeitstatistik (P-S-Serie)

Jahresstatistik erkannter Zellen (Häufigkeit, Lebensdauer, zirkuläre Zugrichtung,
Intensität) inkl. ML-Klimatologie-Features. Datenbasis: train_data/evaluation/track_ends.jsonl.

| # | Task | Datei(en) | Status |
|---|------|-----------|--------|
| P-S01 | Track-Lifecycle-Log: write_track_end an 3 Todespfaden (dissolved/left_bbox/merge/service_restart), inkrementelle zirkuläre Richtungs-/Pfad-/Speed-Akkumulation am Track, Schwere-Maxima-Write-back aus main.py | `track_statistics.py` (neu), `object_tracking.py`, `main.py`, `config.py` | ✅ erledigt |
| P-S02 | stats_aggregator.py (Jahres-Aggregate + zirkuläre Jahresrichtung + 16-Sektor-Windrose + Lebensdauer-/Speed-Histogramme), climatology_grid.json (Gitterzelle×Monat, CLIM_MIN_SAMPLES-Gate), backfill_track_ends.py (Rekonstruktion aus cells_log.jsonl), Scheduler-Job stats_aggregate (nächtlich), install.sh Full/Upgrade-Schutz + Phase-9-Backfill | `stats_aggregator.py` (neu), `backfill_track_ends.py` (neu), `scheduler.py`, `config.py`, `install.sh` | ✅ erledigt |
| P-S03 | Statistik-API: GET /api/statistics/years, /api/statistics/<year>, /api/statistics/climatology (öffentlich/viewer, reines Datei-Lesen, kein externer Call) | `app.py` | ✅ erledigt |
| P-S04 | Frontend-Seite Statistik.jsx (Route /statistik, Menü 📊 Langzeitstatistik): Monats-/Tages-/Intensitätsverlauf, 7-Tage-Mittel, Vorjahresvergleich, kumulierte Kurve, Windrose, Lebensdauer-Histogramm, Tagesgang, Mehrjahres-Trend | `frontend/src/pages/Statistik.jsx` (neu), `frontend/src/App.jsx`, `frontend/src/components/Layout.jsx` | ✅ erledigt |
| P-S05 | ML-Features cell_age_min (physisches Alter) + Klimatologie-Prior (clim_cell_freq/dir_cos/dir_sin/mean_lifetime_min) aus climatology_grid.json. CLIM_MIN_SAMPLES-Gate (unzuverlässig→0.0, B95-Pattern), CLIM_FEATURES_ENABLED-Toggle. Anreicherung in main.py vor predict_positions (B108-Konsistenz). B100-Guard deckt Retrain-Übergang ab. Erfordert Dataset-Rebuild + Retrain auf Maschine mit LOCAL_TRAINING=True (derzeit Pi; externer Trainer noch nicht vorhanden). | `config.py`, `climatology_features.py` (neu), `main.py` | ✅ erledigt |
| P-S06 | Zusatzstatistik: mean_lifetime_by_intensity (Backend), Frontend-Anzeige von Geschwindigkeitsverteilung, Lebensdauer nach Intensität und Tracking-Kennzahlen (Merges/Splits/stationäre Zellen). Keine Gebiets-Karten. | `stats_aggregator.py`, `frontend/src/pages/Statistik.jsx`, `tests/test_stats_lifetime_intensity.py` (neu) | ✅ erledigt |

## B125 – Cache-Status: exakte nächste Abrufzeit statt „jetzt"
Status: ERLEDIGT
Ursache: Spalte „Nächster Abruf in" zeigte bei STALE hartkodiert „jetzt" — keine konkrete Zeit.
Fix: /api/cache_status liefert next_fetch_ts (letzter Abruf + TTL, UTC-ISO). Logs.jsx und
     Dashboard.jsx zeigen absolute lokale Uhrzeit; überfällige Einträge als „(fällig)".
Dateien: app.py, frontend/src/pages/Logs.jsx, frontend/src/pages/Dashboard.jsx,
         tests/test_cache_status_next_fetch.py (neu)


## P47 – Externe Service-Aufrufe manuell auslösen
Status: ERLEDIGT
Neu: POST /api/system/run_job/<job_id> (admin) startet Fetch/Job im Hintergrund-Thread;
     GET /api/system/job_status liefert Lauf-Status. Jobs: atmospheric_snapshot,
     outlook_series(force), outlook_compute, api_health (alle Dienste testen),
     stats_aggregate. Frontend: Karte „Externe Dienste manuell auslösen" auf der Logs-Seite.
Dateien: app.py, frontend/src/pages/Logs.jsx, tests/test_manual_job_trigger.py (neu)

## B127 – Open-Meteo-Outlook: kein MIN-Retry bei Verbindungsfehler, früher Circuit-Stopp
Status: ERLEDIGT
Ursache: Bei ConnectionError/SSLError/Timeout probierte der innere Loop zusätzlich die
         MIN-hourly-Variante (sinnvoll nur bei HTTP-400) und der Circuit wurde nur am
         Batch-Anfang geprüft → bis ~27 Fehlerereignisse gegen einen toten Host.
Fix: Timeout/SSL/Conn brechen den Variant-Loop ab (kein MIN-Retry); danach Circuit prüfen
     und bei offenem Circuit sofort Fallback. "all-param-sets-failed" nur noch bei echten
     HTTP-/Parameterfehlern. Optional CIRCUIT_THRESHOLD_CONN via Env senkbar.
Dateien: fetch_outlook_series.py, tests/test_outlook_conn_break.py (neu)

## B128 – Dashboard API-Requests zeigt alle externen Dienste
Status: ERLEDIGT
Ursache: /api/api_calls lieferte nur Dienste mit Log-Einträgen → Dashboard zeigte nur die
         zufällig aufgerufenen (z.B. arso_radar, geosphere_nowcast).
Fix: Modul-Konstante _KNOWN_EXTERNAL_SERVICES (= cache_status _DEFAULT_TTLS-Namen);
     api_api_calls ergänzt fehlende Dienste mit Null-Werten. Frontend unverändert.
Dateien: app.py, tests/test_api_calls_all_services.py (neu)

## B131 – GeoSphere-Nowcast: Out-of-Coverage-Gedächtnis + konsistente Fehler-Protokollierung
Status: ERLEDIGT
Ursache: Punkt 47.128,15.055 liegt innerhalb der groben B105-Bbox, aber außerhalb des
         1km-INCA-Punktrasters → liefert jeden Zyklus HTTP 400 (unnötiger Request).
         Zudem loggte der Einzel-Fallback einseitig → Dashboard (Zähler) zeigte einen
         Fehler, „API-Fehler" (api_health.jsonl) blieb leer (Label-/Logpfad-Inkonsistenz).
Fix: (1) Out-of-Coverage-Gedächtnis (train_data/evaluation/nowcast_out_of_coverage.json):
     4xx-Koordinaten werden gemerkt und für 24 h nicht erneut angefragt (TTL-Re-Test;
     erfolgreicher Abruf hebt die Markierung auf). (2) Einzel-Fallback ruft bei 4xx
     log_api_failure UND log_api_call unter identischem Service-Namen → beide Sichten
     stimmen überein. Nur echte HTTP-4xx markieren; Timeout/Connection/5xx bleiben transient.
Dateien: fetch_geosphere_nowcast.py, tests/test_nowcast_out_of_coverage_b131.py (neu)
Hinweis: Die produzierten 09:30-Logs stammten von einer älteren laufenden Prozessversion
         (Fossil: ungenutzter log_http_response-Import). Nach Anwendung Services neu starten.


## LOGIC-01 – Verfahrensdokumentation mit Quellen

| # | Task | Datei(en) | Status |
|---|------|-----------|--------|
| LOGIC-01 | **`logic.md` mit Quellen angelegt.** Verfahrensdoku (Kalman, Tracking/Merge/Split, optischer Fluss/TRT/ETITAN, Forecast-Geschwindigkeitsquelle, Tendenz P-M03, Orts-Treffer inkl. P-M05, Survival/Stale, ML inkl. P-M04) jeweils mit Quell-Weblink (Originalpublikation/Doku) und Hinweis auf die operationell einsetzende Organisation (NCAR, MeteoSwiss, FMI, Hong Kong Observatory, DeepMind/Met Office, Microsoft). Kein Produktionscode. | `logic.md` | ✅ erledigt |

## B132 – api_cache: Refetch bei TTL-Ablauf statt 24h-Stale-Auslieferung
Status: ERLEDIGT
Ursache: cache_get() rief im EXPIRED-Zweig cache_get_stale() (max_stale=86400s) auf und
         lieferte den veralteten Wert statt None. Caller-Muster `if data is None: fetch`
         löste daher nie einen Refetch aus → Blitz (TTL 60s)/TAWES (600s)/CAPE/EUMETView
         wurden faktisch nur 1×/24h real geladen (Beleg: api_call_counts.jsonl, letzter
         echter Call 2026-06-13 09:39; Hauptlog-Muster EXPIRED→STALE HIT). Bei Gewitter
         wären Blitz-/Stationsdaten bis ~24h alt = funktional unbrauchbar.
Fix: cache_get() gibt bei TTL-Ablauf wieder None zurück. Der Stale-While-Error-Fallback
     (cache_get_stale) bleibt unverändert und dient ausschließlich im except-Zweig der
     Caller. cache_get_stale/cache_set/_put_mem/get_ttl unverändert.
Dateien: api_cache.py, tests/test_b132_cache_refetch_on_expiry.py (neu)

## B133 – Kanonische Service-Namen: Logger == Cache-Namespace == Registry
Status: ERLEDIGT
Ursache: Logger schrieb api_call_counts.jsonl unter blitzortung/geosphere_tawes/
         eumetview_wms_caps, während Cache-Namespace + _KNOWN_EXTERNAL_SERVICES die
         kanonischen Namen blitzortung_last_strikes/geosphere_tawes_all/
         eumetview_capabilities nutzten → Dashboard zeigte diese Dienste dauerhaft mit
         0 Anfragen und ohne „Frühester nächster Abruf" (fehlgeschlagener Namespace-Join).
         Zusätzlich tote Registry-Namen open_meteo_outlook (real: openmeteo_outlook) und
         open_meteo_atmosphere (real: 15x open_meteo_atmosphere_<modell>_b<n>).
Fix: Logger-Namen in blitz_api.py/fetch_tawes_gust.py/cloud_height_from_eumetview.py an die
     Cache-Namespaces angeglichen; config.API_CACHE_TTL_SECONDS-Keys kanonisiert;
     _KNOWN_EXTERNAL_SERVICES bereinigt (openmeteo_outlook statt open_meteo_outlook,
     open_meteo_atmosphere entfernt, eumetview_wms-TIFF aufgenommen) + _DEFAULT_TTLS um
     eumetview_wms (900s) ergänzt. Cache-Keys + retry_get-Labels unverändert.
     Ergänzt B132 (reale Requests) für korrekte Dashboard-Zähler.
Dateien: blitz_api.py, fetch_tawes_gust.py, cloud_height_from_eumetview.py, config.py,
         app.py, tests/test_b133_canonical_service_names.py (neu)

## B134 – „Frühester nächster Abruf": Datum + Uhrzeit statt nur Uhrzeit
Status: ERLEDIGT
Ursache: Logs.jsx (CacheStatusTable) und Dashboard.jsx (API-Requests-Tabelle) formatierten
         next_fetch_ts mit toLocaleTimeString (nur Uhrzeit). Backend /api/cache_status
         liefert seit B125 die volle UTC-ISO-Zeit inkl. Datum → reiner Frontend-Verlust.
Fix: toLocaleTimeString → toLocaleString mit {day,month,year,hour,minute,second} (de-AT),
     analog zur bereits korrekten Spalte „Letzter Abruf". overdue/(fällig)-Logik unverändert.
Dateien: frontend/src/pages/Logs.jsx, frontend/src/pages/Dashboard.jsx
         (Validierung: tests/test_frontend_build.py)


### B140 — Debug-Export: 50-MB-Byte-Hartgrenze entfernt + Temp-File-Leak ✅ erledigt
- `EXPORT_MAX_BYTES` / `DEBUG_EXPORT_MAX_BYTES` und beide `max_total_bytes`-Abbruchzweige
  in `create_debug_export_zip` entfernt. Es existiert KEINE Byte-Gesamtgrenze mehr;
  maßgeblich ist ausschließlich die komprimierte Volume-Größe (`EXPORT_VOLUME_MAX_BYTES`, B128).
- `ExportLimitExceeded` bleibt für den `max_files`-Schutz erhalten.
- `create_debug_export_volumes`: angelegte Temp-Datei (`wetterextended_full_*.zip`) wird bei
  Fehler im Vollexport zuverlässig entfernt (kein Leak mehr).
- Obsoleten Test `test_export_limit_exceeded_returns_413` entfernt (testete das durch B126
  abgelöste 413-Verhalten). `test_temp_file_cleaned_up_after_error` ist nun grün.
- Dateien: `debug_export.py`, `tests/test_debug_export.py`

### B141 — Publisher-Tests: create_export-Mock 2-Tupel + Oversized-Volume-Reject ✅ erledigt
- `test_debug_export_branch_publisher.py`: beide `create_export`-Mocks lieferten ein
  veraltetes 3-Tupel `(zip_path, name, manifest)` → `ValueError: too many values to unpack`.
  Korrigiert auf das reale 2-Tupel `([(Path, name)], manifest)`.
- `publish()`: Volumes > `--max-zip-mb` werden jetzt mit `PublisherError`
  („Finale ZIP-Datei ist zu groß für GitHub“) abgelehnt statt nur geloggt — GitHub kann
  nicht-pushbare Übergrößen-Dateien nicht annehmen. Admin-Download bleibt verlustfrei.
- Dateien: `tests/test_debug_export_branch_publisher.py`, `tools/publish_latest_debug_export_branch.py`

### B142 — Debug-Export: 24h-Fenster zeitzonensicher + keine Datenkürzung ✅ erledigt
- KIAnalyse #3/#4 + Vorgabe „alle 24h-Daten an die KI, nichts kürzen".
- (1) `_file_in_window` zeitzonensicher über `st_mtime` (UTC) — Vienna-lokale Namen (B122)
  wurden als UTC (+2 h CEST) fehlinterpretiert, jüngste radar/objects fielen aus dem Fenster.
- (2) Obsoletes B115-Pruning (nur 3 neueste Dateien je train_data-Unterverzeichnis)
  ERSATZLOS entfernt — es kürzte radar/objects UND Wetterdaten (weather/cape/arome/
  external_responses) auf 3 Snapshots. Einzige Grenze ist jetzt das 24h-Fenster; Größe via
  Volume-Split (B128).
- (3) `max_files` 5000 → 50000 (24h-Fenster ist die Grenze, nicht die Dateianzahl).
- Test: `tests/test_b142_export_window_tz.py`. Dateien: `debug_export.py`.

### B143 — evaluation-JSONL Alters-Rotation (api_call_counts.jsonl) ✅ erledigt
- KIAnalyse #1/#2: `api_call_counts.jsonl` wuchs unbegrenzt (volle CAPE/eumetview-Bodies,
  86 MB), da `train_data/evaluation/` von der Rotation ausgenommen ist.
- Fix: `cleanup_old_data()` ruft täglich `_prune_eval_jsonl_by_age()` für
  `api_call_counts.jsonl` + `api_health.jsonl` auf — Zeilen älter als
  `EVAL_LOG_RETENTION_HOURS` (Default 48 h) werden verworfen. Nicht parsebare Zeilen bleiben.
- Bewusst 48 h > 24h-Export-Fenster → der 24h-Export behält IMMER alle Daten. Der Export
  filtert API-Log-Zeilen ohnehin selbst auf das Fenster; A7-Volltext-Bodies bleiben.
- Konfig: `config.EVAL_LOG_RETENTION_HOURS`. Test: `tests/test_b143_eval_log_rollover.py`.
- Dateien: `config.py`, `cleanup_old_data.py`.


### B144 — Circuit-Breaker: cooldown auf Wall-Clock (stuck-open nach Reboot) ✅ erledigt
- Symptom: alle openmeteo_*-Dienste seit ~02:09 "fällig"/leer; atmospheric_snapshot
  durch `is_open("open_meteo_atmosphere")` dauerhaft übersprungen.
- Ursache: `_now()` = `time.monotonic()`. `cooldown_until` wird persistiert und nach
  Reboot mit dem neuen (resetteten) monotonic verglichen → Breaker bleibt dauerhaft offen.
- Fix: `_now()` → `time.time()` (Wall-Clock, reboot-stabil). Bestehende stuck-open-Zustände
  heilen sich beim ersten `is_open()` selbst.
- Test: `tests/test_b144_circuit_walltime.py`. Datei: `api_circuit_breaker.py`.


### B145 — systemd-Services self-healing (StartLimitIntervalSec=0) ✅ erledigt
- Symptom: Scheduler 02:09 → 08:01 dauerhaft tot; erst manueller Eingriff (Install) brachte
  ihn um 08:01 zurück. Ursache NICHT der Circuit-Breaker (B144, open:false) und kein Reboot.
- Ursache: Unit-Files mit `StartLimitIntervalSec=120` + `StartLimitBurst=3`. Mehrere Crashes
  in 120 s (z. B. Scheduler-OOM bei convlstm_weekly, vgl. B147) → systemd lässt die Unit
  dauerhaft `failed`, kein Auto-Restart mehr bis `reset-failed`.
- Fix: `StartLimitIntervalSec=0` (Rate-Begrenzung aus) in allen drei Units →
  `wetterprojekt`, `wetterprojekt-scheduler`, `wetterprojekt-admin`. systemd startet nach
  jedem Absturz erneut (Backoff `RestartSec=30`). `Restart=on-failure` deckt OOM-SIGKILL ab.
- Zusammen mit B146 (Misfire-Nachholung) und B147 (ConvLSTM isoliert) vollständige
  Scheduler-Robustheit.
- Test: `tests/test_b145_service_restart_policy.py`. Dateien: die drei `.service`-Files.

### B146 — Scheduler: verpasste Cron-Jobs nach Downtime nachholen ✅ erledigt
- Symptom-Kontext: „Lernfortschritt" leer, weil `retrain_nightly` (03:00) während des
  Scheduler-Stillstands (B145) nicht lief und der verpasste Cron-Lauf (APScheduler-Default
  misfire_grace_time=1 s) übersprungen wurde.
- Fix: `create_scheduler()` setzt `job_defaults={"coalesce": True, "misfire_grace_time":
  SCHEDULER_MISFIRE_GRACE_S}` (Default 1 h). Nach kurzer Downtime (B145 self-healing) holt
  der Scheduler einen knapp verpassten Lauf nach statt einen Tag zu warten.
- Konfig: `config.SCHEDULER_MISFIRE_GRACE_S`. Test: `tests/test_b146_scheduler_misfire.py`.
- Dateien: `config.py`, `scheduler.py`.

### B147 — ConvLSTM-Training: Streaming + Subprozess-Isolation ✅ erledigt
- Ursache der Montag-02:00-Einfrierung: `convlstm_weekly` rief `train_convlstm()`
  IN-PROCESS auf; `_load_radar_dataset()` lud das gesamte Radar-Archiv als ein großes
  Array → OOM-SIGKILL des Scheduler-Prozesses (mit B145-StartLimit → Dienst blieb tot).
- Fix 1 (Streaming): `train_convlstm()` nutzt `tf.keras.utils.Sequence` (pro Batch nur
  benötigte Frames von Platte; Peak-RAM ≈ batch_size × SEQUENCE_LENGTH). ALLE gecappten
  Frames werden je Epoche gesehen → kein Qualitätsverlust. Chronologischer Train/Val-Split
  statt `validation_split`. Sicherheits-Ceiling `CONVLSTM_MAX_FRAMES` (Default 6000).
- Fix 2 (Isolation): Scheduler startet `python3 radar_convlstm.py --train` als Subprozess
  mit `RLIMIT_AS` (`CONVLSTM_TRAIN_MEM_LIMIT_GB`, Default 12 GB) und Timeout
  (`CONVLSTM_TRAIN_TIMEOUT_S`). Kind-Crash/OOM beendet nur das Kind; Scheduler überlebt.
- Training läuft bewusst weiter lokal auf dem Pi. Ergänzt B145 (systemd self-healing) und
  B146 (misfire-grace) zur vollständigen Scheduler-Robustheit.
- Konfig: `config.CONVLSTM_MAX_FRAMES`, `CONVLSTM_TRAIN_TIMEOUT_S`,
  `CONVLSTM_TRAIN_MEM_LIMIT_GB`. Test: `tests/test_b147_convlstm_isolation.py`.
- Dateien: `config.py`, `radar_convlstm.py`, `scheduler.py`.

## Phase B (Hailo) — Stand
- Schweres Training/DFC-Kompilierung weiterhin für M910q vorgesehen (U-Net-Nowcasting als
  primäres Hailo-Ziel). B147 macht das ConvLSTM-Training zusätzlich Pi-tauglich (Streaming),
  ohne die Phase-B-Architektur zu ändern (Inferenz auf dem Pi, schweres Training optional
  auf dem Trainer).

### B148 — Ortspopup: Erstkontaktzeit (ETA) + garantierter Transit-Treffer ✅ erledigt (Feature)
- Wunsch A: Popup zeigt jetzt die präzise Zeit bis zur ersten Radius-Berührung
  (`first_contact_min`), interpoliert entlang der Bahn statt nur den diskreten Horizont.
- Wunsch B: Durchquerung zwischen zwei Horizonten zählt als Treffer. War via P34
  (Zwischensegmente) + B127 (Rand-Streifen) bereits weitgehend abgedeckt; B148 schließt die
  letzte Lücke (reiner Mittelpunkt-Transit trotz Polygon-Stützpunkt zu weit) durch einen
  `transit`-Treffer aus derselben Segment-Kreis-Primitive.
- Neue Helfer in `locations_check.py`: `_forecast_track_points`, `_first_radius_contact_min`.
  Additiv — current/slow_approach/forecast/growth_approach, P-T06-Survival, P-T09-stale
  unverändert. Survival-Unterdrückung greift auch auf den Transit-Treffer.
- Frontend: `MapView.jsx` + `MapFullscreen.jsx` zeigen „⏱ Radius erstmals berührt in ~X min".
- Test: `tests/test_b148_first_contact.py`. Dateien: `locations_check.py`,
  `frontend/src/pages/MapView.jsx`, `frontend/src/pages/MapFullscreen.jsx`.
- Phase B (Hailo) unberührt.

### B149 — Circuit-Breaker zentral in retry_get (Schritt 1 von #5) ✅ erledigt
- `http_retry.retry_get` bekommt optionalen Parameter `breaker_service`. Gesetzt → Breaker
  zentral: is_open()-Gate (→ `CircuitOpenError`), record_success() bei Erfolg,
  record_failure() bei 429/5xx/Timeout/Connection/SSL (max. 1× pro Aufruf, keine
  Doppelzählung über Retries). Ohne Parameter unverändert (rückwärtskompatibel).
- `CircuitOpenError` ist Subklasse von `requests.exceptions.RequestException` → bestehende
  except-Blöcke der Fetcher greifen den Fallback automatisch.
- Grundlage für die schrittweise Anbindung der Fetcher (#5): B150 ff. setzen je
  `breaker_service="…"` (kanonischer Name) bzw. migrieren `tawes`/`nowcast` von rohem
  requests.get auf retry_get.
- Test: `tests/test_b149_retry_get_breaker.py`. Datei: `http_retry.py`.

### B150 — TAWES an Circuit-Breaker (#5, Rollout 1) ✅ erledigt
- `fetch_tawes_gust.fetch_tawes_stations()` von rohem `requests.get` auf `retry_get`
  umgestellt mit `service="geosphere_tawes_all"` und `breaker_service="geosphere_tawes_all"`.
- Retry + Logging + Breaker laufen jetzt zentral; doppeltes Fehler-Logging entfällt.
  Erfolgs-`log_api_call` (mit Payload) bleibt für das Dashboard erhalten.
- Test: `tests/test_b150_tawes_breaker.py`. Datei: `fetch_tawes_gust.py`.
- Offen im #5-Rollout: B151 `fetch_geosphere_nowcast` (Bulk + Einzel + B131-OOC),
  danach die bereits auf retry_get laufenden Fetcher (blitz_api, fetch_arome_openmeteo,
  cloud_height_from_eumetview, fetch_700hpa_wind, radar_download) je `breaker_service=`.

### B151 — Nowcast an Circuit-Breaker (#5, Rollout 2) ✅ erledigt
- `fetch_geosphere_nowcast`: Bulk-Request (`assign_nowcast_to_objects`) UND Einzel-Fallback
  (`_parse_nowcast_single`) von rohem `requests.get` auf `retry_get` mit
  `service`/`breaker_service="geosphere_nowcast"` umgestellt.
- Doppel-Logging entfällt (retry_get loggt Fehler in beiden Pfaden + bedient Breaker).
  B131-Out-of-Coverage bleibt exakt: nur echte 4xx → `_ooc_mark`; Timeout/Connection/5xx/
  CircuitOpen (status 0) → kein OOC-Merken. Erfolgs-`log_api_call` bleibt.
- Test: `tests/test_b151_nowcast_breaker.py`. Datei: `fetch_geosphere_nowcast.py`.
- Offen im #5-Rollout: die bereits auf retry_get laufenden Fetcher je `breaker_service=`
  (blitz_api, fetch_arome_openmeteo, cloud_height_from_eumetview, fetch_700hpa_wind,
  radar_download).

### B152 — Blitzortung an Circuit-Breaker (#5, Rollout 3) ✅ erledigt
- `blitz_api`: `retry_get(...)` um `breaker_service="blitzortung_last_strikes"` ergänzt
  (lief bereits über retry_get; nur Breaker-Anbindung).
- Test: `tests/test_b152_blitz_breaker.py`. Datei: `blitz_api.py`.

### B153 — 700-hPa-Wind an Circuit-Breaker (#5, Rollout 4) ✅ erledigt
- `fetch_700hpa_wind_per_object_slim`: `retry_get(...)` um
  `breaker_service="openmeteo_icon_global"` ergänzt (lief bereits über retry_get).
- Test: `tests/test_b153_wind_breaker.py`. Datei: `fetch_700hpa_wind_per_object_slim.py`.

### B155 — GeoSphere-CAPE an Circuit-Breaker (#5, Rollout 6) ✅ erledigt
- `assign_cape_from_forecast.fetch_or_use_latest_geojson()` von rohem `requests.get` auf
  `retry_get` (`service`/`breaker_service="geosphere_cape"`); bestehender
  `except → get_latest_geojson()`-Fallback bleibt (fängt auch CircuitOpenError).
- Test: `tests/test_b155_cape_breaker.py`. Datei: `assign_cape_from_forecast.py`.

### B156 — ARSO-Radar an Circuit-Breaker (#5, Rollout 7) ✅ erledigt
- `radar_download.download_kmz()`: Breaker EXPLIZIT angebunden (Service `arso_radar`) —
  is_open()-Gate am Anfang; record_success() bei 304/SHA256-identisch/200; record_failure()
  bei 4xx und nach allen fehlgeschlagenen Versuchen (Reason robust aus Exception-Typ).
  Bewusst KEIN retry_get (eigene If-Modified-Since/304- und SHA256-Dedup-Logik bleibt).
- Test: `tests/test_b156_radar_breaker.py`. Datei: `radar_download.py`.
- #5-Rollout offen: nur noch `fetch_arome_openmeteo` (openmeteo_icon_d2) — separater Prompt.

### B158 — Radar-Breaker-Fixes (Codex zu B156) ✅ erledigt
- 429-Retry-After: im 4xx-Pfad wird `Retry-After` aus der Response geparst und an
  `record_failure(..., retry_after=…)` übergeben → Cooldown folgt dem Provider statt 1h-Default.
- Erfolg erst nach Validierung: `record_success("arso_radar")` aus dem Erfolgs-`break`
  entfernt und erst direkt vor dem finalen `return True` (nach ZIP-Validierung + Entpacken)
  gesetzt. Ein 200-Fehlerseiten-/Korrupt-ZIP setzt den Breaker damit nicht mehr fälschlich
  zurück. 304/SHA256-identisch bleiben legitime Erfolge.
- Test: `tests/test_b158_radar_breaker_fix.py`. Datei: `radar_download.py`.

### B159 — CAPE: Doppel-Logging vermeiden (Codex zu B155) ✅ erledigt
- Im except von `fetch_or_use_latest_geojson()` das zweite
  `log_api_failure("GeoSphere-CAPE", …)` entfernt — `retry_get` protokolliert den Ausfall
  bereits unter `geosphere_cape`. Verhindert Doppelzählung unter zwei Service-Namen.
- Die übrigen `log_api_failure("GeoSphere-CAPE", …)` in `assign_cape()` (Daten-/Inhaltsfälle)
  bleiben unberührt.
- Test: `tests/test_b159_cape_doppellog.py`. Datei: `assign_cape_from_forecast.py`.

### B167 — test_debug_export.py auf asynchronen Export-Vertrag + Temp-Cleanup bei Build-Fehler ✅ erledigt
- Ursache: B162 entfernte den synchronen token-losen Build (→ 400 use_parts_endpoint). Sechs alte
  Tests prüften den synchronen Vertrag (200/500/409/cleanup) und schlugen mit 400 fehl.
- Fix: die sechs Tests auf den asynchronen Vertrag umgestellt (Fake-subprocess.Popen: ready/error/
  building); Auth- und direkte create_debug_export_zip-Tests unverändert übernommen. Zusätzlich
  räumt `_poll_export_build` einen fehlgeschlagenen Build-Ordner sofort auf (kein Temp-Leak).
- Test: `tests/test_debug_export.py` (neu geschrieben). Datei: `app.py` (_poll_export_build). Verwandt: B162.


### B166 — Kinematische Glättung gegen vx/vy-Sprünge bei Merge/Split ✅ erledigt
- Ursache: `_append_kinematic` mittelte die gespeicherten vx/vy ALLER History-Frames inkl. des
  Merge/Split-Frames, dessen Schwerpunktsprung die kinematische Vorhersagegeschwindigkeit verbog.
- Fix: Bei `merge_discontinuity`/`is_merged`/`is_split` wird der jüngste History-Eintrag aus der
  v-Mittelung ausgeschlossen (nur wenn danach ≥ 2 Frames bleiben); `kinematic_source` += `+mguard`.
  Optischer Fluss (P-M02) bleibt Vorrang und unbeeinflusst; Kalman-Clamp greift bei kurzer History.
- Test: `tests/test_b166_merge_smoothing.py`. Dateien: `prediction.py`, `logic.md`. Verwandt: B30/B115/B117, P-M02.

### B164 — Test-Isolation: b88-Nowcast-Tests gegen Disk-Cache-HITs gehärtet ✅ erledigt
- Ursache: `test_geosphere_nowcast_b88.py` stubte `api_cache` nur per modulweitem
  `sys.modules.setdefault(...)` (greift nicht, wenn api_cache bereits geladen). Bei warmem
  Disk-Cache (Live-Dienst schreibt `geosphere_nowcast_bulk_*`) lieferte das echte `cache_get`
  einen HIT → `retry_get` lief nie → `captured["url"]`/Fallback-Log fehlten (KeyError/assert False).
- Fix: autouse-Fixture `_isolate_cache` patcht `nowcast.cache_get`→None / `nowcast.cache_set`→no-op
  pro Test (Cache-Miss erzwingen), analog `test_nowcast_out_of_coverage_b131::_isolate`.
- Test-only, kein Produktionscode. Datei: `tests/test_geosphere_nowcast_b88.py`.

### B163 — Korrektur des B160-Guard-Tests (fragile requests.exceptions-Assertion) ✅ erledigt
- `test_requests_impostor_is_replaced` prüfte `hasattr(rq, "exceptions")` — nach del+Reimport ist
  das Submodul-Bare-Attribut auf dem neuen Parent-Objekt (CPython-Submodul-Caching) nicht
  zuverlässig gesetzt → False-Negative. Kein Produktionsfehler (requests ist im Normallauf nie
  Impostor; der reale Pfad http_retry.requests.exceptions ist über den http_retry-Guard abgedeckt).
- Fix: robuste Prüfung via `importlib.import_module("requests.exceptions")` + RequestException
  statt Bare-Attribut. Datei: `tests/test_b160_module_impostor_guard.py`. Produktionscode unverändert.

### B162 — Admin-Export: systemd-Watchdog-Kill → Subprozess-Build + Status-Polling ✅ erledigt
- Ursache (journalctl bewiesen): `GET /api/admin/export/last-24h/parts` baute den 24-h-Export
  SYNCHRON im Flask-Request (> 60 s CPU). Das hungerte den Watchdog-Heartbeat aus →
  „Watchdog timeout (limit 1min)!" → SIGABRT (status=6/ABRT). nginx: „upstream prematurely
  closed" + „connect() failed (111)" → das im Dashboard sichtbare 502. Kein OOM, kein Timeout.
- Schlüssel: Ein Build im selben Prozess (auch als Thread) hungert den Heartbeat-Thread genauso
  aus → Build MUSS in einen eigenen Prozess.
- Fix: neuer Runner `tools/build_debug_export_volumes.py` (eigener Prozess, schreibt
  manifest.json/error.json). `_build_export_volumes()` ersetzt durch `_start_export_build()`
  (subprocess.Popen, kehrt sofort zurück) + `_poll_export_build()`. `/parts` liefert sofort
  `{token, status:"building"}`; neuer Endpunkt `/api/admin/export/status?token=…` zum Pollen;
  `last-24h.zip?token=&part=N` liefert nur bei `ready` aus. Token-loser synchroner Build-Pfad
  entfernt (→ 400 use_parts_endpoint). Start/Ende/Fehler über `debug_log` (journald-sichtbar,
  da app.logger.info bei Flask-Default-Level WARNING unsichtbar war). Frontend `Logs.jsx` pollt.
- Test: `tests/test_b162_export_async.py`. Dateien: `app.py`, `tools/build_debug_export_volumes.py`,
  `frontend/src/pages/Logs.jsx`.

### B161 — Test-Aktualisierung: Nowcast-OOC-Test auf retry_get-Pfad ✅ erledigt
- Ursache der 4 roten Tests (test_nowcast_out_of_coverage_b131): der Test patchte noch den
  vor B151 gültigen rohen `nowcast.requests.get`. Seit B151 läuft Nowcast (Bulk
  `assign_nowcast_to_objects` + Einzel `_parse_nowcast_single`) ausschließlich über
  `http_retry.retry_get(breaker_service="geosphere_nowcast")` → alter Patch ohne Wirkung.
- Fix: Test vollständig neu — patcht `http_retry.retry_get` statt `nowcast.requests.get`;
  OOC-Datei + log_api_call/debug_log + Cache in tmp/no-op isoliert (keine echten Writes,
  kein Netzwerk). Abgedeckt: 4xx→_ooc_mark, CircuitOpen(status 0)→kein Merken, TTL aktiv→
  kein Request, TTL abgelaufen→Re-Request, Erfolg→_ooc_clear.
- Entfällt: `test_b131_single_fallback_4xx_logs_both_counter_and_failure` — das Doppel-Logging
  (log_api_failure + log_api_call) liegt seit B151 zentral in retry_get und wird durch
  `tests/test_b149_retry_get_breaker.py` geprüft.
- Test: `tests/test_nowcast_out_of_coverage_b131.py`. Produktionscode unverändert.

### B154 — EUMETView an Circuit-Breaker (#5, Rollout 5) ✅ erledigt
- `cloud_height_from_eumetview`: GetCapabilities (`get_latest_wms_time`) von rohem
  `requests.get` auf `retry_get` (`breaker_service="eumetview_capabilities"`); GetMap-TIFF
  (`assign_cloud_top_height`) um `breaker_service="eumetview_wms"` ergänzt.
- Test: `tests/test_b154_eumetview_breaker.py`. Datei: `cloud_height_from_eumetview.py`.

### B157 — AROME an Circuit-Breaker (#5, Rollout 8 — Abschluss) ✅ erledigt
- `fetch_arome_openmeteo`: icon_d2-Hauptrequest (`assign_arome_to_objects`) auf kanonischen
  Service `openmeteo_icon_d2` + `breaker_service="openmeteo_icon_d2"`; lifted_index-Fallback
  (`_fetch_arome_li_via_icon_eu`, GFS) um `breaker_service="openmeteo_icon_eu_li"` ergänzt.
- Doppel-Logging im icon_d2-except entfernt (retry_get loggt bereits) — analog B159.
- Daten-Qualitäts-Log „arome_t2m alle 0.0" bleibt unberührt (kein Netzwerk-Ausfall).
- Test: `tests/test_b157_arome_breaker.py`. Datei: `fetch_arome_openmeteo.py`.
- **#5-Rollout abgeschlossen:** alle externen Fetcher laufen jetzt über den Circuit-Breaker
  (arso_radar, blitzortung_last_strikes, eumetview_capabilities, eumetview_wms,
  geosphere_cape, geosphere_nowcast, geosphere_tawes_all, openmeteo_icon_d2,
  openmeteo_icon_eu_li, openmeteo_icon_global, openmeteo_outlook).

### B160 — Test-Isolation: http_retry/requests-Impostor-Leak aus test_eumetview_parser ✅ erledigt
- Ursache der 6 roten Tests (test_b149_retry_get_breaker 5×, test_b151_nowcast_breaker 1×):
  `tests/test_eumetview_parser.py` setzte auf Modulebene
  `sys.modules.setdefault("http_retry", SimpleNamespace(retry_get=lambda→None))` und
  `setdefault("requests", SimpleNamespace())`. Diese Stubs blieben für den gesamten pytest-Lauf
  in sys.modules haften → `hr._SESSION` fehlt (b149), `http_retry.requests` fehlt (b151).
  Gleiche Klasse wie B96/B125/B127.
- Fix 1 (Quelle): test_eumetview_parser.py lädt die ECHTEN Module
  (`pytest.importorskip("requests")` + `import http_retry`) statt SimpleNamespace-Stubs;
  get_latest_wms_time() importiert retry_get zur Laufzeit, die Tests patchen
  `sys.modules["http_retry"].retry_get` pro Test (mit echtem Modul identisch).
- Fix 2 (Defensive): `tests/conftest.py` _preload_critical_modules() um `requests` und
  `http_retry` erweitert (Impostor-Drop + Reimport vor der Sammlung; requests vor http_retry).
- Test: `tests/test_b160_module_impostor_guard.py`. Dateien: `tests/test_eumetview_parser.py`,
  `tests/conftest.py`. Produktionscode unverändert.

### B160 — EUMETView Capabilities-Loop an Breaker (Nachzieher zu B154) ✅ erledigt
- `get_latest_wms_time()`: der GetCapabilities-Re-Fetch im B125-Robustheits-Loop bekommt
  ebenfalls `breaker_service="eumetview_capabilities"` (zuvor nur der Erst-Request via B154).
- Test: `tests/test_b160_eumetview_caps_loop_breaker.py`. Datei: `cloud_height_from_eumetview.py`.

### B165 — Drift-Detektor: absoluter Kurzhorizont-Wächter (Zieldefinition ≤30 min < 1 km) ✅ erledigt
- Ursache: `check_drift()` erkannte Drift nur RELATIV (delta > 2 km). Ein konstant hoher Fehler
  (z. B. ~10 km bei +10/+30 min) galt als „stabil" → Verstoß gegen zieldefinition.txt
  („≤30 Min < 1 km"). Das All-Horizont-Mittel (`_mean_mae`) maskierte zusätzlich den Kurzhorizont.
- Fix: neuer Helper `_mean_mae_for_horizons(records, max_horizon_min)`; Config
  `DRIFT_MAE_ABS_MAX_KM` (1.0), `DRIFT_SHORT_HORIZON_MAX_MIN` (30); absoluter Wächter in
  `check_drift()` (unabhängig vom relativen Trend, nur bei `_has_ml_model()`); neue Result-Felder
  `mae_recent_short_km`/`short_horizon_max_min`/`abs_threshold_km`/`drift_reason`; Alarm-Mail um
  Kurzhorizont-Zeile + Grund ergänzt.
- Test: `tests/test_b165_drift_absolute_guardrail.py`. Dateien: `drift_detector.py`,
  `email_notifier.py`, `docs/WetterExtended_Benutzerhandbuch.md`. Verwandt: B23.

## B168 – Lernfortschritt: Fehler-/Leer-/Modus-Trennung (2026-06-16)
Status: ERLEDIGT
Ursache: `Progress.jsx` schluckte jeden /api/progress-Fehler still
         (`.catch(() => setLoaded(true))`) → Fehler-Zustand optisch identisch zum
         echten Cold-Start. Zusaetzlich war die Modus-Aussage statisch im Leer-Zweig
         hinterlegt und aus `versions.length` abgeleitet statt aus dem echten
         Produktiv-Status (`/api/forecast_stats.ml_blocked_reason`, B116). Folge:
         Seite behauptete "kein trainiertes Modell aktiv" trotz 4 trainierter,
         kompatibler Versionen (HAR + curl belegt).
Fix: (1) loadError-State trennt Ladefehler vom echten Leerzustand; rote Fehler-Karte
         mit "Erneut versuchen". (2) Immer sichtbare Modus-Badge aus /api/forecast_stats
         (gruen = ML aktiv, gelb = kinematisch + Klartext-Grund). (3) Statische
         Falschbehauptung entfernt. Charts/Tabelle unveraendert.
Externe Services: nicht betroffen (interne Endpunkte).
Dateien: frontend/src/pages/Progress.jsx, tests/test_b168_progress_active_mode.py (neu)

## B169 – Lernfortschritt: /api/progress ungültiges JSON (Infinity) + _ml_block_reason os.isdir (2026-06-16)
Status: ERLEDIGT
Ursache A: `_ml_block_reason()` (app.py) rief `os.isdir` (existiert nicht) statt
           `os.path.isdir` → jeder Status-Check landete im except
           ("status-check fehlgeschlagen: module 'os' has no attribute 'isdir'") →
           echter ML-Aktiv-Status (B116) nie ermittelt.
Ursache B: `/api/progress` serialisierte `training_meta.json` mit `"mae_old": Infinity`
           (float('inf'), Cold-Start). jsonify gibt das Literal `Infinity` aus →
           ungültiges JSON → Browser-JSON.parse bricht ab (Spalte 2232). Das war die
           eigentliche Ursprungsursache des leeren Lernfortschritts; B168 (UI-Robustheit)
           machte sie sichtbar.
Fix A: `_os_mb.isdir` → `_os_mb.path.isdir`.
Fix B: neuer rekursiver Helfer `_json_finite_safe()` ersetzt inf/-inf/nan durch null,
       angewandt in `api_progress` vor jsonify. Behebt auch bestehende v_*-Metas,
       ohne Lerndaten zu verändern.
Externe Services: nicht betroffen (interne Endpunkte).
Dateien: app.py, tests/test_b169_progress_json_and_mlreason.py (neu). Verwandt: B116, B168.

### B172 — Bewegungs-Seed für neu entstandene Zellen ✅ erledigt
- Ursache: neue Zellen (lineage="new", kein Parent) erhielten in `object_tracking.py`
  `kf.x=[cx,cy,0,0]` → Geschwindigkeit 0. Da pysteps auf dem Pi fehlt (of_available=0),
  fehlte jede feldbasierte Bewegung → kinematischer Forecast konnte neue Zellen nicht
  weiterbewegen (Verstoß gegen zieldefinition.txt ≤30 min < 1 km).
- Fix: neuer Helper `_neighbor_motion_seed()` mittelt den Bewegungsvektor (ORIGINAL-px/Frame)
  der aktiven Zellen des letzten Frames im Umkreis `NEW_CELL_SEED_RADIUS_KM` (config, 30 km)
  und seedet damit Kalman-Zustand und vx/vy. Konvention-frei (reine px/Frame), kf.P=500
  bleibt → schnelle Korrektur durch die nächste Messung. Ohne Nachbarn weiterhin (0,0)
  (optischer Fluss übernimmt nach pysteps-Installation, siehe B173).
- Test: `tests/test_b172_new_cell_seed.py`. Dateien: `object_tracking.py`, `config.py`.
- Invarianten unberührt (UPSCALE_FACTOR/PX_TO_KMH). Verwandt: B173 (pysteps), P-M01/P-M02.


### B175 — Skywarn-Snapshot defensiv gegen None/leere Antwort ✅ erledigt
- Ursache: `build_success_snapshot()` rief im Return `payload.get("start"/"end"/"text")` ohne
  None-Guard auf. Bei JSON `null` (leere Lage) → AttributeError, vom Catch-All als
  "unexpected_error" mit valid_from/valid_to=null maskiert.
- Fix: `if not isinstance(payload, dict): return _error_snapshot("empty_payload", …)` am
  Funktionsanfang → sauberes status='error' ohne Exception, ohne Folge-Request.
- Test: `tests/test_b175_skywarn_empty_payload.py`. Datei: `skywarn_export_snapshot.py`.

### B176 — Horizont-wachsender Unsicherheitskegel (Fallback ohne Quantile) ✅ erledigt
- Ausgangslage: B130-Korridor nur bei KI-Vorhersagen mit q10/q90. Kinematische Vorhersagen
  (Normalfall) ohne Kegel → scheingenaue Zugbahn, besonders +40/+60 min (hit_rate=0).
- Fix (Frontend, MapView.jsx + MapFullscreen.jsx): neuer `cone`-Fallback, wenn kein
  Quantil-Korridor vorliegt. Halbbreite r(h)=3 km + 0,3 km/min·h, Offsets entlang der
  Achse Ursprung→letzter Stützpunkt (robust, ohne Selbstüberschneidung). Rein clientseitig.
- Fach-Feature → Benutzerhandbuch-Abschnitt „NEU: Unsicherheitskegel der Zell-Vorhersage".
- Test: `tests/test_b176_forecast_cone.py`. Dateien: `frontend/src/pages/MapView.jsx`,
  `frontend/src/pages/MapFullscreen.jsx`, `docs/WetterExtended_Benutzerhandbuch.md`.
- Verwandt: B128 (durchgehende Zugbahn), B130 (Quantil-Korridor). KMZ-Unsicherheit
  unverändert über q10/q90-Ellipsen.

### B174 — EUMETView: Fallback auf letzten WMS-Timestamp bei Capabilities-Fehler ✅ erledigt
- Ursache: bei endgültigem GetCapabilities-Fehlschlag gab `get_latest_wms_time()` None zurück
  → alle Objekte cloud_height_missing=1.0 (IR-/Cloud-Top-Verarbeitung im Fallback).
- Fix: neuer Helper `_caps_fallback(reason)` verwendet `read_last_timestamp()` wieder, sofern
  jünger als `EUMETVIEW_FALLBACK_MAX_AGE_MIN` (30 min, config-überschreibbar). Drei
  Failure-Returns (parse-failed/target-missing/Funktionsschluss inkl. parser-no-timestamp &
  Exception) liefern jetzt den frischen Fallback statt None. Erfolgspfad unverändert.
- Test: `tests/test_b174_eumetview_fallback.py`. Datei: `cloud_height_from_eumetview.py`.
- Verwandt: B125/B154/B160 (Caps-Robustheit/Breaker).

### B177 — Radar-SKIP-Grund differenzieren (nicht-neu vs. ungültig) ✅ erledigt
- Ursache: `main.py` loggte jeden Radar-Skip pauschal ("ungültig oder nicht neu"). Track-Abrisse
  durch echte Defekte (Download/ZIP/Entpacken) waren nicht von legitimem "kein neues Bild"
  (304/SHA-identisch) unterscheidbar.
- Fix: `download_kmz()` setzt `_LAST_SKIP_REASON` (Default "not_new", Fehlerpfade gezielt);
  `last_skip_reason()` Getter; `main.py` loggt differenziert (nicht neu / Circuit offen /
  ungültig <grund>). Rückgabe-Vertrag bleibt bool; B158-Adjazenz unangetastet.
- Pull-Intervall unverändert (bereits via B121-3-Stufen-Logik an Aktivität gekoppelt).
- Test: `tests/test_b177_radar_skip_reason.py`. Dateien: `radar_download.py`, `main.py`.
- Verwandt: B156/B158 (Radar-Breaker), B121 (Skip-Intervall), P2-1 (SHA-Dedup).

### B178 — install.sh: pip-Fehler nicht mehr verschlucken + kritische Importe verifizieren ✅ erledigt
- Root-Cause: `pip_install_safe()` maß den Erfolg an `… | tail -5; then` → Exit-Code von `tail`,
  nicht von pip. Fehlgeschlagene Builds (z. B. pysteps/scipy auf aarch64) wurden still als
  Erfolg gewertet → pysteps deklariert, aber nicht importierbar.
- Fix 1: alle drei pip-Stufen prüfen `${PIPESTATUS[0]}` (echter pip-Exit), analog zur
  pytest-Phase. Fix 2: nach dem requirements-Install werden kritische Importe
  (numpy/scipy/pysteps/cv2/lightgbm/shapely/rasterio/filterpy) verifiziert; fehlende erzeugen
  laute Warnung + manuellen Schritt (inkl. aarch64-Git-Fallback für pysteps). Kein Hart-Abbruch.
- requirements.txt unverändert (`pysteps>=1.8.0` bleibt).
- Test: `tests/test_b178_install_pip_exit.py`. Datei: `install.sh`.
- Verwandt: B173 (zurückgezogen — pysteps war bereits deklariert; eigentliches Problem war
  dieser stille Build-Fehler).

## Schritt 1 — Convective-Risk-Layer (Rapid-Scan / Höhen-Alarm / IR-Lineage / Risk-Watch)

Erweiterung der Phase E. Ziel: Frühwarn-Layer aus Rapid-Scan-IR108, aktiven
Höhen-Alarmen, CB-IR-Vorläuferzellen, durchgehender Zell-Lineage (IR→Radar) und
Gewitterpotenzial — ohne kostenpflichtige APIs und ohne unnötige Requests.

> **CB-ONLY (verbindlich):** Höhen-Alarm und IR-Vorläuferstatus gelten ausschließlich
> für Cumulonimbus (konvektive Zellen mit Niederschlagskern / Overshooting Top).
> Andere hochliegende Wolken (Cirren, Amboss-/Anvil-Reste, Frontbewölkung) lösen
> WEDER Höhen-Alarm NOCH IR-Vorläuferstatus aus.

| Teil | Aufgabe | Datei(en) | Status |
|---|---|---|---|
| 1A.1 | **Risk-Watch-Polling:** kurzer Loop-Intervall auch bei Gewitterpotenzial (`/api/risk_grid` ≥ `RISK_WATCH_MIN_RISK_LEVEL`) ODER CB-IR-Vorläuferzelle (`ir_only_precursor==1.0`). Gekapselt in `risk_watch.py`, beide Intervall-Stellen. | `risk_watch.py`, `main.py`, `config.py`, `tests/test_risk_watch_interval.py` | ✅ erledigt |
| 1A.2 | EUMETView Scan-Modus FES/RSS (`get_active_ir108_layer`): RSS nur bei `free_confirmed` + GetCapabilities-validiertem Layer, sonst FES-Fallback. RSS-Layername NICHT hart angenommen. RSS-IR108 auf EUMETView nicht verfügbar (nur ir039 + RGB) → bleibt dauerhaft FES (B206). | `cloud_height_from_eumetview.py`, `config.py`, `tests/test_eumetview_scan_mode.py` | ✅ erledigt (RSS-Scharfschaltung Pi-seitig) |
| 1B.1 | Einstellbare CB-Höhengrenze (`CLOUD_HEIGHT_ALERT_THRESHOLD_M`, runtime-überschreibbar) — ersetzt die hartkodierte `>= 10000`-Grenze der bestehenden „CB > …"-Anzeige (IR-Layer), geliefert via `/api/objects?include_ir=1`. KEIN separates Flag, KEINE Markierung aktiver Radarzellen. Karten-Defaults: Risikozonen aus, CB/IR-Vorläufer an. | `config.py`, `app.py`, `frontend/src/pages/MapView.jsx`, `frontend/src/pages/MapFullscreen.jsx`, `tests/test_cb_threshold_delivery.py` | ✅ erledigt |
| 1B.2 | ~~Aktive-Zelle-Höhen-Alert-Engine (Polygon-/Core-Statistik p90, Karten-Halo), nur CB~~ — **verworfen (B204):** B204 hat bewusst KEINE zusätzliche Markierung aktiver Radarzellen (kein separates Höhen-Halo) eingeführt; die einstellbare CB-Höhengrenze liefert 1B.1 über `/api/objects?include_ir=1`. | — (`cloud_height_alerts.py` nicht erstellt) | ❌ verworfen (B204) |
| 1C | IR-Vorläuferzelle vereinheitlichen (`type/radar_confirmed/is_potential_new_cell`, Flächenwachstum, BT-Cooling), nur CB | `ir_cell_detection.py`, `ir_cell_tracking.py` | ✅ 1C.1 IR-Vorläufer-Semantik vereinheitlicht; ✅ 1C.2 Wachstumsfelder für IR-Tracks ergänzt; ✅ 1C.3 Payload-/Karten-Deduplizierungs-Guardrails ergänzt |
| 1L.1 | **Zell-Lineage:** CB-IR-Wolke bekommt früh stabile `cell_id`; technische `ir_track_id`/`radar_track_id` bleiben intern | `cell_lineage.py`, `ir_cell_tracking.py`, `config.py` | ✅ erledigt — stabile cell_id für CB-IR-Tracks, Persistenz in train_data/cell_lineage |
| 1L.2 | Score-Matching IR↔Radar (vorhergesagte IR-Position, Growth-/MetPot-Signale, Zeitfenster ≤45 min); Radarzelle übernimmt `cell_id` | `cell_lineage.py`, `main.py`, `config.py`, `tests/test_1l2_ir_radar_score_matching.py` | ✅ erledigt |
| 1L.3 | Karten-/API-/KMZ-Dedup: gematchte IR-Wolke nicht mehr als Vorläufer; physikalische Zellen über `cell_id` eindeutig sichtbar | `app.py`, `kmz_export.py`, Frontend, `tests/test_1l3_cell_lineage_dedup.py` | ✅ erledigt — API/Karte/KMZ deduplizieren physikalische Zellen über cell_id |
| 1L.4 | ML-Lead-Time-Labels (`became_radar_cell`, `ended_without_radar`, `lead_time_min`) aus IR→Radar-Lineage erzeugen; API-/Debug-Export-/Cleanup-Schutz; Training/Modellnutzung folgt später | `cell_lineage.py`, `app.py`, `tools/summarize_ir_lead_time_labels.py`, `tests/test_1l4_ir_lead_time_labels.py` | ✅ erledigt — Labels werden in `train_data/cell_lineage/ir_lead_time_labels.jsonl` geschrieben; ML-Verwertung folgt als spätere Phase |
| 1D | Storm-Potential anreichern (normalisierter Score 0–1 + `drivers[]`) in `risk_grid` | `app.py` | ✅ erledigt (P48) |
| 1E | Admin/Logs/Budget-Guard (Free-only erzwingen, persistente Budgetzähler) | `api_budget_guard.py`, Frontend, `app.py` | ✅ erledigt |

### B203 — Risk-Watch-Korrekturen (Codex-Review zu 1A.1) ✅
- **Skip-Pfad:** `risk_watch_active(ir_tracks=None)` lädt jetzt persistierte aktive
  IR-Tracks (`load_active_ir_tracks`), sodass eine CB-IR-Vorläuferzelle den kurzen
  Intervall auch bei `not_new`-Radar weiter erzwingt.
- **Frische-Gate:** `RISK_WATCH_MAX_DATA_AGE_MIN` (20 min). Sind die jüngste Objekt-Datei
  und der IR-State älter, erzwingt Risk-Watch keinen kurzen Intervall mehr — der
  120-min-Backoff greift wieder (verhindert Dauer-Pinning nach Radar-Ausfall).
- **Dateien:** `risk_watch.py`, `config.py`, `tests/test_risk_watch_interval.py`,
  `tests/test_risk_watch_freshness.py`

### B207 — Neu-Zellen-Seed ignoriert verschwundene Zellen (Codex-Review) ✅
- `_neighbor_motion_seed()` überspringt jetzt Snapshot-Einträge mit `missing != 0`.
  Verhindert, dass neu entstehende Zellen die veraltete Geschwindigkeit bereits
  verschwundener Nachbarn erben (Prio-1-Genauigkeit, ≤30 min < 1 km).
- Datei: `object_tracking.py`, `tests/test_b207_seed_skip_missing.py`. Verwandt: B172.

### P48 — Storm-Potential-Score (0–1) + drivers[] in /api/risk_grid (Roadmap 1D) ✅ erledigt
- `/api/risk_grid` liefert je Grid-Zelle zusätzlich `info.score01` (normalisierter
  Roh-Score 0.0–1.0, Default-Norm `RISK_SCORE01_NORM=2.5`, runtime-überschreibbar) und
  `info.drivers[]` (`{source,label,value}`, dominante Quelle zuerst:
  cell→track→ir_cell→lightning→atm) — erklärt, warum eine Zone riskant ist.
- Rein additiv: bestehende Felder (`risk`, `color`, `info.score`, …) unverändert.
- Reiner Modul-Helfer `_risk_score01_and_drivers(info, norm)` (isoliert testbar), arbeitet
  nur auf dem fertigen info-Dict (keine Loop-Variablen).
- Backend-only (noch keine UI) → kein Benutzerhandbuch-Eintrag; Frontend-Tooltip ist separat.
- Test: `tests/test_risk_score01_drivers.py`. Datei: `app.py`.

### B210 — Roadmap-Bereinigung: 1B.2 verworfen (B204) ✅ erledigt
- Tabellenzeile **1B.2** ("Aktive-Zelle-Höhen-Alert-Engine, Karten-Halo") in der
  "Schritt 1"-Roadmap auf **❌ verworfen (B204)** gesetzt.
- Begründung: B204/1B.1 hat bewusst entschieden, KEINE zusätzliche Markierung aktiver
  Radarzellen (kein separates Höhen-Halo) einzuführen. Die einstellbare CB-Höhengrenze
  (`CLOUD_HEIGHT_ALERT_THRESHOLD_M`) wird über die bestehende IR-Vorläufer-Anzeige via
  `/api/objects?include_ir=1` geliefert. Die in 1B.2 geplante Datei `cloud_height_alerts.py`
  wurde nie erstellt.
- Reine Doku-Bereinigung: kein Code, kein API-Aufruf, kein benutzersichtbares Feature →
  **kein** Benutzerhandbuch-Update, **kein** Test.
- Datei: `docs/HAILO_INTEGRATION.md`.

### B205 — Totes `cloud_top_alert`-Flag entfernt (Bereinigung nach B204) ✅
- Serverseitiges `cloud_top_alert` (Radarobjekte) und `CLOUD_HEIGHT_ALERT_MIN_CORE_RATIO`
  entfernt — seit B204 ungenutzt (Karte nutzt `CLOUD_HEIGHT_ALERT_THRESHOLD_M` direkt).
- `CLOUD_HEIGHT_ALERT_THRESHOLD_M` bleibt (Karten-Grenze „CB > …", B204).
- Dateien: `config.py`, `cloud_height_from_eumetview.py`,
  `frontend/src/pages/Configuration.jsx`, `tests/test_cloud_top_alert.py` (gelöscht),
  `docs/WetterExtended_Benutzerhandbuch.md`.

### Z01 — Verifikations-Zieltoleranz 5 km → 1 km ✅
- `VERIFICATION_TOLERANCE_KM = 1.0` (war 5.0) — Angleichung an `zieldefinition.txt`
  (<1 km Trefferabweichung bei ≤30 min, Zielwert 0 km).
- Forschungsziel: aktueller kinematischer Fallback erreicht es noch nicht → Hit-Rate
  fällt mit der strengen Toleranz; erste Genauigkeits-Schritte sind B207/B208.
- Suchradius (25 km) und Zeit-Toleranz unverändert. Dateien: `config.py`,
  `docs/WetterExtended_Benutzerhandbuch.md`, `tests/test_z01_verification_tolerance.py`.

### B209 — Subpixel-Schwerpunkt (Genauigkeit, Prio-1) ✅
- `update_tracking_memory()` rundet den Schwerpunkt nicht mehr doppelt ganzzahlig.
  `obj["x"]/["y"]` sind jetzt subpixel-genaue Original-px (float) — entfernt 0,33-km-
  Quantisierung aus Kalman/EWMA-Geschwindigkeit UND Forecast-Ursprung; `lat/lon` konsistent
  aus denselben subpixel-Koordinaten. UPSCALE_FACTOR/Einheiten-Vertrag unverändert.
- Datei: `object_tracking.py`, `tests/test_b209_subpixel_centroid.py`. Verwandt: B115, B209.
### P49 — 1E API-Budget-Guard (Free-only-Durchsetzung) ✅ erledigt
- Neues Modul `api_budget_guard.py`: persistente Tageszaehler je Budget-Gruppe
  (`train_data/evaluation/api_budget.json`, fcntl-gesichert, Reset 00:00 UTC).
- Zentraler Hook in `http_retry.retry_get` (analog Circuit-Breaker B149):
  `over_budget(service)`-Gate -> `BudgetExceededError` (RequestException) +
  `record_request(service)` vor jedem echten `_SESSION.get`. Geblockte Requests
  loesen den bestehenden Fetcher-Fallback (Stale-Cache) aus.
- Gruppen-Modell: alle `openmeteo_*` teilen das providerweite 10.000/Tag-Limit;
  Default `API_DAILY_BUDGET={"openmeteo": 9000}` (config, runtime-ueberschreibbar).
  Gruppen ohne Limit werden gezaehlt, aber nie geblockt (non-breaking).
- Read-Endpoint `GET /api/api_budget` (Stand je Gruppe).
- Offen (optional, kosmetisch): Logs-Budget-Balken im Frontend -> separates P50.
- Dateien: `api_budget_guard.py`, `http_retry.py`, `config.py`, `app.py`.
  Test: `tests/test_api_budget_guard.py`.


### B179 — Test-Isolation: EUMETView-Parser/B125-Tests gegen B174-Fallback ✅ erledigt
- Ursache der 5 roten Tests (test_b125_eumetview_caps_robust 1×, test_eumetview_parser 4×):
  Seit B174 liefert `get_latest_wms_time()` bei jedem Fehlerpfad `_caps_fallback(reason)`
  statt None. `_caps_fallback()` liest via `read_last_timestamp()` die reale Datei
  `train_data/cloud/last_wms_timestamp.txt`. Die Tests patchten `read_last_timestamp` NICHT
  → auf dem Pi mit frischem Timestamp (< EUMETVIEW_FALLBACK_MAX_AGE_MIN=30 min) griff der
  Fallback und gab einen Wert statt None zurück. Auf einer sauberen Maschine ohne die Datei
  waren die Tests grün → undeklarierte Filesystem-Abhängigkeit. Gleiche Klasse wie B160/B161.
- Fix (NUR Tests): in `_patch_common` (b125) sowie in `_run_with_xml`, `test_invalid_xml`
  und `test_http_200_html_not_xml` (parser) `monkeypatch.setattr(mod, "read_last_timestamp",
  lambda: None)` ergänzt. Die Tests pruefen damit wieder ausschliesslich den Parse-Pfad
  (Fehler/kein Layer/kein Timestamp → None). `test_always_broken_returns_none` ist semantisch
  korrekt: „immer kaputt" = nie ein erfolgreicher Fetch = kein letzter Timestamp.
- Produktionscode UNVERÄNDERT. B174-Verhalten korrekt und konform zu zieldefinition.txt
  (gebundener Fallback < 30 min, keine veralteten IR-Daten). Der Fallback-Positivpfad
  (frisch/zu alt/fehlend/unparsbar) bleibt vollständig durch
  `tests/test_b174_eumetview_fallback.py` abgedeckt.
- Kein Benutzerhandbuch-Update (Bug-/Test-Fix, kein Fach-Feature).
- Dateien: `tests/test_b125_eumetview_caps_robust.py`, `tests/test_eumetview_parser.py`,
  `docs/HAILO_INTEGRATION.md`. Verwandt: B174, B160, B161, B125.

| B213 | Split-/Merge-Lineage über `cell_id`: Parent-/Child-Beziehungen, Merge-Aliase und Events `cell_split`/`cell_merge` | `cell_lineage.py`, `main.py`, `object_tracking.py`, `tests/test_b213_split_merge_lineage.py` | ✅ erledigt |
| B214 | Forecast-Error-Breakdown automatisch diagnostizieren: ML vs. kinematic, Richtung, Speed, Match-Type, Coverage und Worst-Forecasts | `forecast_error_diagnosis.py`, `tools/diagnose_motion_pipeline.py`, `app.py`, `drift_detector.py`, `tests/test_b214_forecast_error_diagnosis.py` | ✅ erledigt |

| B215 | Forecast-Error-Detail-Validation: synthetische/zeitlich unmögliche Details aus Diagnose ausschließen und Datenbasis sichtbar machen | `forecast_error_diagnosis.py`, `tools/diagnose_motion_pipeline.py`, `app.py`, `tests/test_b215_forecast_error_detail_validation.py` | ✅ erledigt |

### B216 — Test-Isolation der evaluation-Schreibpfade (Ursache zu B215) ✅
- B215 filterte synthetische Records nur in der Diagnose; die Ursache blieb: Tests schrieben
  via evaluate_for_horizon() echte forecast_error_details.jsonl/accuracy_history.jsonl voll.
- Fix: conftest-autouse-Fixture `_isolate_evaluation_writes` (klassenweit, SAVE_PATHS['evaluation']
  + accuracy_tracker-Konstanten nach tmp) + gezielte Isolation in
  test_accuracy_tracker_horizon_mode.py + Regressionstest + einmalige Bereinigung
  (cell-1 entfernt, Backup `.b216.bak`). Verwandt: B127, B129, B179, B215.

### P51 — Wolkenhöhe immer anzeigen (Warm-Top low-confidence) ✅
- Warm-Top-Konvektion (`bt_k > nan_threshold` & `core_ratio>0`) wird nicht mehr unterdrückt:
  Höhe aus `bt_val` via `warm_top_height_msl()`, `cloud_height_missing=0`,
  neues Flag `cloud_height_low_confidence=1`. Frontend `CloudHeight` zeigt Tilde+Amber+Tooltip.
- „—" nur noch bei echtem Nodata (kein WMS-Timestamp, rasterio fehlt, außerhalb Raster, BT-Nodata).
- Fachhinweis: Warm-Top-Wert = grobe Untergrenze, nicht der echte Cb-Top.
- Dateien: `cloud_height_from_eumetview.py`, `frontend/src/pages/LiveDaten.jsx`,
  `tests/test_p51_cloud_height_low_confidence.py`, Benutzerhandbuch.

## B217 — Atmosphäre-Bulk-Pfad gehärtet (2026-06-21)
Phase A (Stabilisierung / API-Hardening) — **erledigt**.
- `fetch_atmospheric_snapshot._bulk_get` nutzt jetzt `retry_get` (Backoff,
  Retry-After) + Circuit-Breaker + Cache + Stale-While-Error-Fallback —
  letzter Open-Meteo-Fetcher, der noch rohes `requests.get` verwendete.
- Circuit-Breaker geteilt mit fetch_700hpa (`openmeteo_icon_global`).
- Fehlende AROME/GFS-Werte werden als `*_missing`-Flag geführt (t2m, td2m,
  ff10m, fl_height, cape, li, cin, pw) statt als echte 0.0-Messung.
- Behebt die durchgängige 0.0-Atmosphäre bei Open-Meteo-429 (Root-Cause der
  Forecast-Drift-Symptomatik).
- Voraussetzung für B218 (Potenzialbewertung robust gegen missing).

## B218 — Gewitterpotenzial robust gegen Missing (2026-06-21)
Phase A (Stabilisierung) — **erledigt**.
- `_gewitterpotenzial` gibt `"unbekannt"` zurück, wenn LI UND CAPE fehlen
  (B217-Missing-Flags), statt fälschlich `"niedrig"`.
- Verhindert „ruhiges Wetter"-Fehlklassifikation bei API-Ausfall trotz realer
  Konvektion (geosphere_cape 400–800 J/kg).
- Neuer möglicher Ausgabewert `"unbekannt"` — Konsumenten der `potential`-
  Spalte müssen ihn als „Daten fehlen" behandeln (siehe Review-Note).
- Baut auf B217 auf.

## B219 — Kinematischer Geschwindigkeits-Cap unbedingt (2026-06-21)
Phase A (Stabilisierung) — **erledigt**.
- Cap in `_append_kinematic` aus dem `if steering_blend_applied`-Zweig herausgelöst
  und unbedingt angewandt (Knopf `FORECAST_MAX_SPEED_KMH`, Fallback
  `MAX_CELL_SPEED_KMH`).
- Eliminiert 200+ km/h-Ausreißer im optischen-Fluss-/EWMA-/Kalman-Pfad.
- Marker `forecast_speed_capped=1` am Objekt bei aktiver Klemmung.

## B220 — Orographische Dämpfung im Forecast verdrahtet (2026-06-21)
Phase A (Stabilisierung) — **erledigt**.
- `forecast_speed_factor` (orographic_module, 0.1..1.0) wird jetzt in
  `_append_kinematic` VOR der Projektion auf avg_vx/avg_vy angewandt — war zuvor
  eine tote, nur im Admin-Panel angezeigte Diagnose-Größe.
- Reduziert Überprojektion langsamer/orographisch gebremster Zellen
  (Skywarn: nahezu stationäre Bergland-Hitzegewitter).
- Marker `forecast_speed_damped=1` am Objekt bei aktiver Dämpfung.
- Offener Folge-Punkt (separater Prompt): explizite Persistenz-Dämpfung bei
  fehlendem/schwachem Steuerstrom.

## B221 — install.sh Phase 7d: `$request_uri` im nginx-Here-Doc nicht escaped (2026-06-21)
Phase A (Stabilisierung) — **erledigt**.
- Symptom: `install.sh: line 1445: request_uri: unbound variable` → Phase 7d (nginx)
  brach mit Exit-Code 1 ab (full & upgrade).
- Ursache: Der UNQUOTED Here-Doc `<<NGINXCONF` lässt Bash jede `$VAR` expandieren;
  nginx-Variablen werden deshalb als `\$VAR` escaped. Im Admin-Export-Block
  (`proxy_pass http://127.0.0.1:5000$request_uri;`) fehlte der Backslash → unter
  `set -u` Abbruch.
- Fix: `5000$request_uri;` → `5000\$request_uri;` (konventionskonform; nginx ersetzt
  `$request_uri` zur Laufzeit korrekt).
- Neuer Regressions-Test prüft den gesamten Here-Doc-Body auf unescapte Bash-Variablen
  (`tests/test_b221_nginx_heredoc_no_unescaped_vars.py`) → bewacht die komplette Bug-Klasse.

## B222 — install.sh startet nach Selbst-Update neu (re-exec) (2026-06-21)
Phase A (Stabilisierung) — **erledigt**.
- Symptom: Ein in `main` gemergter install.sh-Fix (z.B. B221 nginx `$request_uri`)
  wirkte im selben Lauf NICHT — Phase 7d brach weiter mit `request_uri:
  unbound variable` (alte Zeile 1445) ab, obwohl der Fix auf Platte lag.
- Ursache: install.sh aktualisiert sich in Phase 3 selbst (`git pull` /
  `git reset --hard`). Der laufende Bash-Prozess führt das ALTE Skript zu Ende aus
  (Datei-Inode beim Start geöffnet); der Fix greift erst beim nächsten Aufruf.
- Fix: Nach dem Source-Update SHA256-Vergleich des eigenen Skripts vor/nach Update;
  bei Änderung Neustart via `exec bash "$TARGET/install.sh" "$@"`. Endlosschutz:
  Umgebungsflag `WETTER_INSTALL_REEXEC` + Hash-Gleichheit.
- Test: `tests/test_b222_install_self_reexec.py` (Mechanik, Position, `bash -n`).

## B223 — Test-Fix: Admin-Export-Status-Tests patchen Auth unvollständig (2026-06-21)
Phase A (Stabilisierung) — **erledigt**. Reiner Test-Fix, keine Produktionsänderung.
- Symptom: 3 Tests in `tests/test_admin_export_rate_limit.py` schlugen mit 401 fehl
  (erwartet 200/500/403).
- Ursache: `/api/admin/export/status` (GET) fällt unter `_SENSITIVE_READ_PREFIXES`;
  der `before_request`-Gate `_jwt_auth_check` nutzt `auth.get_current_user` (B107).
  Die Tests patchten nur `app.get_current_user` → Gate liefert 401 vor dem Body.
- Fix: Helfer `_login()` patcht `app` UND `auth` (Muster aus `test_b162_export_async.py`).
- Auth-Verhalten der Produktion ist korrekt und unverändert.

## B224 — Test-Fix: EWMA/Optflow-Tests gegen B219-Speed-Cap isoliert (2026-06-21)
Phase A (Stabilisierung) — **erledigt**. Reiner Test-Fix, keine Produktionsänderung.
- Symptom: `test_optflow_overrides_ewma_when_available` (kinematic_vx -6.0→-5.366) und
  `test_ewma_weights_newer_frames` (vx >7.5 → 5.918/7.398) schlugen fehl.
- Ursache: B219 klemmt `avg_vx/avg_vy` (Cap) unbedingt vor dem Setzen von
  `kinematic_vx`. Beide Tests prüfen die ROHE Geschwindigkeit; ihre Eingaben liegen
  über dem 120/150-km/h-Cap. (Der Wert schwankte 7.398↔5.918 durch geleakten
  globalen `_runtime_cfg`-Cap.)
- Fix: In beiden Tests `_runtime_float_value` für die Cap-Schlüssel via `monkeypatch`
  neutralisieren → Test isoliert die EWMA-Gewichtung/den Optflow-Override; zugleich
  ordnungsunabhängig. Cap-Coverage bleibt in `test_b219_kinematic_speed_cap.py`.

## B225 — Admin-API auf produktiven WSGI-Server (waitress) umgestellt (2026-06-21)
Phase A (Stabilisierung) — **erledigt**.
- Symptom: Admin-Panel stürzt bei häufigem Refresh ab → Re-Login; verstärkt bei
  vielen Zellen. Log: `connect refused` zu `127.0.0.1:5000` im 30-s-Takt
  (16:11–16:15), 8× 502.
- Ursache: `app.run()` = single-threaded Flask-Dev-Server. Karten-Bursts blockieren
  den GIL → Watchdog-Heartbeat-Thread (25 s) verhungert → systemd-Watchdog
  (`WatchdogSec=60`) killt → `RestartSec=30`/`StartLimitIntervalSec=0` → Crash-Loop.
- Fix: `waitress` (reines Python, threaded, in-Process) bedient Requests im
  Thread-Pool; Heartbeat bleibt zuverlässig. In-Process gewählt, damit
  `NotifyAccess=main`/`watchdog_heartbeat` unverändert gültig bleiben (kein
  gunicorn-Fork). `ADMIN_DEBUG=1` → Flask-Debug (threaded); ohne waitress
  `threaded=True`-Fallback. `waitress` in requirements.txt (Phase 5 installiert es).
- Test: `tests/test_b225_admin_uses_waitress.py`.

## B228 — Verifikations-Matching gehärtet: NN-Akzeptanzschwelle (2026-06-22)
- Ursache: Nearest-Neighbor-Matches bis zum vollen Suchradius (25 km) flossen als „verifiziert" ins MAE — auch Fehlzuordnungen zu Nachbarzellen → MAE/Drift aufgebläht.
- Fix: strenge, runtime-pflegbare Schwelle `VERIFICATION_NN_MAX_MATCH_KM`; NN jenseits = Bucket `nn_rejected`, nicht in MAE/Hit-Rate/Drift. ID-/cell_id-Treffer distanzunabhängig gültig (Lineage). Match-Typ-Anteile geloggt.
- Test: `tests/test_b228_nn_match_threshold.py`.

## Z02 — ML-Shadow-Scoring / Re-Gating (geplant, 2026-06-22)
- ✅ erledigt — P52: `prediction.py` Schattenfelder + Schalter `ML_SHADOW_SCORING_ENABLED`
- ✅ erledigt — P53: `accuracy_tracker.py` Schattenverifikation → `breakdown_by_forecast_mode["ml"]`
- ✅ erledigt — P54: Admin/Frontend Champion-vs-Challenger-`ml_mae` grafisch
- Zweck: bricht den verifizierten Gate-Deadlock (ML gegated → kein ML-Forecast → `ml_mae`
  eingefroren → bleibt gegated). Spezifikation: `docs/ML_SHADOW_SCORING.md`.

## B232 — nn_rejected-Zeilen kontaminierten die Fehler-Diagnose (2026-06-22)
- Ursache (Folge von B228): `nn_rejected`-Detailzeilen übergaben `dist_km` → `_detail_record` setzte `forecast_error_km`/`match_distance_km`; `is_valid_forecast_error_detail` wertete sie als verifiziert → MAE/Worst-Listen/Attribution verfälscht.
- Fix: `nn_rejected` übergibt `None` (wie `missed`/`none`); Diagnose schließt `nn_rejected` jetzt explizit als `rejected_match` aus, auch wenn alte Detailzeilen noch eine Distanz oder `missed=true` enthalten. nn_rejected-Zähler/Buckets unverändert.
- Quelle: Codex-Inline-Review PR #783. Test: `tests/test_b232_nn_rejected_no_diag_contamination.py`.

## B233 — Phase-9-Tests verschmutzten das echte API-Tagesbudget (2026-06-22)
- Ursache: `api_budget_guard._BUDGET_FILE` wird zur Import-Zeit gecached; conftest isolierte den Budget-Pfad nicht. `test_b149` (`service="t"` → `example.invalid`) zählte `record_request` in die echte `train_data/evaluation/api_budget.json` (9 Fallback-Events im Admin-Export).
- Fix: `tests/conftest.py` (`_isolate_evaluation_writes`) lenkt `_BUDGET_FILE` pro Test ins tmp — analog zur bestehenden accuracy_tracker-Isolation (B216). Kein Produktionscode geändert.
- Test: `tests/test_b233_budget_isolation.py`.

## P52 — ML-Shadow-Scoring: Challenger im gated branch (2026-06-22)
- Ziel/Z02: ML wird bei Kinematik-Gate im Schatten mitberechnet (kein Zusatz-Inferenz), Felder `forecast_ml_*` auf obj; Champion/`forecasts[]` unveraendert. Schalter `ML_SHADOW_SCORING_ENABLED` (Default True; False = bit-identisch).
- Naechster Schritt: P53 (accuracy_tracker verifiziert Schatten -> `breakdown_by_forecast_mode["ml"]`), dann automatisches Re-Gating.
- Test: `tests/test_p52_ml_shadow_scoring.py`.

## P53 — ML-Shadow-Scoring: Challenger-Verifikation (2026-06-22)
- accuracy_tracker bewertet `forecast_ml_*` gegen dasselbe Actual und bucht ausschliesslich in `by_mode["ml"]` → `breakdown_by_forecast_mode["ml"]["mae_km"]`. Gate `_latest_runtime_mae_by_horizon` erhaelt frische `ml_mae` → Re-Gating (ab `ML_RUNTIME_MIN_SAMPLES_PER_MODE` Schatten-Samples). Deadlock gebrochen.
- Bewusst nur Bucket, kein Detail-Record → keine Diagnose-/Drift-/Global-Kontamination (vgl. B232). Selbst-gated ueber Anwesenheit der `forecast_ml_*`-Felder (P52).
- Naechster Schritt: P54 (Admin/Frontend Champion-vs-Challenger-`ml_mae` grafisch).
- Test: `tests/test_p53_ml_shadow_verify.py`.

## P54 — ML-Lernfortschritt grafisch: Champion vs. Challenger (2026-06-22)
- Getesteter Helper `accuracy_tracker.ml_quality_series` + Endpunkt `/api/ml_quality`; Chart in `Accuracy.jsx` zeigt Champion(Kinematik)- vs. Challenger(ML)-MAE je Horizont ueber die Zeit + Challenger-Sample-Zahl. Erfuellt Zieldefinition „Lernfortschritt/Qualitaet grafisch".
- Schliesst den Z02-Strang ab (P52 Schatten berechnen, P53 verifizieren, P54 darstellen).
- Test: `tests/test_p54_ml_quality_series.py` (Backend). Frontend via Build/Sichtpruefung.

## B227 — Ungültige Zeitstempel mit doppelter Zeitzone (+00:00Z) behoben (2026-06-22)
- Ursache: `isoformat()+"Z"` auf tz-aware datetimes (`datetime.now(timezone.utc)`) erzeugte `...+00:00Z` (`drift_detector.py`, `api_health_check.py`).
- Fix: zentraler Helper `utc_iso_z()` in `utils.py`; betroffene Stellen umgestellt — Format garantiert genau ein `Z`.
- Test: `tests/test_b227_utc_iso_z.py`.

## B229 — Wolkenhöhe durchgängig None: fehlender LAPSE_RATE-Import (2026-06-22)
- Ursache: `LAPSE_RATE` in `cloud_height_from_eumetview.py` nicht importiert → NameError im Grid-Pfad (`fetch_cloud_height_for_points`), vom nackten `except` verschluckt → alle Punkte None bei gemeldetem „Erfolg".
- Fix: `LAPSE_RATE` aus `config` importiert; Resolve-Diagnose (Zähler resolved/out_of_extent/nodata_pixel/warm_clear/error + aufgelöst/gesamt-Log + Record in `eumetview_debug.jsonl`).
- Test: `tests/test_b229_cloud_height_lapse_rate.py`.

## B230 — _utc-Felder enthielten Lokalzeit (2026-06-22)
- Ursache: `forecast_created_at_utc` / `target_timestamp_utc` aus lokalen Radar-Frame-Zeiten (Europe/Vienna) unkonvertiert in `_utc`-Felder geschrieben; verfälschte Diagnose (`forecast_created_in_future` / `verified_before_created` → valide Records verworfen).
- Fix: Helper `_local_naive_to_utc_iso_z` konvertiert lokal → echtes UTC. Dateinamen/`_parse_ts`/Frame-Matching unverändert (lokales Key-System = Design).
- Test: `tests/test_b230_utc_field_semantics.py`.

## B231 — Richtungsfehler: Mindest-Displacement-Schwelle für EWMA-Bewegung (2026-06-22)
- Ursache: Sub-Pixel-Jitter quasi-stationärer Zellen erzeugte verrauschte Richtung in der EWMA-Bewegungsableitung (`prediction._append_kinematic`).
- Fix: `KINEMATIC_MIN_INTERVAL_DISP_PX` filtert sub-threshold Intervalle (Helper `_interval_disp_ok`). Default 0.0 = regressionsneutral; Fallback ungefiltert wenn alle Intervalle sub-threshold.
- Test: `tests/test_b231_min_interval_disp.py`.

## IR-Frühphase / Vorläufer entkoppelt vom Radar-Skip (Juni 2026)

Status: ERLEDIGT

Die IR108-Pipeline läuft nun radarunabhängig über `run_ir_precursor_pipeline()`.
Wenn ARSO-Radar per 304/Content-Hash unverändert ist, prüft der Loop trotzdem
auf ein frisches `train_data/cloud/ir108_*.tif` und aktualisiert IR-Detektionen
sowie IR-Lineage aus dem vorhandenen EUMETView-/Cloud-Height-Cache. Dadurch
entstehen keine zusätzlichen kostenpflichtigen APIs und keine unnötigen
Fremdrequests; ohne frisches TIFF bricht die Pipeline sauber ab.

Die Erkennung ist mehrstufig:
- `ir_watch_candidate`: IR-Frühphase / mögliche Gewitterwolke, öffentlich nur
  bei frischen Daten, Mindestscore und konvektivem Signal.
- `ir_pre_cb`: stärkerer IR-Vorläufer.
- `ir_cb_precursor`: fachlich plausibler CB-IR-Vorläufer.
- `radar_confirmed`: Radar übernimmt die bestehende `cell_id`; der IR-Vorläufer
  wird nicht doppelt als IR-only-Objekt angezeigt.

Höhe ist jetzt Teil von Detektion, Scoring und API-Ausgabe
(`cloud_height_m`, Confidence, Quelle, Trend, `height_stage`, Maximum). Die alte
harte 230-K-Schwelle bleibt als CB-Stufe erhalten, ist für frühe Anzeige aber zu
spät: Bei Standardwerten ca. 290 K Bodentemperatur, 600 m Gelände und 6,5 K/km
Lapse Rate entspricht 230 K ungefähr 9,8 km MSL. Frühphasen beginnen daher
konfigurierbar ab 245 K bzw. ca. 6500 m, aber Höhe allein löst weiterhin keine
harte Gewitterwarnung aus. CB-only bleibt verbindlich: nötig ist mindestens ein
konvektives Signal wie Cooling, Wachstum, Overshooting Top, CAPE/LI-Plausibilität,
Risk-Grid oder späterer Radar-Match. Cirren, Frontbewölkung und alte Ambossreste
werden so nicht als harte Gewitterwarnung eskaliert.

Neue Runtime-/Admin-Werte umfassen u. a. `IR_WATCH_ENABLED`,
`IR_PUBLIC_WATCH_VISIBLE`, BT-/Höhen-/Score-Schwellen und maximale IR-Datenalter.
`CLOUD_HEIGHT_ALERT_THRESHOLD_M` bleibt die Anzeige-Schwelle für „CB > …“; neue
IR-Stufen verwenden keine hartkodierte 10000-m-Grenze. Alle Zellpolygonfarben
bleiben dunkelblau, Unterschiede erfolgen über Label, Badge, Transparenz,
Linienstil und Popup-Felder.

## B234 — Upgrade-rsync löschte train_data/hydro/ (2026-06-22)
- Ursache: `install.sh` (LOCAL/ZIP-Modus, `rsync -a --delete`) schloss `.env`, `users.db`, `runtime_overrides.json`, `statistics/`, `dem/`, `cell_filters/`, `cell_lineage/` aus, jedoch NICHT `train_data/hydro/`. Da `/train_data/` gitignored ist, löschte `--delete` beim Upgrade die Hydro-Impact-Historie (`train_data/hydro/impact/`) und die generierten Geodaten (`train_data/hydro/static/generated/`). Widersprach der Full-Modus-Zusage „NICHT geloescht: train_data/hydro/“.
- Fix: `--exclude=/train_data/hydro/` im rsync-Block ergänzt. Kein anderer Pfad geändert; der Git-basierte Upgrade-Pfad (`git pull`/`reset`) war nie betroffen, da er gitignorierte Daten nicht anfasst.
- Test: `tests/test_b234_install_preserves_hydro.py`.


## B235 — Globales Cycle-Gate sperrte gesamte Hydro-Upstream-Topologie (2026-06-22)
- Ursache: `upstream_by_basin` ist nach `build_upstream_basin_graph` bereits zyklenfrei (cycle-blocked-Kanten entfernt), doch `get_upstream_basin_ids` und das Eligibility-Gate in `hydro_station_index.py` sperrten netzweit bei `cycle_count>0`. In Produktion (638 Zyklen in AT_WATERCOURSELINK) → `impact_eligible_station_count: 0`, Feature inert trotz 4099 confidenter Kanten.
- Fix: `build_upstream_basin_graph` exponiert `cycle_nodes`. `get_upstream_basin_ids` schließt nur noch die zyklus-beteiligte Station selbst aus (per-Station) und nutzt die bereits zyklenfreie BFS-Adjazenz. Eligibility prüft `basin_id not in cycle_nodes` statt globalem `cycle_count==0`. Fachlich konservativ: zyklenfreie Stationen erhalten eine Teilmenge des Upstream-Gebiets (Unter-, nie Über-Attribution); Zyklus-Knoten bleiben über den Basin-Downstream-Fallback unverändert.
- Aktivierung: nach Anwendung Static-Hydro neu aufbauen (Admin „Static-Hydro neu …“ bzw. CLI-Import); `/api/hydro/status` sollte dann `impact_eligible_station_count > 0` zeigen.
- Test: `tests/test_b235_cycle_gate_granular.py`.

## B236 — Static-Hydro-Import im eigenen Prozess (async) (2026-06-23)
- Ursache: `/api/hydro/reload-static` rief `build_static_hydro()` synchron im Waitress-Worker auf; der Rebuild (5756 Basins, 26247 Flowlines) blockierte den Worker, lief in nginx-Timeouts und liess den Admin-Button reaktionslos wirken.
- Fix: reload-static startet den Import als eigenen Prozess via `subprocess.Popen([sys.executable, hydro_static_import.py, "--build-job"], start_new_session=True)` (gespiegeltes B162-Muster), schreibt eine atomare Job-Statusdatei (`train_data/hydro/static/generated/hydro_import_job.json`) und liefert sofort `started`/`already_running`. Neuer `GET /api/hydro/import-status` (public read) meldet running/finished/failed/stale inkl. Lebend-Pruefung des PID. `fetch-live`/`verify` bleiben synchron.
- Test: `tests/test_b236_hydro_import_process.py`; Bestandstest `tests/test_hydro_api.py` auf async-Verhalten angepasst.

## B238 — Hydro-Admin: Spinner/Feedback + Polling des async Imports (2026-06-23)
- Ursache: Die drei Hydro-Admin-Buttons hatten keinen Lade-/Disabled-Zustand, die Meldung wurde weit unten im Editor-Block gerendert (auf Mobilgeraeten unsichtbar) -> Klick wirkte reaktionslos. Nach B236 ist reload-static zudem asynchron.
- Fix: `hydroBusy`/`hydroMsg`-State, Buttons werden waehrend der Aktion deaktiviert und zeigen ein Fortschrittslabel; Inline-Feedback direkt am Button-Block; Backend-Fehlertext via `e.payload.error`. Fuer reload-static pollt das Frontend `GET /api/hydro/import-status`, bis der Import-Prozess fertig/fehlerhaft ist, und aktualisiert danach Stationen/Status.
- Test: `tests/test_b238_hydro_admin_busy_feedback.py`.

## B239 — Hydro-Legende aus der Karte entfernt (2026-06-23)
- Ursache: Die Kartenlegende enthielt einen separaten Hydro-Block (Pegel/pending/confirmed/ambiguous), der entfallen soll.
- Fix: Hydro-Sub-Legendenblock in `MapView.jsx` ersatzlos entfernt. Haupt-Farblegende (Zelltypen/Vorhersagepfeile, gemaess zieldefinition.txt) und Hydro-Marker bleiben unveraendert; `MapFullscreen.jsx` war nicht betroffen.
- Test: `tests/test_b239_hydro_legend_removed.py`.

## P55 — Hydro-Kartenanzeige nach Durchfluss konfigurierbar (2026-06-23)
- Feature: Zwei runtime-konfigurierbare Schwellen `HYDRO_MAP_MIN_Q_M3S` (Anzeige-Filter) und `HYDRO_MAP_MARK_Q_M3S` (Markierung). `station_features(map_view=True)` (Route `/api/hydro/stations?map=1`) blendet Pegel unter dem Mindest-Durchfluss aus und setzt `marked` ab dem Markierungs-Durchfluss; Pegel ohne Live-Durchfluss bleiben sichtbar. Defaults (0.0 / None) sind regressionsneutral. Frontend (MapView + MapFullscreen) hebt markierte Pegel hervor; Admin-Liste und KMZ nutzen `map_view` nicht und bleiben vollstaendig.
- Test: `tests/test_p55_hydro_map_display.py`; Bestandsmocks in `tests/test_hydro_api.py` an die neue Signatur angepasst.

## B237 — Topologie-Diagnose-Bundle im Debug-ZIP (2026-06-23)
- Ursache: Der Debug-Export liess aus `train_data/hydro/static/generated/` nur Status + Stationsindex zu; die fuer die Cycle-/Eligibility-Tiefenanalyse noetige Topologie (Zyklen, Knoten, Kanten-Confidence) lag nur in `hydro_upstream_graph.json`, das aber mehrere MB gross ist (matches ueber 26247 Flowlines) und nicht in jeden Export gehoert.
- Fix: `build_station_index` schreibt zusaetzlich ein groessenbeschraenktes `hydro_upstream_diagnostics.json` (Histogramme, gekappte cycle_nodes<=1000, cycle_sample<=50, not_eligible_sample<=50). Allowlist um `hydro_upstream_diagnostics.json` und das kleine `hydro_static_coverage.json` erweitert; grosse Polygon-/Kanten-GeoJSONs bleiben ausgeschlossen.
- Test: `tests/test_b237_hydro_diagnostics_export.py`.

## P56 — Per-Station-Markierungsschwelle + Admin-Stationsverwaltung (2026-06-23)
- Feature: Markierungs-Durchfluss ist nun pro Station setzbar (`HYDRO_STATION_OVERRIDES[sid].mark_q_m3s`), überschreibt die globale Schwelle `HYDRO_MAP_MARK_Q_M3S`. PATCH `/api/hydro/stations/<id>` akzeptiert `mark_q_m3s` (Zahl ≥ 0 oder null zum Löschen); `station_features` exponiert den Wert und nutzt ihn in der `map_view`-Markierung.
- Bugfix (untrennbar): Admin-Liste lädt mit `include_disabled=1`, sodass abgewählte Pegel sichtbar/re-aktivierbar bleiben; Checkbox- und Schwellwert-Änderungen aktualisieren den lokalen State sofort (kein Neuladen nötig). Zeile von `<label>` auf `<div>` umgestellt, damit der Zahlen-Input die Checkbox nicht toggelt.
- Test: `tests/test_p56_hydro_per_station_threshold.py`.

## P57 — Vorausschauender Hydro-Impact (Forecast-Treffer, Niederschlag × Verweildauer) (2026-06-23)
- Feature: `evaluate_hydro_forecast_impact` nutzt die vorhandenen Zell-Forecast-Positionen (`forecast_lat/lon_{h}`, h=10..60), um Treffer oberliegender Einzugsgebiete im Vorhersagehorizont zu erkennen. Verschiebt die Zellkontur an die Forecast-Position und nutzt dieselbe Upstream-/Eligibility-/Overlap-Logik wie die Ist-Bewertung. Gewichtung: grobe Niederschlagsmenge = Regenrate (`nowcast_rain_rate_1h`, sonst `nowcast_rr_mm15`×4) × Verweildauer (aus Stützstellen t=0+Horizonte) → `estimated_precip_mm`, plus `forecast_impact_score`. Keine neuen Fremdrequests.
- Additiv & standardmaessig aus (`HYDRO_FORECAST_IMPACT_ENABLED=false`); Ergebnisse in `latest_hydro_forecast.json`, Read-Endpoint `GET /api/hydro/forecast-impacts`. Schwellen/Horizonte runtime-konfigurierbar. Bestehende Attribution/Verifikation unberührt.
- Test: `tests/test_p57_hydro_forecast_impact.py`.

## P57 — Drift-Alarm-Mail: diagnostizierter Grund statt statischer Liste (2026-06-23)
- Ursache: send_drift_alert ignorierte das von B214/drift_detector bereits berechnete
  diagnosis_summary (severity/primary_findings/top_recommendation) und zeigte eine fixe,
  nichtssagende Ursachenliste. Zusätzlich wurde "Verschlechterung +{delta} km" immer rot
  gerendert — bei absolut ausgelöstem Drift (delta_km < 0) ergab das "+-9.9 km".
- Fix (email_notifier.py): deutsche Übersetzung der Findings (_DRIFT_FINDING_DE), lesbarer
  Drift-Grund (_DRIFT_REASON_DE), Schweregrad-Label, _build_drift_diagnosis_html-Block in
  der Mail; Verschlechterungszeile nur bei positivem relativem Delta rot, sonst neutraler
  Trend mit Vorzeichen; alle km-Werte via _fmt_km gerundet; statische Liste nur noch als
  Fallback ohne diagnosis_summary.
- Test: tests/test_p57_drift_mail_diagnosis.py.

## B240 — Redaction-Lücke: Benutzername + Telefonnummer im Debug-Export (2026-06-23)
- Ursache: SENSITIVE_KEY_PARTS/_TEXT_ASSIGNMENT_RE in export_security.py deckten weder
  USERNAME/LOGIN noch TWILIO_TO ab → BLITZ_USERNAME=HorstBla und TWILIO_TO=+43... lagen
  im Klartext in config/.env des Debug-Exports (Beleg: Export 2026-06-23).
- Fix: SENSITIVE_KEY_PARTS um "USERNAME","LOGIN","TWILIO_TO" erweitert; gleiche Alternation
  in _TEXT_ASSIGNMENT_RE ergänzt (greift für .env-Klartext via redact_text). Bewusst kein
  bloßes "USER" (USER_AGENT) und keine breite +<Ziffern>-Wertregex. B119-Allowlist
  (MAX_TOKENS) unberührt.
- Test: tests/test_b240_redaction_username_phone.py.

## B242 — Holdout-Metrik misst Modellfehler nicht (roh vs. skaliert) (2026-06-23)
- Ursache: retrain_all übergibt y_holdout aus dataset["y"] (= y_scaled). _compute_holdout_metrics
  vergleicht inverse_transform(preds) (roh) gegen das skalierte y_h → errs misst ~den mittleren
  Positionsbetrag statt des Vorhersagefehlers. Beleg Export 2026-06-23: holdout.mae_px≈217 fast
  konstant über alle Horizonte (208→227), während echter Fehler mit dem Horizont wächst.
  Erklärt die holdout-vs-validation-Diskrepanz (KI-Befund F4) und macht _holdout_ok wirkungslos.
- Fix: in _compute_holdout_metrics y_h ebenfalls via _scaler_y.inverse_transform in den Rohraum
  bringen (NaN-tolerant), dann errs = |preds - y_h_raw|. holdout.mae_px liegt danach im selben
  Rohraum wie evaluate_on_recent → vergleichbar und aussagekräftig.
- Test: tests/test_b242_holdout_metric_unit.py.

## P58 — ML-Ziel-Encoding auf Verschiebung (Delta) (2026-06-23)
- Ursache: ML lernte absolute Zukunftspositionen (targets = fo["x"]/["y"]). Bei begrenzten
  Daten -> Regression zur Karten-Mitte (Shadow h10: hit-rate 1,6 % bei mae 7.62 km).
- Fix: config.ML_TARGET_ENCODING="delta"; dataset_builder encodiert Targets als Verschiebung
  zu seq_objects[-1]; model_training schreibt target_encoding in training_meta;
  prediction._decode_ml_position dekodiert encoding-aware (delta -> obj-Position + Delta).
  prediction liest das Encoding aus dem trainierten Modell (training_meta), Default
  "absolute" -> bestehende Modelle bleiben unverändert (keine Regression bis Neutraining).
- Metrik-Invarianz: Verschiebungsfehler == Positionsfehler -> evaluate_on_recent/Holdout
  bleiben bedeutungsgleich.
- Phasen-Status (Hailo): unverändert; betrifft nur LSTM/LGBM-Kinematik-Vorhersage, nicht die
  geplante U-Net-Radar-Nowcasting-Phase B.
- Test: tests/test_p58_delta_encoding.py. Wirkung erst nach Neutraining (>=50 Sequenzen).

## B243 — Promotion-Gate gegen kinematische Baseline (KI-Befund F4) (2026-06-23)
- Ursache: retrain_all promotete ML nur gegen das vorherige ML (mae_new<mae_old), nie gegen
  den kinematischen Fallback. Dadurch wurde ein Modell aktiviert, das laut Shadow-Scoring
  schlechter als kinematisch ist (h10 ML 7.62 vs kin 4.67 km).
- Fix: _kinematic_baseline_mae berechnet die kinematische Vorhersage (Position + v*Horizont,
  Feature-Idx 0..3) auf denselben recent-Samples; evaluate_on_recent liefert kin_mae_total/
  kin_mae_by_horizon. Neue Reject-Bedingung rejected_below_kinematic_baseline vor beiden
  Promotion-Pfaden: Promotion nur wenn mae_new <= kin_baseline. Encoding-robust (delta|absolute),
  Baseline-Werte in training_meta.validation.
- Test: tests/test_b243_baseline_gate.py.

## B241 — Test-Isolation: external_response_logger (Service "t"/example.invalid) (2026-06-24)
- Status: Neulieferung (war nicht eingespielt).
- Ursache: test_b149 (service="t") schrieb über persist_external_response(base_dir=".")
  echte Dateien nach train_data/external_responses/t/ — Leck in den Debug-Export.
- Fix: autouse-Fixture _isolate_external_response_logger in tests/conftest.py lenkt
  persist_external_response pro Test ins tmp. KI-Befund F6 war Fehldiagnose.
- Test: tests/test_b241_external_response_isolation.py.

## B244 — Null-Threshold mark_q_m3s persistiert durch _deep_merge (2026-06-24)
- Ursache: api_hydro_station_patch (app.py) rief runtime_config.patch({HYDRO_STATION_OVERRIDES:...})
  auf. _deep_merge rekursierte in den Station-Sub-Dict und kopierte mark_q_m3s aus _OVERRIDES
  zurück, obwohl cur.pop("mark_q_m3s") es entfernt hatte. Der alte Schwellwert blieb aktiv.
- Fix: runtime_config.patch_exact_key(top_key, value) ersetzt einen Top-Level-Schlüssel
  vollständig ohne deep-merge; api_hydro_station_patch nutzt patch_exact_key statt patch().
- Reproduziert und verifiziert via Simulation (mark_q_m3s: 150.0 nach Löschung zurückgekehrt).
- Test: tests/test_b244_hydro_null_threshold.py.

## P59 — Optical-Flow-Qualitätsgate: OF-Verwerfung bei großen Frame-Intervallen (2026-06-24)
- Ursache: Lucas-Kanade (pysteps) versagt bei großen Pixelverschiebungen (Radar-Lücken 20-30 min).
  Belegt aus 220k Export-Samples: optflow_fm20 mean=+61.4° (std=5°), fm30 mean=+41.8° — konsistente
  systematische Richtungsfehler (KI-Befund F2: "Forecast direction error probably dominates drift").
  Im Normalbetrieb (fm5.0) ist OF mit mean=-15.7° gut; das Gate greift nur bei Lücken.
- Fix: config.OF_MAX_FRAME_INTERVAL_MIN=8.0 (runtime-overridable). Bei _fm_of>Schwellwert wird
  OF verworfen und auf EWMA/History zurückgefallen; of_error_reason="interval_too_large_fm{x}".
- Test: tests/test_p59_of_interval_gate.py.

## P60 — Prognostizierter Pegel-Abfluss q_forecast (m³/s, Rational-Methode) (2026-06-24)

Status: erledigt. Forecast-Hydro-Events (P57) werden um `q_current_m3s`, `delta_q_m3s`,
`q_forecast_m3s` und `lead_min` angereichert. Berechnung: Δq = C·i·A/3.6 (Rational-Methode),
C=`HYDRO_FORECAST_RUNOFF_COEFF` (0.4), Daempfung=`HYDRO_FORECAST_ROUTING_ATTENUATION` (1.0).
Reine Funktion `hydro_impact.compute_q_forecast_m3s`. Keine zusaetzlichen Fremdrequests.
Voraussetzung fuer P61 (Warngrenzen-Ueberschreitung gemessen/prognostiziert) und die
Hydro-Impact-Visualisierung (P62–P64).

Geplante Folgephasen der Hydro-Impact-Visualisierung:
- P61 (offen): impact_active (binaer: Warngrenze ueberschritten) + impact_source (Info) in station_features.
- P62 (offen): Generat station_river_segments.geojson + GET /api/hydro/impact-segments.
- P63 (offen): GET /api/hydro/affected-places + Popup-Datenfelder.
- P64 (offen): Frontend-Layer (Flussabschnitte, betroffene Orte als Symbol), Popups, Sichtbarkeit.
- P65 (offen): ML-Gate (nur impact_eligible_auto erzeugt Catchment-/Upstream-Hydro-Features).

## P61 — Warngrenzen-Ueberschreitung (binaer) + impact_source (2026-06-24)

Status: erledigt. station_features liefert zusaetzlich q_current, q_forecast (aus P60),
q_threshold (mark_q_m3s je Station bzw. HYDRO_MAP_MARK_Q_M3S global), q_threshold_exceeded (bool)
und impact_source (measured/forecast/both). Bestehendes Feld impact_active (Zell-Overlap) unveraendert.
Grundlage fuer P62 (impact-segments) und P64 (Ortssymbol). Offen: P62, P63, P64, P65.

## P62 — Flussabschnitt-Generat + /api/hydro/impact-segments (2026-06-24)

Status: erledigt. build_station_index schreibt station_river_segments.geojson: je
impact_eligible_auto Station die Vereinigung der Flowlines in {station_basin} u upstream_catchment_ids
(topologisch, kein Hardcode) inkl. segment_length_km. status.river_segment_count ergaenzt.
Neuer Endpoint /api/hydro/impact-segments liefert nur Stationen mit ueberschrittener Warngrenze (P61),
angereichert um q_current/q_forecast/q_threshold/impact_source/updated_at. Offen: P63, P64, P65.

## P63 — Betroffene Orte /api/hydro/affected-places (2026-06-24)

Status: erledigt. impact_segments wurde in geteilte Helfer (_active_segment_features,
_affected_place_rows) refaktoriert (kein Zirkelbezug) und fuellt nun affected_places je Segment.
Neuer Endpoint /api/hydro/affected-places: Watchlist-Orte im Puffer HYDRO_IMPACT_PLACE_BUFFER_KM
(Default 1.0 km) um aktive Abschnitte, mit Popup-Daten (place_name, river, station, impact_source,
q-Werte, distance_to_river_km, distance_to_station_km). Offen: P64, P65.

## P64 — Frontend-Layer Flussabschnitte + betroffene Orte (2026-06-24)

Status: erledigt. MapView.jsx: zwei schaltbare Layer — Flussabschnitte als Polylinie in einheitlicher
Warnfarbe (#dc2626), betroffene Orte als 💧-DivIcon-Symbol (keine Einfaerbung des Punktes). Popups
mit q_current/q_forecast/q_threshold/impact_source/Entfernungen; Stations-Popup um Prognose/Warngrenze
erweitert. JSX mit esbuild validiert. Offen: P65.


## B246 — Drift-Alarm nur bei echter Verschlechterung (2026-06-24)
- Drift ist jetzt strikt eine relative Verschlechterung gegenüber der Baseline: `mae_recent > mae_baseline + DRIFT_MAE_THRESHOLD_KM`.
- Der absolute Kurzhorizont-Grenzwert bleibt als Qualitätsziel erhalten, löst aber keine Drift-Mail mehr aus, wenn das Modell stabil ist oder sich verbessert.
- `/api/drift` bleibt kompatibel und ergänzt `model_status`, `quality_target_met`, `quality_status` und `quality_message` für Dashboard-Hinweise.
- Alarm-Mails mit Betreff `⚠️ WetterExtended – Model-Drift erkannt` werden ausschließlich bei echtem relativen Drift versendet.

### B238 — Automatische Forecast-Qualitätsdiagnose vor jedem 24h-Export ✅
- Zentraler Pre-Export-Hook `run_forecast_quality_diagnosis_before_export()` startet vor dem Debug-ZIP-Build die lokale Diagnose `tools/diagnose_forecast_quality.py --hours 24`.
- Ergebnisdateien bleiben stabil ohne Timestamp: `forecast_quality_diagnosis_latest.json` oder bei Fehlern `forecast_quality_diagnosis_error.json`; Fehler blockieren ZIP-/Git-Export nicht.
- Admin-Panel „Genauigkeit" liest die JSON-Datei über `/api/forecast_quality_diagnosis`; keine Browser-Neuberechnung.
- Debug-ZIP und Force-Push-Export-Branch enthalten die Diagnose; keine zusätzlichen Internet- oder API-Requests.
- Drift-Mail bleibt getrennt und wird weiterhin nur bei relativer Verschlechterung über Threshold ausgelöst.
- Tests: `tests/test_forecast_quality_export_diagnosis.py`.

## B247 — Verifikations-Matching: Speed-Gate + Core-Anforderung (2026-06-25)
- `_match_valid_b247(obj, matched, horizon_min)`: prüft ID-/cell_id-/NN-Matches auf zwei Bedingungen:
  1. Implizite Ist-Geschwindigkeit (Origin→Actual) ≤ `VERIFICATION_MATCH_MAX_ACTUAL_SPEED_KMH` (120 km/h, runtime-überschreibbar).
  2. Wenn Origin konvektiv (core_ratio > 0): Actual muss ebenfalls core_ratio ≥ `VERIFICATION_CORE_MIN_RATIO` besitzen.
- Besteht ein ID-/cell_id-Match die Validierung nicht, wird auf NN-Suche zurückgefallen (Ghost-Match wird verhindert, nicht nur markiert).
- Behebt: 5.659 High-Speed-Matches (>120 km/h) und 1.874 Merge-Ghost-Matches in `forecast_error_details.jsonl` (max 515 km/h, p99=143 km/h).
- Neue Konstanten `VERIFICATION_MATCH_MAX_ACTUAL_SPEED_KMH` und `VERIFICATION_CORE_MIN_RATIO` in `config.py` (runtime-überschreibbar).
- Tests: `tests/test_b247_match_speed_gate.py`.

## B248 — Log-Rotation: forecast_error_details.jsonl + external_responses (2026-06-25)
- `_prune_eval_jsonl_by_age` erkennt jetzt `verified_at_utc` und `forecast_created_at_utc` als Zeitstempel-Felder (zusätzlich zu `ts`/`ts_utc`).
- `forecast_error_details.jsonl` (511 MB, 407k Zeilen) wird nun täglich auf `EVAL_LOG_RETENTION_HOURS=48` rotiert.
- `train_data/external_responses/` zu `DATA_CLEANUP_PATHS` hinzugefügt mit 2-Tage-Retention-Override (2.079 Dateien/Tag, ~4 MB/Tag auf Pi 5); Cleanup läuft rekursiv durch Service-Unterverzeichnisse.
- `cleanup_log.jsonl` zeigte `eval_lines_pruned=0` trotz aktivierter Rotation — Ursache war fehlendes `verified_at_utc`-Handling.
- Tests: `tests/test_b248_forecast_detail_rotation.py`.

## B249 — DEM/Weather-Features in forecast_error_details.jsonl (2026-06-25)
- `_detail_record()` in `accuracy_tracker.py` schreibt jetzt DEM- und Wetter-Features aus dem Forecast-Objekt in jede Verifikationszeile.
- DEM-Felder: `dem_elevation_m`, `dem_slope_toward_cell`, `dem_barrier_ahead`, `valley_alignment`, `terrain_blocking_score`, `orographic_lift_score`.
- Wetter-Felder: `wind_speed_700hPa`, `wind_dir_cos`, `wind_dir_sin`, `cape`, `arome_li`, `arome_t2m`, `wind_speed_500hPa`, `nowcast_rr_mm15`, `lightning_count_10km`.
- Zusätzlich: `kinematic_speed_kmh`, `core_ratio`, `area` für Fehler-Attribution.
- Behebt: `forecast_quality_diagnosis_latest.json` meldete `dem_orography.missing_ratio=1.0` und `weather_features.missing_ratio=1.0` — Features waren im Objekt vorhanden, aber nicht in das JSONL geschrieben.
- Tests: `tests/test_b249_detail_record_features.py`.

## B250 — Train/Serve-Mismatch: Feature-Namen-Persistenz + Konsistenz-Check (2026-06-25)
- `training_meta.json` speichert jetzt `feature_names` (vollständige Feature-Liste in Trainings-Reihenfolge: ML_CELL_FEATURES + ML_STATION_FEATURES + time).
- `prediction.py` prüft beim Modell-Load ob die aktuelle Feature-Liste identisch mit `training_meta.feature_names` ist.
- Bei Mismatch: kritische Log-Warnung mit erstem Abweichungspunkt + Force-Kinematik für alle Objekte des Laufs.
- Kein Mismatch-Check für alte Modelle ohne `feature_names` in `training_meta` (rückwärtskompatibel).
- Behebt die Diagnose-Grundlage für: ~160 km Runtime-MAE trotz val_loss≈0.40 (Train/Serve-Skew).
- Ein nach B250 trainiertes Modell mit unveränderter Feature-Liste aktiviert die ML-Vorhersage wenn auch der ML-Runtime-Gate (B243) durchlässt.
- Tests: `tests/test_b250_feature_consistency.py`.

## B251 — Lineage-State-Integrität: Timestamp-Order, radar_confirmed, recycled cell_id, ended-Flag (2026-06-26)
- F1: `_normalize_state()` repariert `last_seen < first_seen` (auf `first_seen` zurücksetzen).
- F2: `_normalize_state()` repariert `radar_confirmed=true` ohne `radar_track_id` (auf `ir_precursor` zurücksetzen).
- F3: `ensure_ir_track_cell_id()` prüft vor Wiederverwendung einer bestehenden `cell_id`, ob die Zelle bereits ended (`ended_at`/`ended_without_radar`/`label_written`); abgelaufene IDs werden verworfen und eine frische `WX-<datum>-NNNN` vergeben.
- F4: `ended=True` wird konsistent gesetzt: in `_normalize_state()`, in `finalize_expired_ir_precursors()` und im positiven-Label-Pfad.
- `confirm_ir_radar_match_in_lineage()` setzt `radar_confirmed=True` nur bei nicht-leerem `radar_track_id`.
- Test: `tests/test_b251_lineage_integrity.py`.

## B252 — IR-Track Ausalterung an Observation-Timestamp + Kurzintervall-Freshness (2026-06-26)
- F5: `ir_cell_tracking.py` zählt in `stale_obs_cycles`, wie oft aufeinanderfolgend `tiff_file` + `observation_timestamp` identisch geblieben sind. Nach `IR_MAX_STALE_OBS_CYCLES` (Default 2) eingefrorenen Zyklen wird `missing` inkrementiert und `motion_quality="stale_obs"` gesetzt. Verhindert dauerhaftes `missing=0` bei eingefrorenen TIFF-Tracks.
- F6: `risk_watch.risk_watch_active()` prüft zusätzlich zur Datei-mtime den `observation_timestamp` jedes IR-Tracks. Tracks mit Observation älter als `IR_MAX_DATA_AGE_MIN` werden für den Kurzintervall-Trigger ignoriert.
- Test: `tests/test_b252_ir_track_stale_obs.py`.

## B253 — CB-Klassifikation Konfidenz-Gate + first_height_alert_timestamp fixieren (2026-06-26)
- F7: `classify_height_stage()` in `ir_cell_detection.py` erhält neue Parameter `cloud_height_confidence` und `cloud_height_source`. CB-Stufen (`pre_cb`/`cb`/`severe_cb`) werden nur vergeben, wenn `confidence >= IR_CB_MIN_HEIGHT_CONFIDENCE` (Default 0.5, regressionsneutral bei 0.0) und `source != "default_fallback"`. Verhindert CB-Einstufung allein aus Fallback-Höhen.
- `config.py`: `IR_CB_MIN_HEIGHT_CONFIDENCE = 0.5` (runtime-überschreibbar).
- F8: `first_height_alert_timestamp` wird in `ir_cell_detection.py` nicht mehr gesetzt (immer `None`); in `ir_cell_tracking.py` wird er exakt einmalig beim ersten Überschreiten der Höhenschwelle gesetzt und danach nie überschrieben.
- Test: `tests/test_b253_cb_confidence_gate.py`.

## B254 — Steuerwind-Fallback für IR-Vorläufer ohne Bewegungsableitung (2026-06-26)
- F9: `_forecast_fields()` in `ir_cell_tracking.py` nutzt bei `vx == vy == 0` den 700-hPa-Steuerwind aus dem Track (`wind_speed_700hPa`, `wind_dir_cos`, `wind_dir_sin`), um eine Bewegungsprognose abzuleiten (70 % der Windgeschwindigkeit als Zellgeschwindigkeit). `forecast_mode = "steering_wind"`, `forecast_confidence = 0.35`. Alle Zeithorizonte zeigen damit sinnvolle Positionen statt der Ist-Position.
- Neu-Track-Anlage übernimmt Wind-Felder aus der Detektion.
- Test: `tests/test_b254_steering_wind_fallback.py`.

## B256 — `api_call_counts.jsonl` Body-Truncation (2026-06-29)
- **Problem:** `log_api_call()` speichert vollständige Response-Bodies ohne Größenbegrenzung.
  GeoSphere-CAPE liefert 4.278 GeoJSON-Features pro Aufruf → 2,3 MB/Eintrag;
  `api_call_counts.jsonl` wuchs auf **254 MB/Tag** (153 MB allein CAPE).
- **Fix:** Neuer Config-Parameter `LOG_API_RESPONSE_MAX_CHARS = 4000` (runtime-überschreibbar).
  `_truncate_body()` in `log_api_call()` kürzt `body_json` (JSON-serialisiert) und
  `body_text` auf diesen Wert; `truncated: true` im Log-Eintrag. Binäre Antworten
  (KMZ, TIFF) bleiben unberührt. 0 = keine Begrenzung.
- **Dateien:** `config.py`, `debug_utils.py`, `tests/test_b256_api_log_truncation.py`

## B257 — Diagnose-Report: Feature-Namen an aktives Schema koppeln (2026-06-27)
- `build_diagnosis()` prüfte Legacy-Schlüssel (`wind_speed`, `temperature`, `grosswetterlage`, `valley_alignment_score`, `valley_channeling_score`) und meldete befüllte Features fälschlich als 100 % missing.
- `terrain`/`weather` jetzt exakt an die von `accuracy_tracker._detail_record` (B249) geschriebenen Spalten gekoppelt (`wind_speed_700hPa`, `wind_speed_500hPa`, `cape`, `arome_li`, `arome_t2m`, `nowcast_rr_mm15`, `lightning_count_10km`, `valley_alignment`, …).
- Beseitigt falsche „alles fehlt"-Befunde; echte Defizite (z. B. konstant-0 Gelände-Features) werden nicht mehr verdeckt.
- Test: `tests/test_b257_diagnosis_feature_schema.py`.
- Erledigt.

## B258 — forecast_error_details.jsonl: Dedup über Scheduler-Läufe hinweg (2026-06-27)
- `evaluate_for_horizon()` setzte `detail_keys_seen` pro Lauf auf `set()` zurück → jede Verifikation wurde im 24-h-Fenster bei jedem Lauf erneut angehängt (~20× pro Tag); Statistiken/Outlier wurden verfälscht.
- Neue Funktion `_load_detail_keys()`; `detail_keys_seen` wird beim Start aus der bestehenden Datei vorgeladen → jede Forecast-Verifikation wird genau einmal geschrieben.
- Test: `tests/test_b258_detail_dedup.py`.
- Erledigt.

## P66

| Nummer | Titel | Beschreibung | Dateien | Status |
|---|---|---|---|---|
| P66 | **Multi-Core-Split** | Erkennt Radar-Blobs mit mehreren räumlich getrennten Konvektionskernen (≥2 rot/violett-Zonen mit ≥2.4 km Abstand) und teilt sie via Voronoi-Partitionierung in unabhängige Sub-Zellen auf. Jede Sub-Zelle erhält einen eigenen Kalman-Track, Geschwindigkeitsvektor und Core-Ratio. Konfigurierbar über `MULTI_CORE_SPLIT_ENABLED`, `MULTI_CORE_MIN_CORE_AREA_PX`, `MULTI_CORE_MIN_DIST_PX`, `MULTI_CORE_MIN_CHILD_AREA_PX` in `runtime_overrides.json`. Neue Hilfsfunktionen: `_detect_core_components`, `_voronoi_split`. | `object_tracking.py`, `config.py`, `tests/test_p66_multi_core_split.py` | ✅ erledigt |

## B263 — IR→Radar-Matching: Logik-Inversion in `select_ir_radar_matches` (2026-06-29)

**Datei:** `cell_lineage.py`  
**Problem:** Guard `if _real_cell_id(robj.get("cell_id")): continue` filterte
**alle** Radar-Objekte heraus, da `object_tracking.py` jeder Zelle eine
`WX-`-ID vergibt. Folge: 987 IR-Zellen über 24 h, 0 jemals radar-bestätigt
(`ir_precursors.matched_count = 0` im Export). Alle IR-Features ohne
Lerngrundlage.  
**Fix:** Guard-Bedingung geändert auf `lineage_status == "radar_confirmed"` —
überspringt nur bereits in diesem Zyklus bestätigte Objekte, nicht alle
mit einer cell_id.  
**Tests:** `tests/test_b263_ir_radar_matching.py`

## B259 — Radarframes: Archivierung ohne `radar_`-Präfix (2026-06-29)

**Datei:** `object_tracking.py`<br>
**Problem:** `process_frame()` archivierte Frames als `radar_TIMESTAMP.png` in
`data/radar/` und `train_data/radar/`. `accuracy_tracker._parse_ts()` erwartet
`%Y-%m-%d_%H-%M-%S` ohne Präfix; präfixbehaftete Frames wurden mit `None`
geparst und fielen aus der Verifikation heraus (Beweis: 223 Präfix-Frames neben
159 Nicht-Präfix-Frames im debug3-Export).<br>
**Fix:** `f"radar_{timestamp}.png"` → `f"{timestamp}.png"` an beiden
Archivierungsstellen (Zeilen 1781, 1787). Zeile 1768 (`filename.replace("radar_", "")`)
bleibt für Rückwärtskompatibilität erhalten.<br>
**Tests:** `tests/test_b259_radar_filename.py`

## B260 — Verifikations-Zeittoleranz adaptiv an gemessene Radar-Kadenz (2026-06-29)

**Datei:** `accuracy_tracker.py`  
**Problem:** `_effective_target_tolerance_s()` nutzte den statischen
`FRAME_INTERVAL_MIN=5.0` (→ 150 s). Bei ARSO-15-min-Kadenz (nachts/vormittags)
fanden Kurz-Horizont-Forecasts keinen Zielframe (ratio=0.3974 im Export).
**Fix:** `_effective_target_tolerance_s()` misst den Median der tatsächlichen
Inter-Frame-Abstände aus dem übergebenen `by_ts`-Dict; `_find_target_frame()`
übergibt dieses Dict. Bei 15-min-Kadenz steigt die effektive Toleranz auf
≥450 s.  
**Tests:** `tests/test_b260_adaptive_tolerance.py`

## B261 — `api_health.jsonl`: Test-Telemetrie-Einträge herausfiltern (2026-06-29)

**Datei:** `debug_utils.py`
**Problem:** `log_api_failure()` schrieb Sentinel-Einträge (`service="t"`,
`url="example.invalid"` aus `test_b149_retry_get_breaker.py`) in die
Produktionsdatei, wenn die conftest-Fixture `_isolate_api_health_log`
nicht griff. Im debug1-Export: 9 von 217 Einträgen betroffen.
**Fix:** Guard am Anfang von `log_api_failure()`: `service == "t"` oder
`"example.invalid"` in URL → sofortiges `return` ohne Datei-Schreibzugriff.
**Tests:** `tests/test_b261_health_log_isolation.py`

## B262 — RISK-WATCH: Retry mit Backoff bei lokalem HTTP-Timeout (2026-06-29)

**Datei:** `main.py`  
**Problem:** `_risk_alert_check()` brach bei einem einzigen `ReadTimeout`
auf `127.0.0.1:5000/api/risk_grid` sofort ab. Im Export-Log:
`Read timed out. (read timeout=5)` um 05:27:55 — Service war aktiv,
Retry hätte gereicht.  
**Fix:** Retry-Loop mit 2 Versuchen (Pause 1 s nach erstem Fehler); erst
nach dem zweiten Fehlschlag wird abgebrochen. Kein Absturz, kein Alarm-Verlust
bei kurzer Überlast.  
**Tests:** `tests/test_b262_risk_watch_retry.py`

## B264 — `test_b262_risk_watch_retry.py`: State-Leak durch rohes `setattr` behoben (2026-06-29)

**Datei:** `tests/test_b262_risk_watch_retry.py` (vollständige Ersetzung)
**Problem:** Codex-generierter Helper verwendete `setattr(mod, attr, value)` ohne
Cleanup. `runtime_config.get` blieb nach B262-Tests als default-only-Lambda in der
Modul-Referenz stehen. `test_p2_2_config_health::test_valid_json_clears_error` las
dadurch `15` statt `20` (Codex-Review-Badge P2).
**Fix:** Alle 5 Tests nutzen ausschließlich `monkeypatch.setattr()`. pytest stellt
alle Attribute nach jedem Test automatisch wieder her. Kein rohes `setattr()` mehr.
**Verifiziert:** `test_b262 → test_p2_2` in Reihenfolge → 9/9 grün, kein State-Leak.

## B257 — `tools/diagnose_forecast_quality.py`: Legacy-Feldnamen `accuracy_history.jsonl` (2026-06-29)
- **Problem:** `_read_accuracy_history_horizons()` greift auf Top-Level-Felder
  `rec.get("horizon")`, `rec.get("mae_km")` zu. `evaluate_all()` schreibt seit
  einem früheren Refactor das verschachtelte Format
  `{"horizons": [{"horizon": 10, "mae_km": ...}]}`.
  Alle 95 History-Einträge lieferten `horizon=None` → `model_usage: "not_available"`.
- **Fix:** `_read_accuracy_history_horizons()` prüft zuerst `rec.get("horizons")`
  (neues Format) und iteriert die Liste; Fallback auf altes Flat-Format
  `rec.get("horizon")`. Parent-Kontext-Felder (z.B. `timestamp_utc`) werden in
  jeden Horizont-Dict gemergt.
- **Dateien:** `tools/diagnose_forecast_quality.py`,
  `tests/test_b257_diagnose_history_format.py`

## B258 Follow-up — `forecast_error_details.jsonl`: since_hours-Fenster für Dedup-Keys (2026-06-29)
- **Problem:** `_load_detail_keys()` lud persistierte Detail-Keys ohne Zeitfenster. Damit war der Scheduler zwar laufübergreifend idempotent, aber das Key-Set entsprach nicht dem `since_hours`-Fenster von `evaluate_for_horizon()`.
- **Fix:** `_load_detail_keys(path, since_hours)` berücksichtigt jetzt `verified_at_utc` und lädt nur Keys innerhalb der letzten `since_hours` Stunden. `evaluate_for_horizon()` übergibt sein aktuelles Fenster an die Hilfsfunktion.
- **Tests:** `tests/test_b258_detail_no_duplicates.py` prüft den zweiten Scheduler-Lauf, das Laden aktueller Keys, das Ausschließen alter Keys und den leeren Rückgabewert bei fehlender Datei.

## B259a — `object_tracking.py`: ARSO-KML-Timestamp Sanity-Check (Fallback Systemzeit) (2026-06-29)
- **Problem:** ARSO-Server lieferte frischen Radarinhalt (SHA256 geändert →
  `download_kmz()=True`, Zellen erkannt, Starkregen-Warnung), aber
  `<TimeStamp><when>` im KML blieb auf `2026-06-29T07:05:00Z` (09:05 CEST)
  eingefroren. `detect_and_track_objects()` speicherte jede neue PNG mit
  demselben Timestamp (Überschreiben). `api_radar_frames` filterte diesen
  einzigen Frame als zu alt heraus → leere Liste → kein Radar-Overlay.
- **Fix:** Nach `get_acquisition_timestamp()` neuer Skew-Check: ist der Timestamp
  mehr als `RADAR_TIMESTAMP_MAX_SKEW_MIN` (Default 30 min, runtime-überschreibbar)
  älter als Systemzeit, wird `datetime.now()` als Dateiname-Basis verwendet.
  `get_acquisition_timestamp()` selbst bleibt unverändert (liefert weiter den
  besten verfügbaren ARSO-Timestamp). Skew-Check nur im Live-Modus (`"latest"`
  im Dateinamen). 0 = deaktiviert.
- **Dateien:** `config.py`, `object_tracking.py`,
  `tests/test_b259_radar_timestamp_skew.py`

## B265 — Radar-Reader auf präfixloses Dateinamen-Schema angleichen (2026-06-30)

**Dateien:** `app.py`, `main.py`, `movement_gif.py`
**Problem:** B259 stellte nur den Writer (`object_tracking.py`) auf präfixlose
Frame-Namen `{timestamp}.png` um. Die Reader suchten weiter nach `radar_*.png`
bzw. `f"radar_{ts}.png"` an 10 Stellen (app.py: 623/719/724/800/1497/3315/4326,
main.py:594, movement_gif.py:28/31). Folge ab 2026-06-29 ~09:10 UTC: `/api/radar_image`
und `/api/radar_frames` fanden keine neuen Frames → Radar-Overlay eingefroren auf
09:05 bzw. Fallback `data/latest.png`; Optical Flow meldete `prev_radar_missing`.
Beleg: im Debug-Export koexistieren `radar_*_09-05-00.png` (alt) und
`*_09-10-00.png` (neu) im selben Verzeichnis.
**Fix:** Explizite Pfade `f"radar_{...}.png"` → `f"{...}.png"`; Glob-Muster
`"radar_*.png"` → `"[0-9]*.png"` (matcht ausschließlich präfixlose Timestamp-Frames,
keine Doppeltreffer während der Migration). Quelle der Wahrheit:
`object_tracking.py` + `cleanup_radar_names.sh`.
**Tests:** `tests/test_b265_radar_reader_filename.py` (+ `test_b259_radar_filename.py`
bleibt grün).

## B266 — `cleanup_radar_names.sh` auf `data/radar/` (Live-Verzeichnis) erweitert (2026-06-30)

**Datei:** `cleanup_radar_names.sh` (vollständige Ersetzung)
**Problem:** Das Skript bereinigte seit B259 nur `train_data/radar/`
(`SAVE_PATHS["radar"]`, das Trainingsarchiv). Das Live-Serving-Verzeichnis
`data/radar/`, aus dem `app.py` (`/api/radar_image`, `/api/radar_frames`) und
`movement_gif.py` lesen (siehe B265), hatte dieselbe `radar_*.png`-Altlast,
wurde aber nicht erfasst — verwaiste Dateien blieben dauerhaft liegen.
**Fix:** Skript auf eine Schleife über `RADAR_DIRS=(train_data/radar data/radar)`
umgebaut; identisches Umbenenn-/Dedup-Verhalten pro Verzeichnis, explizites
`[SKIP]`-Logging falls ein Verzeichnis fehlt. Funktional rein additiv — B265
funktionierte bereits ohne dieses Skript korrekt (Glob `[0-9]*.png` ignoriert
Altdateien), B266 ist reine Datenhygiene.
**Tests:** `tests/test_b266_cleanup_radar_dirs.py` (End-to-End gegen temporäre
Verzeichnisstruktur: Umbenennung, Dedup, fehlendes Verzeichnis, Idempotenz).


## B267 — `test_lightning_api.py`: stale Radar-Fixture nach B265 korrigiert (2026-06-30)

**Datei:** `tests/test_lightning_api.py` (eine Zeile)
**Problem:** `api_lightning()`s Fallback-Zeitreferenz liest seit B265 das
jüngste Radarbild über den präfixlosen Glob `[0-9]*.png`. Die Testfixture
legte noch eine präfixbehaftete Datei (`radar_2026-06-09_14-00-00.png`) an —
ein Rest aus der Zeit vor B259, der vor B265 nur deshalb funktionierte, weil
auch der Produktionscode noch den alten (falschen) Glob nutzte. Nach B265
(korrekt an den B259-Writer angeglichen) fand der Test seine eigene Fixture
nicht mehr → Fallback auf echte Systemzeit → Assertion-Fehler
(`count == 0` statt `1`). Per echtem Testlauf reproduziert und nach Fix
verifiziert (siehe B265/B267-Verifikationsprotokoll).
**Fix:** Fixture-Dateiname auf `2026-06-09_14-00-00.png` (ohne Präfix)
geändert — entspricht der seit B259 tatsächlich geschriebenen Konvention.
Kein Produktionscode geändert.
**Tests:** `tests/test_lightning_api.py` (beide Tests grün).


## B268 — Merge-Lineage: etablierte cell_id wird nicht mehr von frisch entstandener Zelle überschrieben (2026-06-30)

**Datei:** `cell_lineage.py`, Funktion `update_split_merge_lineage()`
**Problem:** Beim Verschmelzen zweier Zellen wählte die `cell_id` des
Survivors ausschließlich `select_primary_merge_parent()`
(`CELL_LINEAGE_PRIMARY_MERGE_POLICY = "highest_core_ratio"`), unabhängig
davon, ob der Tracking-Survivor (`obj["id"]`) selbst bereits einer der Parents
mit eigener, etablierter `cell_id` war. Eine frisch entstandene, momentan
kompaktere Zelle konnte dadurch die Identität einer etablierten, seit
Stunden getrackten Zelle übernehmen; die abgeschmolzene Zelle lief parallel
als `silent_tracking`-Geisterzelle unter derselben `cell_id` weiter (Live-Beleg
2026-06-29: Zelle 8ZAOEUFJ verlor `WX-20260629-0209` an die 5 Minuten alte
Zelle `WX-20260629-0216`, Doppelbelegung 3,5 Std., 12 betroffene cell_ids,
146 Snapshot-Vorkommen im Tagesexport). Die öffentliche Karte war nicht
betroffen (`is_public_cell()` filtert die Geisterzelle bereits korrekt), wohl
aber Statistik/Verifikation, die nach `cell_id` joint.
**Fix:** Hat der Survivor (`_obj_track_id(obj)`) bereits vor dem Merge eine
eigene `cell_id` in `state["radar_to_cell"]`, die unter den Merge-Parents
ist, hat diese Identitätskontinuität Vorrang vor der core_ratio-Policy. Ohne
eigene Vorgeschichte (frisch generierte id) bleibt das bisherige
core_ratio-Fallback-Verhalten unverändert.
**Tests:** `tests/test_b213_split_merge_lineage.py` — 2 neue Testfälle
(Identitätserhalt bei etabliertem Survivor; unverändertes Fallback bei
frischer Survivor-id), alle 10 bestehenden Tests weiterhin grün.

## B269 — Test-Isolation: sys.modules-Stubs aus test_b121 leakten in spätere Testdateien (2026-06-30)

**Datei:** `tests/test_b121_tracking_snapshot.py`
**Problem:** `_install_import_stubs()` installierte Fake-Module (u. a.
`radar_download` ohne `download_kmz`) per roher `sys.modules[...]`-Zuweisung
am Modul-Level, ohne `monkeypatch` und ohne Cleanup. Da diese Datei
alphabetisch vor `test_b177_radar_skip_reason.py` kollektiert wird und als
erste den `radar_download`-Import auslöst, blieb der unvollständige Stub für
den Rest des pytest-Prozesses bestehen → `AttributeError:
module 'radar_download' has no attribute 'download_kmz'` bei vollständigen
Suite-Läufen (isoliert lief der betroffene Test immer grün). Minimal
reproduziert mit `pytest tests/test_b121_tracking_snapshot.py
tests/test_b177_radar_skip_reason.py`.
**Fix:** `_install_import_stubs()` gibt die tatsächlich neu eingefügten
Modulnamen zurück; eine modul-gescopte `autouse`-Fixture entfernt sie nach
Abschluss aller Tests dieser Datei wieder aus `sys.modules`, sodass später
kollektierte Dateien einen echten Import erhalten.
**Tests:** `tests/test_b121_tracking_snapshot.py` (alle 8 bestehenden Tests
weiterhin grün) + `tests/test_b177_radar_skip_reason.py` (3/3 grün in
Kombination, vorher 1 Fehlschlag).

## P67a — Q-Trend-Anzeige

Die Hydro-Flood-Bewertung berechnet zusätzlich zur Hochwasserheuristik eine lokale Q-Tendenz pro Pegelstation. Die Berechnung nutzt ausschließlich die bereits persistierte Datei `train_data/hydro/live/hydro_history.jsonl`; es werden keine zusätzlichen Fremdrequests und keine neuen Datenquellen verwendet.

Technische Eckpunkte:

- Pro Bewertungszyklus wird die Historie einmal per Tail-Read geladen. Dabei werden nur die letzten ca. 400 KB der JSONL-Datei gelesen.
- Verwendet werden nur Messwerte innerhalb des konfigurierbaren Lookback-Fensters `HYDRO_TREND_LOOKBACK_MIN` (Standard: 65 Minuten).
- Für 10, 30 und 60 Minuten wird der aktuelle Durchfluss mit dem nächstliegenden historischen Q-Wert verglichen. Die maximale Toleranz für den Vergleichswert beträgt 5 Minuten.
- Die Trendklassifikation lautet `rising`, `falling`, `stable` oder `insufficient_history`.
- Die Schwellen `HYDRO_TREND_MIN_DELTA_M3S` und `HYDRO_TREND_MIN_DELTA_REL_PCT` sind runtime-fähig. Änderungen darunter werden als `stable` gewertet.
- `evaluate_live_flood_risk()` exponiert die Trendfelder im Cache `latest_hydro_flood_risk.json`; `hydro_api.py` merged diese Felder nach `/api/hydro/stations` und berechnet sie dort nicht erneut.

Exponierte Felder:

- `current_q_trend_10min`
- `current_q_trend_30min`
- `current_q_trend_60min`
- `q_trend_per_hour`
- `already_rising_flag`
- `q_trend_status`
- `q_trend_delta_m3s`
- `q_trend_reference_window_min`

## P67b — Hochwassergefahr-Icon am Pegel-Punkt

`/api/hydro/stations` übernimmt `flood_expected` direkt aus dem bestehenden Cache `train_data/hydro/impact/latest_hydro_flood_risk.json`. Der Wert wird pro `station_id` in die Stations-Properties gemerged; fehlt der Cache oder enthält er keine passende Station, liefert die API `flood_expected: null`. Die Stations-API berechnet die Flood-Risk-Bewertung dabei nicht neu und löst keine zusätzlichen Fremdrequests aus.

In `MapView.jsx` und `MapFullscreen.jsx` ersetzt ein Inline-SVG-Warnsymbol den normalen Hydro-Pegel-Kreis, sobald `flood_expected === true` ist. Das Symbol wird als Leaflet-`divIcon` im Code definiert und besteht aus rotem Warnkreis, weißem Rufzeichen und zwei roten Wellen. Die Popup-Inhalte, Catchment-Klicks und Hydro-Impact-Linien bleiben unverändert erhalten; bei Hochwassergefahr wird kein zusätzlicher Kreis am selben Punkt gerendert.

## B271 — Flood-Risk/Trend-Cache lief nie ohne geöffnetes MapView (2026-06-30)

**Datei:** `hydro_fetch.py`
**Problem:** `evaluate_live_flood_risk()` wurde ausschließlich lazy über
die Route `/api/hydro/flood-risk` ausgelöst, die nur `MapView.jsx` pollt.
`MapFullscreen.jsx` und jeder Scheduler-Lauf lasen den Cache nur, lösten
aber nie eine Neuberechnung aus. Live verifiziert: `latest_hydro_flood_risk.json`
existierte nach mehreren Betriebsstunden überhaupt nicht.
**Fix:** `evaluate_live_flood_risk(live=result)` direkt im Erfolgspfad von
`fetch_hydro_live()` ausgelöst (gleiche Stelle wie `append_hydro_history()`),
robust mit `try/except`. `cells` wird hier bewusst nicht mitgegeben
(Niederschlag/Einzugsgebiet bleibt dann "nicht bewertbar", Q-Trend/
Hochwassergefahr unabhängig davon korrekt).
**Tests:** `tests/test_b271_hydro_fetch_triggers_risk_eval.py` (2 neue
Tests) + `tests/test_hydro_fetch.py`, `tests/test_hydro_flood_ml.py`
weiterhin grün (22/22 lokal verifiziert).

## B270 — Q-Trend-Historie filterte gegen Wanduhrzeit statt Messzeitpunkt (2026-06-30)

**Datei:** `hydro_flood_ml.py`, `config.py`
**Problem:** `_recent_q_history_by_station()` bzw. die aktuelle Q-Trend-Historienladung verwarf Historie-Zeilen anhand eines Cutoffs `datetime.now(timezone.utc) - 65min`. Die Trendfenster werten aber relativ zum Messzeitpunkt der aktuellen Live-Station aus, nicht relativ zur echten Wanduhrzeit. Bei jeder Abweichung zwischen Messzeitpunkt und "jetzt" (Fetch-Lag, verzögerte Auswertung) wurde dadurch vorhandene, relevante Historie faelschlich ausgeschlossen.
**Fix:** Cutoff vollständig entfernt, Begrenzung nur noch über das bestehende Byte-Tail-Budget (400 KB). `HYDRO_TREND_LOOKBACK_MIN` (nur für den Cutoff verwendet) aus `config.py` entfernt.
**Tests:** `tests/test_p67_hydro_trend.py` (Regression gegen Wanduhr-Cutoff + End-to-End-Regressionstest).

## B272 — hydro_kaernten fehlte im Admin-Panel "API-Cache Status" (2026-06-30)

**Datei:** `app.py`
**Problem:** Alle anderen externen Schnittstellen cachen über
`api_cache.py` (`train_data/api_cache/`), das `/api/cache_status` scannt.
`hydro_fetch.py` nutzt einen eigenen, älteren Cache-Mechanismus
(`LATEST_FILE`) und fehlte dadurch komplett in dieser Tabelle sowie in
`_KNOWN_EXTERNAL_SERVICES`/`_API_PUBLIC_URLS`.
**Fix:** `hydro_kaernten` zu beiden Listen ergänzt; `/api/cache_status`
liefert für `hydro_kaernten` jetzt eine eigene Zeile mit identischer
FRESH/STALE/MISSING-Logik, basierend auf `hydro_fetch.LATEST_FILE`-Mtime
und der effektiven `HYDRO_API_TTL_SECONDS`. `hydro_fetch.py` selbst wurde
nicht verändert.
**Tests:** `tests/test_b272_hydro_cache_status_visible.py` (4 neue Tests)
+ bestehende Cache-Status-/Service-Registry-Tests weiterhin grün (11/11
lokal verifiziert).

## B273 — ML-Forecast-Horizonte zickzackten ohne Richtungsprüfung (2026-06-30)

**Dateien:** `prediction.py`, `config.py`

**Problem:** Seit P58 (Delta-Encoding) hat jeder Forecast-Horizont (10/20/30/40/60 min)
ein unabhängig trainiertes ML-Modell. `validate_forecast_point()` prüfte pro Horizont
nur bbox, NaN, Reaktivierungs-Warmup und maximale Geschwindigkeit (Ursprung→Zielpunkt) —
nie die Richtung. Dadurch konnte ein Horizont-Punkt fast entgegengesetzt zur zuletzt
beobachteten Zugrichtung der Zelle liegen, solange die implizite Geschwindigkeit unter
`MAX_CELL_SPEED_KMH` blieb. Live verifiziert (Debug-Export 2026-06-30, 17:00-Frame):
4 von 16 aktiven Zellen mit `forecast_mode=ml` zeigten Kursänderungen von 165–176°
zwischen aufeinanderfolgenden Horizonten (z. B. Zelle 346I2ILB: 23,6° → 207,8° →
301,8° → 265,6° → 302,9°), während alle `kinematic_fallback`-Zellen exakt 0,0°
Kursänderung hatten (reine Geradenextrapolation).

**Fix:** Neue Prüfung in `validate_forecast_point()`: für `mode="ml"` wird, sofern die
Zelle eine belastbare Zugrichtung hat (`speed_kmh >= MIN_MOVEMENT_FOR_ARROW_KMH`), die
Peilung Ursprung→ML-Punkt (neue Hilfsfunktion `_bearing_deg()`) gegen `direction_deg`
geprüft. Überschreitet die Abweichung `ML_FORECAST_MAX_BEARING_DEVIATION_DEG`
(Default 90°, runtime-überschreibbar), wird der Punkt mit
`ml_forecast_direction_implausible` abgelehnt und der bestehende kinematische
Fallback-Pfad greift für diesen Horizont. Kinematische Forecasts sind nicht betroffen.

**Tests:** `tests/test_b273_ml_forecast_direction_check.py` (9 neue Tests, inkl.
Regressionstest mit den realen 346I2ILB-Koordinaten aus dem Debug-Export).

## B274 — Zusammenhängende Zellen wurden durch 1-Pixel-Lücke nie zusammengeführt (2026-06-30)

**Dateien:** `object_tracking.py`, `config.py`

**Problem:** `are_contours_touching_edges()` prüfte Konturen ohne jegliche
Toleranz auf direkte Pixel-Überlappung der 1px-Ränder. Verifiziert im
Debug-Export 2026-06-30, 17:35-Frame: Die Zellen `I45JTRXI`↔`9WMB6Q7Q` und
`SKU9AD2B`↔`IHAPWM5M` hatten je einen Konturabstand von exakt 0,140 km —
bei `UPSCALE_FACTOR=3` und `PX_TO_KMH=4.0` entspricht das genau einem
einzigen Pixel im hochskalierten Grid. Im Reflektivitäts-Colormap war an
beiden Stellen keinerlei Lücke erkennbar; beide Fälle waren je eine einzige
zusammenhängende Zelle, wurden aber als zwei separate Zellen mit getrennten
IDs, Forecasts und Hagel-/Schwere-Bewertungen getrackt.

**Fix:** Neuer Parameter `dilate_px` in `are_contours_touching_edges()` und
`merge_close_contours()`: vor dem Überlappungs-Check werden beide
Rand-Masken um `dilate_px` Pixel aufgeweitet (`cv2.dilate`). Beide
Aufrufstellen in `object_tracking.py` übergeben jetzt
`dilate_px=MERGE_TOUCH_DILATE_PX` (neue Konstante, Default 2, analog zu
`MIN_CONTOUR_TOUCH` statisch, nicht runtime-überschreibbar). Ohne
`dilate_px`-Argument bleibt das bisherige Verhalten unverändert
(Default 0) — keine Auswirkung auf eventuelle weitere, unbekannte Aufrufer.

**Tests:** `tests/test_b274_contour_touch_dilate.py` (6 neue Tests, inkl.
Regressionstest für echte, weit getrennte Zellen und Backward-Kompatibilität
ohne `dilate_px`-Argument).

## B275 — P66 (Multi-Core-Split) zerschnitt zusammenhängende Gewitterlinien ohne echte Lücke (2026-06-30)

**Dateien:** `object_tracking.py`, `config.py`

**Problem:** `split_multi_core_contours()` entschied über einen Split
ausschließlich anhand des Abstands zweier erkannter Konvektionskerne
(`MULTI_CORE_MIN_DIST_PX`), ohne jemals zu prüfen, ob zwischen ihnen
tatsächlich eine Lücke in der äußeren Zell-Maske existiert. Verifiziert im
Debug-Export 2026-06-30, 17:35-Frame (Original-Radarbild + KML-Georeferenzierung
nachgebaut): Eine von `merge_close_contours()` bereits korrekt zu einer
Kontur zusammengeführte Gewitterlinie (18.586 px) wurde wegen zweier
170 px (≈18,9 km) entfernter Reflektivitäts-Maxima per Voronoi in
`9WMB6Q7Q` und `I45JTRXI` zerschnitten — obwohl die Verbindungslinie
zwischen beiden Kernen zu 0 von 100 Stichproben außerhalb der Zell-Maske
lag (keine reale Lücke, durchgehend zusammenhängende Struktur).

**Fix:** Neue Hilfsfunktion `_core_path_gap_px()` tastet die direkte
Verbindungslinie zwischen zwei Kern-Zentren gegen die äußere Zell-Maske ab
und liefert den längsten zusammenhängenden Pixel-Abschnitt außerhalb der
Maske. Neue Schwelle `MULTI_CORE_MIN_GAP_PX` (Default 2.0 px, runtime-
überschreibbar wie alle anderen P66-Schwellen). Ein Split ist nur noch
erlaubt, wenn sowohl der bestehende Abstands-Check als auch der neue
Lücken-Check erfüllt sind. Verifiziert an zwei synthetischen Kontrollfällen
(durchgehende Böenlinie bleibt unverändert; U-Form mit echter Lücke bleibt
korrekt gesplittet) sowie am realen 17:35-Fall (Kontur bleibt jetzt
unverändert eine einzige Zelle).

**Tests:** `tests/test_b275_multi_core_gap_check.py` (6 neue Tests, inkl.
Regressionstest für den bestehenden Abstands-Check).

## B276 — Korrektur zu B274: unary_union führte nahe Konturen trotz Dilatation nicht zusammen (2026-06-30)

**Dateien:** `object_tracking.py`

**Problem:** B274 führte den `dilate_px`-Parameter ein und reichte ihn an
`are_contours_touching_edges()` durch — das beeinflusst aber nur die
Gruppierungs-Entscheidung. Der eigentliche Vereinigungsschritt
(`unary_union` in `merge_close_contours()`) wurde nicht angepasst: zwei
geometrisch echt getrennte Polygone (z. B. mit einer winzigen 1-Pixel-Lücke)
werden von `unary_union` weiterhin als `MultiPolygon` mit getrennten Teilen
zurückgegeben, nicht als ein einzelnes fusioniertes Polygon. B274 hatte
dadurch in der bisherigen Form keine praktische Wirkung — der eigene
B274-Test `test_merge_close_contours_joins_one_pixel_gap_with_dilate_px`
schlug gegen den deployten Code fehl.

**Fix:** Wird eine Gruppe mit `dilate_px > 0` und mehr als einer Kontur
gebildet, werden die Polygone vor der Vereinigung um `dilate_px` aufgeweitet
(`.buffer(dilate_px)`), vereinigt und danach wieder um denselben Betrag
zurückgeschrumpft (`.buffer(-dilate_px)`) — Buffer-Union-Unbuffer, schließt
die Lücke wie eine morphologische Closing-Operation im Polygon-Raum. Für
`dilate_px=0` (Default, alle unbekannten Aufrufer) bleibt der Code-Pfad
unverändert.

**Tests:** Keine neue Testdatei — der bestehende B274-Test
`tests/test_b274_contour_touch_dilate.py::test_merge_close_contours_joins_one_pixel_gap_with_dilate_px`
wechselt von FAILED auf PASSED und dient als Nachweis.

## B277 — ML-Promotion nutzte andere Kinematik-Baseline als Runtime-Gate (2026-07-02)

**Dateien:** `accuracy_tracker.py`, `model_training.py`, `prediction.py`, `app.py`
**Problem:** `model_training.py` bewertete Modell-Promotion gegen eine synthetische
Baseline (Position + v*Horizont, B243), während `prediction.py`s Runtime-Gate gegen
die reale Betriebskinematik (Optical-Flow/EWMA/Steering/orographisch) aus
`accuracy_history.jsonl` verglich. Modelle konnten promoted werden, die im
Runtime-Gate sofort wieder verworfen wurden.
**Fix:** Neue gemeinsame Funktion `accuracy_tracker.get_runtime_kinematic_mae_by_horizon()`
wird von Promotion UND Runtime-Gate genutzt. B243-Baseline bleibt nur Fallback bei
fehlenden Realdaten. `/api/ml_quality` zeigt Baseline-Quelle und letzten
Promotion-Entscheid.
**Tests:** `tests/test_b277_unified_kinematic_baseline.py`, erweitert:
`tests/test_b243_baseline_gate.py`, `tests/test_c1_dashboard_forecast_mode.py`

## P68 — Signierter Forecast-Bias: Messung, Anzeige, optionale Korrektur (2026-07-02)

**Dateien:** `forecast_error_diagnosis.py`, `prediction.py`, `orographic_module.py`, `drift_detector.py`, `config.py`, `app.py`
**Feature:** Signierte Bias-Metriken (dLon/dLat/Speed/Richtung) werden je Horizont
aus vorhandenen `forecast_error_details.jsonl`-Rohdaten berechnet (p10-p90-getrimmt),
in `train_data/evaluation/forecast_bias_status.json` persistiert und im Admin-Panel
angezeigt. Optionale, hart begrenzte Bias-Korrektur des kinematischen Fallbacks
(`FORECAST_BIAS_CORRECTION_ENABLED`, default aus). Ändert NICHT die Qualitätsziele
aus der Zieldefinition (<1 km / ≤30 Min bleibt unverändert).
**Tests:** `tests/test_p68_bias_metrics.py`

## B278 — Ziel-Frame-Diagnose granular aufgesplittet (ergänzt B260) (2026-07-02)

**Dateien:** `accuracy_tracker.py`, `dataset_builder.py`, `forecast_error_diagnosis.py`, `config.py`
**Hinweis:** Baut auf B260 (adaptive Toleranz, bereits committed) auf, ersetzt sie NICHT.
**Fix:** `_find_target_frame()` liefert zusätzlich `target_frame_delta_min` und einen
Ablehnungsgrund (`missing_due_to_ingest_gap`/`missing_due_to_tolerance`/
`missing_due_to_future_not_available`). Radar-Ingest-Lücken werden separat quantifiziert
(`radar_ingest_gaps.json`). Coverage je Horizont im Diagnose-Ergebnis sichtbar,
Warnstatus unter `MIN_VERIFICATION_COVERAGE_RATIO`.
**Tests:** erweitert `tests/test_accuracy_target_frame_coverage.py`

## B279 — Merge/Split-Lineage wurde bei Forecast-Verifikation ignoriert (2026-07-02)

**Dateien:** `accuracy_tracker.py`, `config.py`
**Problem:** Das B247-Speed/Core-Gate verwarf ID-Matches bei Merge/Split-Ereignissen
pauschal auf NN-Fallback, obwohl `parent_cell_id`/`merged_from_cell_ids` den
Zusammenhang bereits erklärten. `match_type="none"` und NN-Fallback dominierten.
**Fix:** Lineage-aware Matching (`lineage_parent`/`lineage_merged_from`/
`lineage_split_child`) vor dem B247-Gate. `VERIFICATION_NN_MAX_MATCH_KM` ist jetzt
horizontabhängig (`VERIFICATION_NN_MAX_MATCH_KM_BY_HORIZON`), harte Obergrenze bleibt.
**Tests:** erweitert `tests/test_b247_match_speed_gate.py`, `tests/test_b213_split_merge_lineage.py`

## B280 — IR→Radar-Precursor-Matching: Diagnose und Positiv-Pfad abgesichert (2026-07-02)

**Dateien:** `ir_cell_tracking.py`, `ir_cell_detection.py`, `cell_lineage.py`
**Ausgangslage:** Im 24h-Debug-Export waren alle IR-Lead-Time-Labels negativ.
Aktueller Code nutzt bereits durchgängig das kanonische `ir_<n>`-ID-Schema;
gemischte `IR-NNN`-IDs im Export stammen vermutlich aus Altdaten, nicht aus
aktivem Code. Es fehlte Instrumentierung der Match-Kandidaten und ein
nachweislich getesteter Positiv-Pfad.
**Fix:** `normalize_ir_id()` als defensive Altdaten-Absicherung, granulares
Match-Kandidaten-Logging (`[IR-MATCH][B280]`), `ir_precursor_diagnosis_summary()`
für Admin-/Export-Diagnose, Schutz vor Doppelmarkierung nach erfolgreichem Match.
**Tests:** erweitert `tests/test_1l4_ir_lead_time_labels.py`, `tests/test_1l2_ir_radar_score_matching.py`

## B281 — Circuit-Breaker: exponentieller Backoff + Tages-Aussetzer (2026-07-02)

**Dateien:** `api_circuit_breaker.py`, `api_budget_guard.py`
**Problem:** Fixer Cooldown (`CIRCUIT_COOLDOWN_CONN=900`) sorgte dafür, dass
dauerhaft tote Quellen (z. B. `hydro_kaernten`) alle 15 Minuten erneut angefragt
wurden.
**Fix:** Exponentieller Backoff (`CIRCUIT_BACKOFF_BASE_S`→`CIRCUIT_BACKOFF_MAX_S`,
Faktor `CIRCUIT_BACKOFF_FACTOR`), Tages-Aussetzer nach `CIRCUIT_SUSPEND_AFTER_STREAK`
Folgefehlern (`suspended_until`), sauberer Reset bei Erfolg. Geblockte Versuche
werden getrennt von echten HTTP-Requests gezählt.
**Tests:** erweitert `tests/test_circuit_breaker.py`, `tests/test_b144_circuit_walltime.py`

## P69 — ML-Transparenz konsolidiert in bestehenden Admin-Endpoints (2026-07-02)

**Dateien:** `app.py`, `accuracy_tracker.py`, `debug_export.py`
**Feature:** `/api/ml_quality` liefert zusätzlich `forecast_mode_counts`,
`ml_usage_ratio`, `ml_gate_reasons`, `verification_coverage_by_horizon`.
`/api/forecast_quality_diagnosis` liefert (via P68) bereits `bias_by_horizon`.
KEIN neuer Endpoint — bewusste Entscheidung gegen Duplizierung bestehender
Admin-Datenquellen. Statusdateien (`forecast_bias_status.json`,
`radar_ingest_gaps.json`) im 24h-Debug-Export enthalten.
**Tests:** `tests/test_p69_ml_transparency.py`, erweitert `tests/test_c1_dashboard_forecast_mode.py`

## P70 — Horizontabhängige Qualitätsziele administrierbar (h40/h60), <=30-Min-Ziel bleibt fest (2026-07-02)

**Dateien:** `config.py`, `runtime_config.py`, `drift_detector.py`, `app.py`
**Wichtige Korrektur gegenüber Erstentwurf:** Die Zieldefinition fordert
verbindlich <1km MAE für Horizonte <=30 Min. Dieses Ziel wird durch P70 NICHT
aufgeweicht oder administrierbar gemacht — es bleibt hart in
`QUALITY_TARGET_MAE_KM_FIXED` verdrahtet und ist über die Admin-API/Runtime-Config
schreibgeschützt. Administrierbar sind ausschließlich die zusätzlichen Horizonte
h40/h60, für die die Zieldefinition keine explizite Zahl vorgibt.
**Feature:** `/api/quality_targets`, Drift-Status zeigt `quality_target_by_horizon`
inkl. `quality_target_violation_horizon`.
**Tests:** `tests/test_p70_quality_targets.py`

## B282 — Codex-Review-Fix zu B279: Lineage-Nachfolger mit abweichender ID (2026-07-02)

**Datei:** `accuracy_tracker.py`
**Problem (Codex-Review PR #909):** Die B279-Lineage-Pruefung lief nur auf
Kandidaten, die bereits per exakter id/cell_id gefunden wurden. Split-Kinder
(neue cell_id + parent_cell_id) und sekundaere Merge-Parents (in
merged_from_cell_ids, aber andere cell_id) wurden dadurch nie erreicht und
fielen auf NN/B247-Gate zurueck.
**Fix:** Eigene Lineage-Kandidatensuche vor dem generischen NN-Fallback,
unabhaengig von id/cell_id-Gleichheit.
**Tests:** erweitert `tests/test_b247_match_speed_gate.py`, `tests/test_b213_split_merge_lineage.py`

## B283 — Codex-Review-Fix zu P69: Doppelzaehlung von no_target_frame in Coverage (2026-07-02)

**Datei:** `accuracy_tracker.py`
**Problem (Codex-Review PR #912):** `verification_coverage_by_horizon()` addierte
`no_target_frame` zusaetzlich zu `samples`, obwohl `samples` in
`breakdown_by_forecast_mode` bereits no_target_frame enthaelt (siehe `_finish()`
in `evaluate_for_horizon()`). Coverage wurde dadurch systematisch zu niedrig
angezeigt (z.B. 8/12 statt 8/10).
**Fix:** Nenner nutzt ausschliesslich das bereits kombinierte `samples`-Feld.
**Tests:** korrigiert `tests/test_p69_ml_transparency.py`

## B284 — Codex-Review-Fix zu P69: Schatten-Scoring als Live-ML-Nutzung gezaehlt (2026-07-02)

**Dateien:** `accuracy_tracker.py`, `app.py`
**Problem (Codex-Review PR #912):** `_accumulate_ml_shadow()` (P53/P54, bewusst
so implementiert) buchte Schatten-ML-Bewertungen in denselben by_mode["ml"]-Bucket
wie real ausgelieferte ML-Forecasts. `ml_usage_ratio` summierte diesen Bucket und
zeigte dadurch auch bei reinem Schatten-Betrieb "ML aktiv" an.
**Fix:** Neues, schatten-freies Feld `delivered_mode_counts` (nur real
ausgelieferte forecast_mode-Werte) wird zusaetzlich persistiert.
`ml_usage_ratio` in `/api/ml_quality` basiert ausschliesslich darauf.
P53/P54-Schatten-Logik bleibt unveraendert.
**Tests:** erweitert `tests/test_p69_ml_transparency.py`, `tests/test_c1_dashboard_forecast_mode.py`

## B285 — Codex-Review-Fix zu P69: Ampel zeigte "ML verworfen" auch bei erlaubtem Gate (2026-07-02)

**Dateien:** `app.py`, `frontend/src/pages/Accuracy.jsx`
**Problem (Codex-Review PR #912):** `/api/ml_quality` lieferte nur den
Reason-String je Horizont, nicht das `allow_ml`-Flag. Das Frontend behandelte
dadurch auch erlaubte Gate-Zustaende ("ml_mae_better_or_equal",
"gating_disabled") als Ablehnung und zeigte in ruhigen Zeitfenstern faelschlich
Rot statt Gelb/Gruen.
**Fix:** `/api/ml_quality["ml_gate_reasons"]` liefert je Horizont
`{reason, allow_ml}`. Frontend unterscheidet `allow_ml === false` (abgelehnt)
von `allow_ml === true` (erlaubt, aber ggf. wenig Traffic).
**Tests:** erweitert `tests/test_p69_ml_transparency.py`, `tests/test_c1_dashboard_forecast_mode.py`

### B286 — Codex-Review-Fix zu P70: Fixe <=30-Min-Ziele bei benutzerdefinierten Horizonten ✅ erledigt

**Dateien:** `drift_detector.py`, `runtime_config.py`, `app.py`
**Problem (Codex-Review PR #917):** `/api/horizons` erlaubt beliebige 5
Ganzzahl-Horizonte (nicht nur 10/20/30/40/60). `_quality_target_for_horizon()`
und `validate_override_key()` prüften jedoch nur die literalen Schlüssel
"10"/"20"/"30" als fest. Ein benutzerdefinierter Horizont wie h15 fiel auf den
2.0km-Default zurück statt die feste <1km-Vorgabe zu erben; die Admin-UI zeigte
ihn faelschlich als editierbar, obwohl das Speichern serverseitig ohnehin
abgelehnt wurde.
**Fix:** Numerische Prüfung `int(horizon) <= 30` statt literaler
Dict-Mitgliedschaft — an allen drei betroffenen Stellen (Zielberechnung,
Override-Validierung, Admin-API `editable`-Flag). `/api/quality_targets` zeigt
jetzt auch aktuell konfigurierte, nicht-standardmäßige Horizonte an.
**Tests:** erweitert `tests/test_p70_quality_targets.py`
**Status Phase „Horizontabhängige Qualitätsziele" (P70):** vollständig
abgeschlossen inkl. dieser Nachbesserung. Kein offener Punkt mehr aus den
PR #909/#911/#912/#914/#915/#916/#917-Reviews zu P70/B279/P69 bekannt.

### B287 — Codex-Review-Fix zu P70: Kinematik-MAE-Objekt wurde als NaN formatiert ✅ erledigt

**Datei:** `frontend/src/pages/Configuration.jsx`
**Problem (Codex-Review PR #917):** `runtime_kinematic_mae_by_horizon[h]` ist
seit B277 ein Objekt `{kinematic_mae, kinematic_samples}`. Die neue
P70-Konfigurationstabelle wandelte das gesamte Objekt direkt mit `Number(...)`
um, was `NaN km` anzeigte — der Admin konnte ML- gegen Kinematik-Qualität nicht
vergleichen.
**Fix:** Zugriff auf `.kinematic_mae` vor der Formatierung, zusätzliche Anzeige
von `kinematic_samples` als Kontext. Contract-Test gegen Backend-Struktur
ergänzt, um Regression zu verhindern.
**Tests:** erweitert `tests/test_p70_quality_targets.py`
**Status Phase „ML-Transparenz im Admin-Panel" (P69/P70):** vollständig
abgeschlossen inkl. dieser Nachbesserung.

### B288 — Codex-Review-Fix zu B284: delivered_mode_counts fehlte in no_target_frame-Zweigen ✅ erledigt

**Datei:** `accuracy_tracker.py`
**Problem (Codex-Review PR #916):** `delivered_mode_counts` (B284) wurde nur in
der Haupt-Matching-Schleife befuellt, nicht in den beiden no_target_frame-
Zweigen (Ziel-Frame fehlt / Ziel-Frame leer). Bei Horizont-Enden der
Aufzeichnung oder Radar-Ingest-Luecken verschwanden dadurch real ausgelieferte
ML-Forecasts aus `ml_usage_ratio` (Absturz auf 0/None trotz aktivem ML-Betrieb).
**Fix:** Dieselbe Zaehl-Zeile (`delivered_mode_counts[_mode_for(_o)] += 1`) in
beiden no_target_frame-Zweigen ergaenzt — identisch zur bereits korrekten
Zaehlung im Normalfall.
**Tests:** erweitert `tests/test_p69_ml_transparency.py`, `tests/test_c1_dashboard_forecast_mode.py`
**Status Phase „ML-Transparenz im Admin-Panel" (P69/B284):** vollstaendig
abgeschlossen inkl. dieser Nachbesserung. Keine weiteren offenen
Codex-Review-Punkte zu PR #916/#917 bekannt.

### B289 — Testfix: test_b260_adaptive_tolerance.py auf B278-Signatur angepasst ✅ erledigt

**Datei:** `tests/test_b260_adaptive_tolerance.py`
**Problem:** B278 aenderte die Rueckgabe von `_find_target_frame()` von einem
einzelnen String auf ein 3-Tupel `(pfad, delta_min, missing_reason)`. Der
B260-Regressionstest wurde dabei nicht aktualisiert und verglich weiterhin
direkt mit einem String (`AssertionError: assert ('f_2.json', 0.0, None) ==
'f_2.json'`).
**Fix:** Beide betroffenen Tests entpacken das Tupel explizit. Kein
Produktivcode veraendert.
**Tests:** `tests/test_b260_adaptive_tolerance.py` (korrigiert)
**Status:** Reine Testkorrektur, keine Phase betroffen.

### B290 — Testfix: fehlendes HISTORY_FILE-Monkeypatch im P69-Transparenztest ✅ erledigt

**Datei:** `tests/test_c1_dashboard_forecast_mode.py`
**Problem:** `test_p69_existing_quality_endpoints_expose_transparency_fields`
patchte nur `SAVE_PATHS`, nicht die beim Modul-Import bereits fest berechnete
Konstante `accuracy_tracker.HISTORY_FILE`. `load_history()` las dadurch nicht
die Testdaten, `ml_payload["forecast_mode_counts"]["ml"]` schlug mit
`KeyError` fehl.
**Fix:** Ergänzung von `monkeypatch.setattr(_accuracy_tracker, "HISTORY_FILE", ...)`,
identisch zum bereits etablierten, korrekten Muster im unmittelbar
vorausgehenden Test derselben Datei. Kein Produktivcode veraendert.
**Tests:** `tests/test_c1_dashboard_forecast_mode.py` (korrigiert)
**Status:** Reine Testkorrektur, keine Phase betroffen.

### B291 — Testfix: veraltete Coverage-Erwartung aus der Zeit vor B283 ✅ erledigt

**Datei:** `tests/test_c1_dashboard_forecast_mode.py`
**Problem:** Testerwartung `round(98 / 102, 4)` ging von der VOR B283
bestehenden Doppelzählung aus (no_target_frame zusaetzlich zu samples
addiert). Seit B283 enthaelt `samples` no_target_frame bereits; korrekter
Nenner ist 100, nicht 102.
**Fix:** Testerwartung auf `round(98 / 100, 4)` korrigiert. Kein
Produktivcode veraendert — `verification_coverage_by_horizon()` war bereits
seit B283 korrekt.
**Tests:** `tests/test_c1_dashboard_forecast_mode.py` (korrigiert)
**Status:** Reine Testkorrektur, keine Phase betroffen. Zusammen mit B289/B290
sind damit alle bekannten Test-Nachwirkungen aus B278/B283/B284/P69
bereinigt.

### B294 — _model_usage_from_accuracy_history: Aggregationsbug behoben ✅ erledigt

**Datei:** `tools/diagnose_forecast_quality.py`
**Problem (verifiziert an echtem Export):** by_horizon wurde pro Zeile
überschrieben, die letzte 0-Sample-Zeile (Schönwetter-Flaute) gewann, während
total_samples über alle Zeilen summiert wurde → total_samples=66970 bei allen
Horizonten samples=0.
**Fix:** Pro Horizont jüngste Zeile mit samples>0; total_samples konsistent aus
diesen Einträgen.
**Tests:** `tests/test_b294_model_usage_aggregation.py`

**Phasenstatus Diagnose/Forecast-Quality:** Aggregations- und Statuskorrektheit
der lokalen 24h-Diagnose in Arbeit — B294 (model_usage) erledigt; offen:
B293 (Status-Gating bei kleiner Stichprobe).

### B292 — Stillstands-Prognose bei brandneuer Zelle vermieden (Steering-Seed) ✅ erledigt

**Dateien:** `prediction.py`, `config.py`
**Datenbefund (echter Export):** Nur 15 von 5707 Forecasts waren echte
Stillstaende (forecast_speed=0), alle kalman_only am Track-Anfang; der
EWMA/Kalman-Fallback deckt bereits 402/417 prev_radar_missing-Faelle ab.
**Fix:** Bei kalman_only mit Nullgeschwindigkeit und vorhandenem Steuerstrom
wird der 700/500-hPa-Wind mit STEERING_NEW_CELL_SPEED_FRAC (default 0.6) als
initiale Zuggeschwindigkeit angesetzt statt 0. Geschwindigkeits-Cap (B219)
begrenzt weiterhin. Keine Doppel-Einheitenumrechnung (verifiziert).
**Tests:** `tests/test_b292_new_cell_steering_seed.py`

**Phasenstatus Kurzhorizont-Genauigkeit:** Stillstands-Rest-Fall (B292)
erledigt. Offen bleibt die generelle Reduktion des Richtungsfehlers
(Median h10 ~54 Grad) — bewusst NICHT als Blind-Fix, sondern datengetrieben mit
echten Bewegungsdaten separat anzugehen (siehe Report-Prompt 1).

### P71 — Richtungs-/Geschwindigkeitsfehler als eigenstaendige Drift-Kennzahl ✅ erledigt

**Dateien:** `config.py`, `drift_detector.py`, `runtime_config.py`, `app.py`
**Datenbefund (echter Export):** Median-Richtungsfehler h10 ~54 Grad ist die
Kernursache der Positions-Drift, ging aber in der Positions-MAE unter.
**Feature:** check_drift() wertet direction_stats_by_horizon /
speed_stats_by_horizon (juengste Zeile mit genug Samples, Kurzhorizonte) aus,
alarmiert bei Ueberschreitung admin-editierbarer p90-Schwellwerte
(DRIFT_DIRECTION_P90_MAX_DEG / DRIFT_SPEED_P90_MAX_KMH), zeigt sie im Admin-Panel.
**Tests:** `tests/test_p71_direction_speed_drift.py`

**Phasenstatus Drift-/Qualitaets-Diagnose:** Richtungs-/Speed-Drift-Kennzahl
erledigt (P71). Zusammen mit B293/B294 (Diagnose-Korrektheit) und B292
(Stillstands-Rest-Fall) sind die aus dem 03.07.-Analyse-Report abgeleiteten,
verifizierten Punkte abgeschlossen. NICHT umgesetzt (bewusst, da bereits im
Code vorhanden): ML-Baseline-Gate (bereits via B277 aktiv, ML-Anteil real von
13% auf 2,5% gefallen).

### B293 — Diagnose-Kopf-Status ehrlich (insufficient_data bei kleiner Stichprobe) ✅ erledigt

**Dateien:** `tools/diagnose_forecast_quality.py`, `config.py`
**Problem (verifiziert an echtem Export):** status="ok" fest verdrahtet; bei nur
3 verifizierten Samples + hoher Missing-Ratio verdeckte der Kopf-Status das reale
Genauigkeitsproblem.
**Fix:** status wird aus verified_forecasts (< DIAGNOSIS_MIN_VERIFIED_FORECASTS)
und Missing-Target-Ratio (> DIAGNOSIS_MAX_MISSING_TARGET_RATIO) abgeleitet →
"insufficient_data", inkl. Hinweis in important_findings/recommendations.
**Tests:** `tests/test_b293_diagnosis_status.py`

**Phasenstatus Diagnose/Forecast-Quality:** Status-Gating erledigt (B293),
Aggregation erledigt (B294). Damit ist die Kern-Korrektheit der lokalen
24h-Diagnose (Status + model_usage) abgeschlossen.

### B299 — DEM-Slope/Barrier: Bewegungsvektor-Gate von Berechnungsfehler unterscheiden ✅ erledigt

**Dateien:** `dem_feature.py`, `accuracy_tracker.py`, `tools/diagnose_forecast_quality.py`
**Datenbefund (echter Export 2026-07-04):** dem_slope_toward_cell/dem_barrier_ahead
zero_ratio=0.852 bei 196 Samples. Ursache laut Code-Verifikation ist NICHT
flaches Gelände (wie der Analyse-Report vermutete), sondern das
Bewegungsvektor-Gate `speed <= 0.5` in `get_dem_features()`, das unabhängig
vom Terrain auf 0.0 zurückfällt — identisch mit dem Rückfall bei fehlendem
DEM-Tile.
**Fix:** Neues Feld `dem_slope_barrier_status` ("dem_unavailable" /
"no_movement_vector" / "computed") in `get_dem_features()`, durchgereicht über
`_detail_record()` und als Verteilung in `diagnose_forecast_quality.py`
(`dem_slope_barrier_status_breakdown`) ausgewiesen. Reine Diagnose-Erweiterung,
keine Änderung an Forecast-/Orographie-Verhalten.
**Tests:** `tests/test_b299_dem_status_flag.py`

### B300 — Codex-Review-Fix zu B299: unvollständige DEM-Abdeckung als eigener Status ✅ erledigt

**Dateien:** `dem_feature.py`, `tools/diagnose_forecast_quality.py`
**Codex-Review-Fund (PR zu B299):** Bei vorhandenem Bewegungsvektor, aber
unvollständigem 3×3-Slope-Gitter oder unvollständigen Barrier-Lookahead-Punkten
(DEM-Kachel-Rand/NaN), wurde trotzdem `dem_slope_barrier_status="computed"`
zurückgegeben — DEM-Abdeckungslücken erschienen dadurch als gültige
Flachgelände-Nullwerte in der neuen Diagnose.
**Fix:** Neuer Status `dem_partial_coverage`, wenn `slope_complete` (9/9
Gitterpunkte) oder `barrier_complete` (4/4 Lookahead-Punkte) nicht erfüllt
sind. `dem_slope_barrier_status_breakdown` um diesen Wert ergänzt.
**Tests:** `tests/test_b299_dem_status_flag.py` (erweitert um 2 Fälle)

### B301 — Codex-Review-Folgefix zu B300: test_b257 kannte dem_partial_coverage nicht ✅ erledigt

**Datei:** `tests/test_b257_diagnosis_feature_schema.py` (+ neuer Test
`tests/test_b301_dem_partial_coverage_schema.py`)
**Datenbefund (echter Export 2026-07-05):** `install_pytest.log` zeigt
`1 failed, 1459 passed` — `test_active_schema_features_present` erwartete
noch das Drei-Schlüssel-Schema aus B257, während der Erzeuger seit B300
vier Schlüssel (inkl. `dem_partial_coverage`) liefert.
**Fix:** Testerwartung in `test_b257` auf das aktuelle Vier-Schlüssel-Schema
angeglichen. Neuer Regressionstest `test_b301_dem_partial_coverage_schema.py`
sichert ab, dass `dem_partial_coverage` korrekt gezählt wird und alle vier
Status-Schlüssel im Breakdown stets vorhanden sind, unabhängig davon welcher
Status tatsächlich beobachtet wurde.
**Tests:** `tests/test_b257_diagnosis_feature_schema.py`,
`tests/test_b301_dem_partial_coverage_schema.py`

**Phasenstatus Diagnose/Forecast-Quality:** Schema-Konsistenz zwischen
Erzeuger (`diagnose_forecast_quality.py`) und Test-Suite wiederhergestellt.
Komplette Testsuite wieder grün (0 failed).

### B298 — Radar-Ingest-Health-/Alarmschwelle ✅ erledigt

**Dateien:** `config.py`, `dataset_builder.py`
**Datenbefund (echter Export 2026-07-04):** radar_ingest_gaps.json zeigt
present_frames=170/289 (Coverage ~59%), longest_gap_min=20.0 (4x expected_interval_min)
— bislang ohne automatisierte Einordnung.
**Fix:** `compute_radar_ingest_gaps()` liefert jetzt zusätzlich `coverage_ratio`,
`health_status` ("ok"/"warning"/"critical") und die verwendeten Schwellwerte.
Schwellen (RADAR_INGEST_GAP_WARN_FACTOR=2.0, RADAR_INGEST_GAP_CRITICAL_FACTOR=4.0,
als Vielfaches von expected_interval_min) sind runtime-überschreibbar.
**Tests:** `tests/test_b298_radar_ingest_health.py`

**Phasenstatus Radar-Coverage/Verifikation:** Interpolation (B295), NN-Härtung
(B296), Ingest-Health-Klassifikation (B298) und Kurzhorizont-Verifikation bei
grobem Radar-Takt (B302) zusammen abgeschlossen — verifizierte Samples für
Promotion/Training wieder verfügbar. Eine
Anzeige von health_status im Admin-Panel ist NICHT Teil dieses Prompts (reine
Backend-/Diagnose-Kennzahl) und müsste als eigenes Fach-Feature (P-Prompt)
separat beauftragt werden.

### B297 — Skywarn-Snapshot: gültige Lage nicht durch leeren Fehler überschreiben ✅ erledigt

**Datei:** `skywarn_export_snapshot.py`
**Datenbefund (echter Export 2026-07-04):** `skywarn_export.json` status='error',
error.type='empty_payload', fetched_at 12:00 Europe/Vienna.
**Problem (verifiziert im Code):** `_write_snapshot()` überschrieb immer, auch
bei leerer Lage — ein zuvor gültiger Snapshot ging verloren. `_snapshot_is_from_today()`
blockierte zusätzlich jeden weiteren Versuch für den Rest des Tages, unabhängig
vom Status.
**Fix:** Neue Funktion `_todays_snapshot_status()` unterscheidet 'ok'/'error'.
Skip-Bedingung greift nur noch bei status='ok'. Ein Fehler-Snapshot überschreibt
keinen bereits vorhandenen gültigen Snapshot von heute mehr.
**Tests:** `tests/test_b175_skywarn_empty_payload.py`

### B296 — NN-Akzeptanzschwelle an Zielqualität gekoppelt + robuste Kennzahl ✅ erledigt

**Dateien:** `config.py`, `accuracy_tracker.py`
**Datenbefund (echter Export 2026-07-04):** Zelle WX-20260703-0002 erzeugte
akzeptierte NN-Treffer von 5.0-7.3 km bei h30/h40/h60, obwohl die bestehende
horizontabhängige Schwelle (B279: 8/9/10 km) das formal zuließ — weit über den
Qualitätszielen dieser Horizonte (1.0/1.5/2.0 km).
**Fix:** VERIFICATION_NN_MAX_MATCH_KM_BY_HORIZON für h30/h40/h60 auf 3.0/4.0/5.0 km
verschärft (h10/h20 unverändert, dort bereits im Ziel). Zusätzlich `median_km`
als robuste Kennzahl neben `mae_km` je Horizont in `evaluate_for_horizon()`
ausgegeben.
**Tests:** `tests/test_b296_nn_threshold_and_median.py`

**Phasenstatus Radar-Coverage/Verifikation:** NN-Ausreisser-Härtung (B296)
erledigt, zusammen mit B295 (Interpolation). Offen: Radar-Ingest-Alarmschwelle
(B298).

### B295 — Ziel-Radarframe-Interpolation bei fehlender exakter Aufnahme ✅ erledigt

**Dateien:** `accuracy_tracker.py`, `config.py`
**Datenbefund (echter Export 2026-07-04):** 129/196 Forecasts ohne Ziel-Frame
(missing_target_frames.ratio=0.6582), radar_ingest_gaps.json zeigt Lücken bis
20 Minuten. B260 deckt nur die nächstgelegene reale Aufnahme ab, keine
Interpolation zwischen zwei Frames.
**Fix:** Neue Funktion `_interpolate_target_objects()` rekonstruiert bei
`missing_due_to_tolerance` eine Ziel-Objektliste per linearer Interpolation
zwischen den zwei umgebenden realen Frames (ID-gepaart), begrenzt auf
VERIFICATION_INTERPOLATION_MAX_GAP_S (1800s), um echte Ingest-Lücken nicht zu
überbrücken.
**Tests:** `tests/test_b295_target_frame_interpolation.py`

**Phasenstatus Radar-Coverage/Verifikation:** Interpolationsfall (B295)
erledigt. Offen: NN-Ausreißer-Härtung (B296), Radar-Ingest-Alarmschwelle (B298).

### B302 — Nearest-Target-Frame-Toleranz für Kurzhorizont-Verifikation ✅ erledigt
- Ursache: `_effective_target_tolerance_s()` begrenzte die Zielframe-Suche auf
  `max(VERIFICATION_TIME_TOLERANCE_S=90 s, frame_half_s=150 s)` = 150 s. Bei 15-min-Radartakt
  (Ruhephasen) ist der nächste reale Frame für +10/+20/+40-Horizonte 5–10 min entfernt →
  `no_target_frame`. Verifiziert im 24-h-Export: missing_target_frames.ratio = 0.6142,
  h10 13/22 „none", h20 17/22, h30/h40 je 19/22.
- Fix: Neue Config-Konstante `VERIFICATION_NEAREST_FRAME_TOLERANCE_S` (450 s = 7,5 min,
  runtime-überschreibbar). `_effective_target_tolerance_s()` bezieht sie ein
  (`max(time_tol_s, frame_half_s, nearest_tol_s)`). Nearest-Auswahl (`best_delta`) und
  NN-/ID-Match-Logik unverändert. Echte Lücken > 7,5 min bleiben `no_target_frame`.
- Wirkung: Kurzhorizonte 10/20/40 min werden bei beliebigem Radar-Takt verifizierbar →
  Voraussetzung für zieldefinition.txt (≤30 min < 1 km) und für Modell-Promotion
  (behebt indirekt „samples=4 < 50").
- Dateien: `config.py`, `accuracy_tracker.py`,
  `tests/test_b302_nearest_target_frame_tolerance.py`, `docs/WetterExtended_Benutzerhandbuch.md`.
- Test: `tests/test_b302_nearest_target_frame_tolerance.py`.

### B303 — frame_empty getrennt von no_target_frame in der Verifikation ✅ erledigt
- Ursache: `evaluate_for_horizon()` zählte sowohl „kein Radar-Frame gefunden" als auch
  „Radar-Frame gefunden, aber 0 Zellen" identisch als `no_target_frame`. Letzteres ist
  jedoch kein Datenlücken-Fall, sondern ein korrektes negatives Messergebnis (Zelle real
  aufgelöst). Verifiziert im 24-h-Export: 125 von 145 Objekt-Dateien enthalten `[]`.
- Fix: neuer eigenständiger Zähler `frame_empty` in `_bucket()`, `_finish()`, `base`-Dict,
  finalem Rückgabe-Dict sowie neues Feld `frame_empty` in `_detail_record()`. `id_lost` und
  `missed` schließen `frame_empty`-Fälle jetzt korrekt aus. Der Zweig `target_path is None`
  (echte Lücke) bleibt unverändert.
- Wirkung: `no_target_frame`-Quote in Diagnose/Reports spiegelt künftig nur noch echte
  Radar-Coverage-Lücken wider, nicht mehr meteorologisch korrekte Null-Zellen-Ergebnisse.
  Baut auf B302 (Nearest-Frame-Toleranz) auf.
- Dateien: `accuracy_tracker.py`, `tests/test_b303_frame_empty_vs_no_target_frame.py`.
- Test: `tests/test_b303_frame_empty_vs_no_target_frame.py`.
- Follow-up (nicht Teil dieses Prompts): deutschsprachige Diagnose-Meldung für hohe
  `frame_empty`-Quote in `_diagnosis()` + Übersetzung in `email_notifier.py`.

**Phasenstatus Radar-Coverage/Verifikation:** Coverage-Diagnose jetzt zwischen echten
Datenlücken und aufgelösten Zellen unterscheidbar (B303) — Voraussetzung für belastbare
Root-Cause-Analysen in Phase B (Hailo-Training).

### B306 — forecast_speed_factor nur bei echtem Terrain-Blocking ✅ erledigt
- Ursache: `compute_orographic_scores()` berechnete `speed_factor` unbedingt aus
  `stationary_risk`, auch bei sehr niedrigem `terrain_blocking_score`. Verifiziert im
  Scheduler-Log: Zelle PIB5Z4CB erhielt `forecast_speed_factor=0.860` trotz freier Zugbahn.
  Verschärfte den bereits bestehenden Speed-Underestimation-Bias (Report-Befund #2).
- Fix: neue Schwelle `OROGRAPHIC_BLOCKING_MIN_FOR_DAMPING` (0.3, runtime-überschreibbar) —
  unterhalb bleibt `speed_factor=1.0`. Neue Untergrenze `OROGRAPHIC_SPEED_FACTOR_FLOOR`
  (0.4, runtime-überschreibbar), angehoben von vormals hart codiert 0.1.
- Dateien: `orographic_module.py`, `tests/test_b306_orographic_speed_factor_threshold.py`.
- Test: `tests/test_b306_orographic_speed_factor_threshold.py`.
- Follow-up (nicht Teil dieses Prompts): Kopplung mit künftiger Speed-Bias-Korrektur
  (B305), sobald `forecast_bias_status.json`-Schreibpfad verifiziert ist.

### B307 — 2nd-Order-Beschleunigungsterm in der Kinematik ✅ erledigt (Default AUS)
- Ursache: `_append_kinematic()` extrapolierte ausschließlich mit konstanter
  Geschwindigkeit (1st-Order). Verifiziert im 24h-Export: Zelle WX-20260705-0099
  erreichte bei h40 einen Fehler von 18,3 km durch unterschätzte Nordbeschleunigung.
- Fix: neue Funktionen `_compute_acceleration_px_per_min2()` (Beschleunigung aus den
  2 jüngsten Geschwindigkeitsintervallen der History) und
  `_bounded_acceleration_displacement()` (0.5·a·t², hart gekappt auf
  `KINEMATIC_ACCEL_MAX_FRACTION=0.3` der linearen Verschiebung). Additiv zur
  bestehenden linearen Prognose, NACH Speed-Cap und orographischer Dämpfung (B306).
- Sicherheit: `KINEMATIC_ACCELERATION_ENABLED` Default **False** — wie bei
  `FORECAST_BIAS_CORRECTION_ENABLED` (P68) etabliert, aktiviert Horst manuell nach
  Validierung gegen reale Daten (Admin-Panel/runtime_overrides.json).
- Bereits vorhanden, nicht Teil dieses Prompts: getrimmte/mediane MAE (B296,
  `median_km`), Steering-Wind-Blend, Speed-Cap, orographische Dämpfung (B306).
- Dateien: `config.py`, `prediction.py`, `tests/test_b307_kinematic_acceleration.py`.
- Test: `tests/test_b307_kinematic_acceleration.py`.

### B308 — Promotion-Gate: adaptives Evaluationsfenster statt harter 24h-Grenze ✅ erledigt
- Ursache: `evaluate_on_recent(model_dir, hours=24)` wurde für Promotion-Vergleiche
  ausschließlich mit dem Default-Fenster 24h aufgerufen. Bei ruhigen Wetterlagen
  (verifiziert: 125/145 Objekt-Dateien im 24h-Export ohne Zelle) sammeln sich in 24h zu
  wenige verifizierte Samples → `MIN_SAMPLES_FOR_PROMOTION=50` dauerhaft unerreichbar
  ("samples=4 < 50"), Modell bleibt eingefroren unabhängig von seiner Qualität.
- Fix: neue Funktion `evaluate_on_recent_adaptive()` verdoppelt das Fenster schrittweise
  (24h → 48h → 96h → … max. `MODEL_PROMOTION_EVAL_MAX_HOURS=168h`/7 Tage, innerhalb
  `DATA_RETENTION_DAYS=90`), bis `MIN_SAMPLES_FOR_PROMOTION` erreicht ist oder das Maximum
  greift. Die Qualitätsschwelle selbst (50 Samples) bleibt unverändert streng.
  REJECTED-Logmeldung zeigt jetzt zusätzlich das tatsächlich genutzte Fenster.
- Dateien: `model_training.py`, `tests/test_b308_adaptive_promotion_window.py`.
- Test: `tests/test_b308_adaptive_promotion_window.py`.

### B310 — Diagnose-Instrumentierung für IR→Radar-Match-Rate 🔍 Diagnose (kein Fix)
- Befund: `ir_lead_time_labels.jsonl` zeigt über den gesamten Bestand (2525 Einträge)
  `became_radar_cell=1` in KEINEM Fall — jeder IR-Vorläufer endet als
  `ended_without_radar`. Root-Cause ohne Live-Kandidaten-Daten nicht sicher lokalisierbar
  (Kandidaten unter `IR_RADAR_MATCH_SCORE_MIN`? `ir_tracks` meist leer bei neuen
  Radar-Detektionen? anderer Ausschluss-Mechanismus?).
- Maßnahme: `select_ir_radar_matches()` schreibt jetzt aggregierte Diagnose
  (`ir_radar_match_diagnostics.jsonl`: Kandidaten-/Decision-/Reason-Zähler, KEINE
  Einzel-Details) nach `train_data/cell_lineage/` — automatisch im nächsten
  Debug-Export enthalten (bestehender `cell_lineage`-Export-Pfad).
  Schalter `IR_RADAR_MATCH_DIAGNOSTICS_ENABLED` (Default true, runtime-abschaltbar).
- Dateien: `cell_lineage.py`, `tests/test_b310_ir_radar_match_diagnostics.py`.
- Test: `tests/test_b310_ir_radar_match_diagnostics.py`.
- **Nächster Schritt (separater Prompt, erst nach neuem Export):** Root-Cause anhand
  `reason_counts`/`decision_counts` aus einem frischen 24h-Export identifizieren und
  gezielt beheben.

### B312 — Stabile Fallback-Stations-ID statt Array-Position ✅ erledigt
- Ursache: `hydro_json_to_geojson()` (`hydro_static_import.py`) und die Stationsschleife
  in `build_static_hydro()` (`hydro_station_index.py`) vergaben für Stationen ohne
  offizielle ID einen Fallback basierend auf der Array-Position (`idx+1` bzw.
  `len(index)+1`). Bei jedem Static-Reimport (`install.sh --mode=full` Phase 6a, oder
  Admin-Button „Static-Hydro neu einlesen") konnte sich diese Position ändern, wodurch
  gespeicherte Admin-Overrides (`enabled`, `mark_q_m3s` in
  `data/config/hydro_station_overrides.json`) für exakt diese Stationen verwaisten — die
  Datei selbst blieb dabei unverändert erhalten (bereits korrekt vor install.sh geschützt).
- Fix: neue Hilfsfunktion `_stable_fallback_station_id()` in beiden Dateien — leitet eine
  deterministische Hash-ID aus gerundeten Koordinaten + Name ab, unabhängig von der
  Reihenfolge der Quelldaten. Offizielle IDs (`station_id`/`id`/`number`/`pegel_id`/
  `kennzahl`) haben weiterhin Vorrang.
- Migrations-Hinweis: bereits unter alter Positions-ID gespeicherte Overrides bleiben
  verwaist — einmalig nach diesem Fix betroffene Stationen im Admin-Panel neu setzen,
  danach stabil.
- Dateien: `hydro_static_import.py`, `hydro_station_index.py`,
  `tests/test_b312_stable_fallback_station_id.py`.
- Test: `tests/test_b312_stable_fallback_station_id.py`.

### B313 — Outlook-Abruf gegen systemd-Watchdog abgesichert ✅ erledigt
- Ursache: `fetch_outlook_series.py::_request()` rief `retry_get()` ohne
  `max_retries`-Override auf (Default 2× bei `_TIMEOUT=(5,15)`), und die
  Batch-Schleife hatte kein Gesamt-Wall-Time-Budget. Ein hängender Open-Meteo-Endpoint
  blockierte den Scheduler-Job ~3,3 min und riss ihn per systemd-Watchdog
  (`WatchdogSec=60s`) ab (`Main process exited code=killed status=6/ABRT`).
- Fix: `max_retries=1` explizit gesetzt; neues hartes Budget
  `OUTLOOK_SERIES_MAX_WALLTIME_S=25` (env-überschreibbar) bricht die Batch-Schleife
  unabhängig von Retry-/Batch-Anzahl rechtzeitig ab. Schützt sowohl `outlook_series`
  als auch `outlook_compute` (ruft dieselbe Funktion bei Cache-Miss auf).
- Dateien: `config.py` (nur Kommentar-Kontext, Konstante liegt in
  `fetch_outlook_series.py`), `fetch_outlook_series.py`,
  `tests/test_b313_outlook_watchdog_walltime.py`.
- Test: `tests/test_b313_outlook_watchdog_walltime.py`.

### B314 — ML-Runtime-Gate: adaptiver Fallback-Schwellwert ✅ erledigt
- Ursache: `_latest_runtime_mae_by_horizon()` verlangte hart
  `ML_RUNTIME_MIN_SAMPLES_PER_MODE=20` verifizierte ML-Samples je Horizont. Verifiziert:
  ML ist nachweislich genauer (1.712 km vs. 2.639 km bei h10), aber `model_usage`
  zeigt nur ~3 Samples je Horizont in datenarmen (ruhigen) Phasen — Gate blieb dauerhaft
  geschlossen, `delivered_mode_counts` fast ausschließlich `kinematic_fallback`.
- Fix: neuer Fallback-Schwellwert `ML_RUNTIME_MIN_SAMPLES_FALLBACK=5` (admin-wartbar).
  Wird die Standardschwelle in keiner `accuracy_history.jsonl`-Zeile erreicht, prüft ein
  zweiter Scan-Durchlauf gegen den niedrigeren Wert. Ergebnis wird transparent mit
  `reduced_sample_threshold: true` markiert. `ML_RUNTIME_GATING_MARGIN`-Vergleich bleibt
  unverändert zusätzlich wirksam.
- Dateien: `config.py`, `prediction.py`, `tests/test_b314_ml_runtime_gate_fallback.py`.
- Test: `tests/test_b314_ml_runtime_gate_fallback.py`.

### B315 — Scheindirektionsfehler bei quasi-stationären Zellen ausgeklammert ✅ erledigt
- Ursache: `evaluate_for_horizon()` übernahm `direction_error_deg`/`speed_error_kmh`
  unbedingt in die Drift-/Accuracy-Aggregation. Bei quasi-stationären Zellen
  (`actual_displacement_km` nahe 0) ist die berechnete Ist-Richtung geometrisch
  instabil — verifiziert: 114,6° Richtungsfehler bei 0,17 km realer Verschiebung,
  `p90_direction_error_deg=113,4` bei h10.
- Fix: neue Schwelle `DIRECTION_ERROR_MIN_DISPLACEMENT_KM=0.3` (admin-wartbar).
  Records mit `actual_displacement_km` darunter werden weiterhin vollständig in
  `forecast_error_km`/MAE erfasst, aber aus `direction_errors`/`speed_errors`
  ausgeklammert. Ergänzt B231 (das die Prognoseerstellung selbst bereits gegen
  Mikrobewegung absichert) um den fehlenden Bewertungs-seitigen Fall.
- Dateien: `config.py`, `accuracy_tracker.py`,
  `tests/test_b315_stationary_direction_error_exclusion.py`.
- Test: `tests/test_b315_stationary_direction_error_exclusion.py`.

### B316 — Radar-Ingest-Gesundheit idle-aware ✅ erledigt
- Ursache: `build_dataset()` rief `compute_radar_ingest_gaps(FRAME_INTERVAL_MIN, hours=24)`
  immer mit dem aktiven 5-Minuten-Takt auf, unabhängig davon, ob im Fenster überhaupt
  Zellen aktiv waren. In Ruhephasen (bewusst 15-min-Takt, `LOOP_INTERVAL_NO_CELLS_S=900`)
  führte das zu dauerhaft falschem `health_status="critical"`
  (verifiziert: `coverage_ratio=0.3737` ≈ 5/15 — exakt das erwartete Verhältnis bei
  korrektem 15-min-Realtakt gegen falsche 5-min-Erwartung).
- Fix: neue Funktion `_expected_radar_interval_min()` prüft die letzten `train_data/
  objects/*.json`-Dateien im Fenster auf tatsächliche Zellaktivität und leitet daraus den
  erwarteten Takt ab (Zellen vorhanden → `FRAME_INTERVAL_MIN`, sonst
  `LOOP_INTERVAL_NO_CELLS_S/60`).
- Dateien: `dataset_builder.py`, `tests/test_b316_radar_health_idle_aware.py`.
- Test: `tests/test_b316_radar_health_idle_aware.py`.

### B317 — hydro_kaernten Timeout gesenkt ✅ erledigt
- Ursache: `REQUEST_TIMEOUT_SECONDS` (Default 15s) verzögerte den
  Verarbeitungs-Loop bei jedem `ReadTimeout` gegen info.ktn.gv.at unnötig lange
  (verifiziert: zwei ReadTimeouts à 15s im Export, `fallback_used=true`).
- Fix: Default auf 10s gesenkt (weiterhin per `HYDRO_LIVE_TIMEOUT_SECONDS`
  env-überschreibbar). Circuit-Breaker (B149: `CIRCUIT_THRESHOLD_CONN=4`,
  `CIRCUIT_COOLDOWN_CONN=900s`) und Fallback-Pfad waren bereits korrekt verdrahtet und
  bleiben unverändert.
- Dateien: `hydro_fetch.py`, `tests/test_b317_hydro_timeout.py`.
- Test: `tests/test_b317_hydro_timeout.py`.


### B318 — Codex-Review-Nachbesserungen zu B313/B314 ✅ erledigt
- Fix 1 (echter Logikfehler): `fetch_outlook_series.py` prüfte das
  `OUTLOOK_SERIES_MAX_WALLTIME_S`-Budget nur am Batch-Anfang, nicht vor dem zweiten
  `_HOURLY_MIN`-Versuch innerhalb desselben Batches — konnte das harte Wall-Time-Budget
  aus B313 um ein weiteres Timeout-Fenster überschreiten. Jetzt zusätzlicher Check
  innerhalb der inneren Schleife.
- Fix 2 (Test-Isolation): `tests/test_b313_outlook_watchdog_walltime.py` installierte
  `sys.modules["http_retry"]` als dauerhaften Stub ohne Teardown — ließ
  `tests/test_b149_retry_get_breaker.py` je nach Ausführungsreihenfolge fehlschlagen
  (fehlendes `_SESSION`-Attribut). Jetzt mit `autouse`-Modul-Fixture sauber
  zurückgesetzt.
- Fix 3 (Test-Isolation): `tests/test_b314_ml_runtime_gate_fallback.py` patchte ein bei
  Modul-Import gebundenes, potenziell verwaistes `accuracy_tracker`-Objekt statt den
  aktuellen `sys.modules`-Eintrag. Reproduziert mit
  `pytest tests/test_accuracy_tracker_horizon_mode.py tests/test_b314_ml_runtime_gate_fallback.py`
  (2 Fehlschläge). Jetzt String-Form `monkeypatch.setattr("accuracy_tracker.<attr>", ...)`
  an allen 4 Stellen, löst das Zielmodul bei jedem Patch frisch auf.
- Dateien: `fetch_outlook_series.py`, `tests/test_b313_outlook_watchdog_walltime.py`,
  `tests/test_b314_ml_runtime_gate_fallback.py`.
- Test: bestehende Tests korrigiert, keine neue Testdatei nötig (reine
  Nachbesserung bereits vorhandener Tests plus ein Code-Fix).

### B319 — Codex-Review-Nachbesserung zu B317: Timeout als Tupel ✅ erledigt
- Ursache: B317 übergab `REQUEST_TIMEOUT_SECONDS` (10s) als Skalar an `retry_get()`.
  `http_retry._normalize_timeout()` hebt Skalare aber auf `max(t,
  _DEFAULT_READ_TIMEOUT=15)` an — der tatsächliche Read-Timeout blieb bei 15s, B317
  war in der Produktion wirkungslos. Der ursprüngliche B317-Test prüfte nur den rohen
  Parameter, nicht die normalisierte Wirkung, und übersah den Fehler deshalb.
- Fix: `timeout=(5.0, REQUEST_TIMEOUT_SECONDS)` als explizites Tupel — wird von
  `_normalize_timeout()` unverändert durchgereicht. Neuer Test prüft die tatsächliche,
  normalisierte Ausgabe direkt über `http_retry._normalize_timeout()`.
- Dateien: `hydro_fetch.py`, `tests/test_b317_hydro_timeout.py`.
- Test: `tests/test_b317_hydro_timeout.py`
  (`test_effective_timeout_is_not_clamped_to_fifteen_seconds`, neu).

### B320 — Test-Fehlerinjektion verschmutzte Produktions-api_health.jsonl ✅ erledigt
- Ursache: `test_b313_outlook_watchdog_walltime.py::
  test_fetch_series_aborts_within_walltime_budget` patchte `api_circuit_breaker.
  record_failure` als No-Op, ließ aber `log_api_failure` ungeschützt. Die
  Standard-Schutz-Fixture (`_isolate_api_health_log`, B129) patcht
  `debug_utils._API_HEALTH_FILE` — greift aber nicht mehr, sobald `debug_utils`
  irgendwo in der Gesamt-Suite neu geladen wird, da `fetch_outlook_series.py` die
  Funktion bereits beim eigenen Import gebunden hat (Stale-Modul-Referenz, wie B318).
  Verifiziert: 5 synthetische Zeilen ("simulated hang") in der echten
  `api_health.jsonl` vom 2026-07-07, 08:27:34-36Z. Erklärt zugleich den scheinbaren
  Widerspruch zum Circuit-Breaker-Status (Report-Befund 4) — Produktionscode koppelt
  beide bereits korrekt, nur der Test tat es einseitig nicht.
- Fix: `fos.log_api_failure` direkt gepatcht statt `debug_utils`. Empirisch mit dem
  vollen 1442-Test-Lauf verifiziert: keine Verschmutzung mehr.
- Manuelle Einmal-Bereinigung der bereits verschmutzten `api_health.jsonl` auf dem Pi
  nötig (siehe Prompt Abschnitt 3).
- Dateien: `tests/test_b313_outlook_watchdog_walltime.py`.
- Test: bestehender Test korrigiert; zusätzlich Vollsuite-Verifikationsschritt in
  Abschnitt 4 dokumentiert (kein separates neues Testfile).

### B321 — Radar-Ingest-Gap-Detektor: Raster-Phase und Coverage-Klammerung ✅ erledigt
- Ursache: `compute_radar_ingest_gaps()` verglich Erwartungsslots exakt mit vorhandenen
  Radar-Frame-Zeitpunkten. Wenn das Erwartungsraster durch `cutoff/now` auf einer
  anderen Minutenphase lag als reale Radarframes (z.B. :05/:20/:35/:50), entstanden
  falsche `missing_timestamps`. Zusätzlich konnte `coverage_ratio` bei feinerer realer
  Kadenz als dem erwarteten Raster über 1.0 steigen.
- Fix: Missing-Slots werden jetzt per Nächste-Nachbar-Zuordnung gegen vorhandene Frames
  mit `interval_min/2` Toleranz bestimmt. Die Coverage wird auf maximal 100% geklammert,
  damit feinere reale Kadenz als vollständige Abdeckung statt Übererfüllung zählt.
- Dateien: `dataset_builder.py`, `tests/test_b321_radar_ingest_gap_phase.py`.
- Test: `tests/test_b321_radar_ingest_gap_phase.py`.

### B322 — Warnung bei doppelt definierten .env-Schlüsseln ✅ erledigt
- Ursache: `config/.env` definierte `ADMIN_API_TOKEN` und `ADMIN_REQUIRE_TOKEN`
  jeweils dreifach (nicht aus `.env.example` stammend). `python-dotenv` wertet
  Duplikate stillschweigend nach „last-wins" aus, ohne Warnung — unklar, welcher
  Wert die Admin-Authentifizierung tatsächlich steuert (Fehlkonfigurations-/
  Sicherheitsrisiko).
- Fix: Neue Funktion `_warn_duplicate_env_keys()` in `config.py`, direkt nach
  `_load_dotenv()` aufgerufen. Gibt beim Start eine deutliche Konsolen-Warnung mit
  allen doppelten Schlüsseln aus. `.env` selbst liegt außerhalb des Git-Repos und
  muss manuell auf dem Pi bereinigt werden (siehe Prompt Abschnitt 5).
- Dateien: `config.py`, `tests/test_b322_env_duplicate_key_warning.py`.
- Test: `tests/test_b322_env_duplicate_key_warning.py`.

### B323 — Diagnose der Ziel-Verschiebungsverteilung 🔍 Diagnose (kein Fix)
- Befund: `lstm.val_loss` sprang einmalig von 0.592 (1727 Samples) auf ~1.20-1.24
  (alle 5 Retrains vom 07./08.07., konstant 2169 Samples). Plausible, aber nicht
  abschließend verifizierte Hypothese: die zusätzlichen ~442 Trainingszeilen stammen
  überproportional von quasi-stationären Zellen (siehe B315), was die
  Ziel-Verschiebungsverteilung verschiebt.
- Maßnahme: `build_dataset()` berechnet jetzt `target_displacement_stats`
  (Median/Mittelwert/P10/P90 der Horizont-0-Verschiebung in px,
  `quasi_stationary_fraction_lt2px`), gespeichert in `training_meta.json`. Rein
  diagnostisch, keine Änderung an Training/Sampling/Promotion.
- Dateien: `dataset_builder.py`, `model_training.py`,
  `tests/test_b323_target_displacement_diagnostics.py`.
- Test: `tests/test_b323_target_displacement_diagnostics.py`.
- **Nächster Schritt (separater Prompt, erst nach neuem Retrain):** Falls
  `quasi_stationary_fraction_lt2px` beim nächsten Retrain deutlich höher ist als bei
  der 1727-Sample-Version, gezielt Sample-Gewichtung oder Klassenbalance einführen.

### B324 — Hagelwarnung feuert faktisch nie: SHIP-basiertes hail_prob2 wurde nie ausgewertet ✅ erledigt
- Ursache: `_compute_hail_prob()` (main.py) multipliziert core_factor * cape_factor *
  height_factor. Drei Faktoren <= 1.0 multipliziert unterschaetzen die Hagelwahr-
  scheinlichkeit systematisch, sobald auch nur einer davon mittelmaessig ist — in Kaernten
  regelmaessig der Fall (Gefriergrenze im Sommer meist 3200-4200 m statt <= 3000 m).
  `hail_warning >= HAIL_WARN_THRESHOLD (0.45)` wurde dadurch faktisch nie erreicht, obwohl
  reale Hagelereignisse vorlagen (Nutzerbefund). Das bereits vorhandene, additiv gewichtete
  SHIP-basierte `hail_prob2` (compute_convective_indices.py, eigener Docstring: "kompatibel
  mit HAIL_WARN_THRESHOLD") wurde nirgends fuer die Warnentscheidung gelesen, nur als
  ML-Feature verwendet — die Integration war vorbereitet, aber nie fertiggestellt.
- Fix: Neue Funktion `_compute_hail_warning()` in main.py kombiniert `hail_prob` (ML-Feature,
  unveraendert, kein Retraining noetig) und `hail_prob2` per `max()` zu `hail_prob_effective`.
  `hail_warning` wird ab jetzt gegen `hail_prob_effective` statt gegen `hail_prob` allein
  geprueft. Beide Suppress-Funktionen (main.py, object_tracking.py) setzen
  `hail_prob_effective` bei still weiterverfolgten Regenresten ebenfalls auf 0.0 zurueck.
  Frontend (MapView.jsx) zeigt im Warn-Tooltip `hail_prob_effective` statt `hail_prob`, damit
  der angezeigte Prozentwert immer zur tatsaechlichen Ausloesebedingung passt.
- Dateien: `main.py`, `object_tracking.py`, `frontend/src/pages/MapView.jsx`,
  `tests/test_b324_hail_warning_ship_fusion.py`.
- Test: `tests/test_b324_hail_warning_ship_fusion.py`.
- Phasen-Status (Hailo): unveraendert; betrifft nur die operative Kartenwarnung, keine
  Hailo-U-Net-Nowcasting-Phase B.

### B333 — Beobachtungspunkt zu samples=0 im Bewegungs-Dataset dokumentiert ✅ erledigt
- Kein Bugfix: reine Dokumentation. `samples=0` im Bewegungs-Dataset wurde am
  2026-07-10 analysiert und auf konvektionsarme Wetterlage zurückgeführt
  (nur 14 neue Zellen am 2026-07-09 laut `cell_lineage_state.json`, gegenüber
  500-680/Tag Ende Juni). Damit erübrigt sich vorerst die in B332 aufgeworfene
  Architekturfrage zu `ML_SEQUENCE_LENGTH`.
- Fix: Ein Satz in `zieldefinition.txt` ergänzt, der festhält, dass `samples=0`
  erst bei anhaltendem Auftreten TROTZ ausreichender Zell-Lebensdauer erneut
  zu prüfen ist — verhindert erneute Vollanalyse bei der nächsten ruhigen Phase.
- Dateien: `zieldefinition.txt`.
- Test: kein Code geändert, kein Test nötig.
- Phasen-Status (Hailo): unverändert; reine Dokumentation.

### B330 — Open-Meteo 5xx wurden nach Retry-Erschöpfung mit `http=None` geloggt ✅ erledigt
- Ursache: `retry_get()` (`http_retry.py`) berechnete den echten HTTP-Statuscode
  (`_b_status`) nach Retry-Erschöpfung ausschließlich innerhalb des
  `breaker_service`-Zweigs für den Circuit-Breaker, übergab ihn aber nicht an den
  direkt danach folgenden `log_api_failure()`-Aufruf. Reale 5xx-Antworten
  (Open-Meteo-Outlook HTTP 502, Open-Meteo-Atmosphere-AROME-B1 HTTP 503) wurden
  dadurch als `(fallback=True, http=None)` protokolliert — der Statuscode ging
  für die Fehlerdiagnose verloren, obwohl der Fallback selbst korrekt griff.
- Fix: `_final_http_status` wird jetzt unabhängig vom `breaker_service`-Zweig aus
  `last_exc` ermittelt und an den abschließenden `log_api_failure()`-Aufruf
  übergeben. Der bereits korrekte 4xx-Sonderpfad und der Circuit-Breaker-Aufruf
  selbst bleiben unverändert.
- Dateien: `http_retry.py`, `tests/test_b330_retry_get_http_status_logging.py`.
- Test: `tests/test_b330_retry_get_http_status_logging.py`.
- Phasen-Status (Hailo): unverändert; reine Logging-Korrektur, keine
  funktionale Änderung am Fallback-/Retry-Verhalten.

### B329 — `dem_slope_barrier_status` wird nie am Objekt persistiert ✅ erledigt
- Ursache: `get_dem_features()` (`dem_feature.py`) liefert `dem_slope_barrier_status`
  ("computed"/"dem_partial_coverage"/"no_movement_vector"/"dem_unavailable"), aber
  `object_tracking.py` uebernahm beim Aufbau von `new_memory[obj_id]` nur
  `dem_elevation_m`/`dem_slope_toward_cell`/`dem_barrier_ahead` — das Statusfeld fehlte.
  `accuracy_tracker.py` und `tools/diagnose_forecast_quality.py` lasen dadurch
  immer `None`; `dem_slope_barrier_status_breakdown` in der Diagnose blieb leer.
  Reproduziert: alle 129 Records im aktuellen `forecast_error_details` hatten
  `dem_slope_barrier_status=None`.
- Fix: Eine Zeile in `object_tracking.py` ergaenzt — `dem.get("dem_slope_barrier_status")`
  wird in `new_memory[obj_id]` uebernommen. Keine Aenderung an der Berechnung selbst.
- Dateien: `object_tracking.py`, `tests/test_b329_dem_slope_barrier_status_persisted.py`.
- Test: `tests/test_b329_dem_slope_barrier_status_persisted.py`.
- Phasen-Status (Hailo): unveraendert; reines Feature-Plumbing fuer die
  Terrain-Diagnose, keine Auswirkung auf Phase B.

### B328 — Zeitbomben-Timestamp in Test (kein Produktivcode-Bug) ✅ erledigt
- Ursache: `test_p69_existing_quality_endpoints_expose_transparency_fields`
  (`tests/test_c1_dashboard_forecast_mode.py`) verwendete einen fest verdrahteten
  Fixture-Zeitstempel (`"2026-07-02T00:00:00Z"`) für `/api/ml_quality?hours=168`
  (→ `accuracy_tracker.load_history(since_hours=168)`, Cutoff =
  `datetime.utcnow() - timedelta(hours=168)`). Ab 2026-07-09 fiel dieser feste
  Zeitstempel aus dem 168h-Fenster heraus → `load_history()` lieferte `[]` →
  `forecast_mode_counts` blieb `{}` → `KeyError: 'ml'`. Reines Testartefakt, kein
  Fehler in `app.py`/`accuracy_tracker.py`.
- Fix: Fixture-Zeitstempel wird relativ zur Testlaufzeit (`datetime.utcnow() -
  timedelta(hours=1)`) berechnet statt fest verdrahtet. Neuer Regressionstest
  `tests/test_b328_load_history_window_boundary.py` sichert die
  Fenstergrenzen-Logik von `load_history()` direkt und zeitunabhängig ab.
  Der zweite Test mit identischem altem Fixture-Datum
  (`test_ml_quality_api_exposes_b277_fields`) nutzt `load_history()` nicht und
  war nicht betroffen — dort keine Änderung.
- Dateien: `tests/test_c1_dashboard_forecast_mode.py`,
  `tests/test_b328_load_history_window_boundary.py`.
- Test: `tests/test_b328_load_history_window_boundary.py`,
  `tests/test_c1_dashboard_forecast_mode.py`.
- Phasen-Status (Hailo): unverändert; reiner Test-Fix, keine Auswirkung auf
  Produktivcode oder Phase B.

### B327 — Risk-Watch Startup-Race gegen lokalen API-Server abgefedert ✅ erledigt
- Ursache: `_max_risk_level()` (`risk_watch.py`) pollt direkt nach dem Prozessstart
  `http://127.0.0.1:5000/api/risk_grid`. Ist der Flask-/API-Server (systemd-Dienst
  `wetterprojekt`) noch nicht vollständig hochgefahren, schlägt der Request mit
  "Connection refused" fehl und die Funktion liefert sofort `0` zurück — kein
  Readiness-Mechanismus vorhanden. Korrektur zum ursprünglichen Analyse-Report:
  der dort referenzierte Test `tests/test_b262_risk_watch_retry.py` betrifft einen
  anderen Codepfad (`main.py::_risk_alert_check`, E-Mail-Alert) und war als
  Grundlage ungeeignet.
- Fix: Neue Config-Konstanten `RISK_WATCH_STARTUP_GRACE_S` (Default 30 s) und
  `RISK_WATCH_STARTUP_MAX_RETRIES` (Default 2). `_max_risk_level()` versucht
  innerhalb des Grace-Fensters seit Prozessstart (`_PROC_START_MONOTONIC`) bei
  Exception bis zu `RISK_WATCH_STARTUP_MAX_RETRIES`-mal mit kurzem Backoff erneut,
  bevor auf `0` zurückgefallen wird. Außerhalb des Fensters (regulärer Betrieb)
  unverändertes Verhalten — kein zusätzlicher Retry, keine zusätzliche Latenz.
- Dateien: `config.py`, `risk_watch.py`, `tests/test_b327_risk_watch_startup_grace.py`.
- Test: `tests/test_b327_risk_watch_startup_grace.py`.
- Phasen-Status (Hailo): unverändert; reine Startup-Robustheit des Risk-Watch-Pollings,
  keine Auswirkung auf Phase B (Hailo-U-Net-Nowcasting).

### B325 — Atmosphären-Stale-Cache griff nicht über die Stundengrenze ✅ erledigt
- Ursache: `_bulk_get()` (`fetch_atmospheric_snapshot.py`) bildete den Cache-Key über
  `cache_key(_cache_prefix, url, _nearest_hour_str())` und suchte im Fehlerfall den
  Stale-Cache ausschließlich unter demselben stundengenauen Key. Beim ersten
  fehlgeschlagenen Request einer neuen Stunde (z. B. Open-Meteo HTTP 503 um 19:20)
  existierte dieser Key noch nicht, obwohl für die Vorstunde ein gültiger Snapshot
  vorlag — Ergebnis: `[ATMOSPHERE] ... kein Stale-Cache verfügbar`, alle
  atmosphärischen Features fehlten für den Zyklus komplett.
- Fix: Neue Funktion `_stale_get_recent_hours()` sucht rückwärts stundenweise
  (aktuelle Stunde zuerst, bis zu 24 h zurück) nach dem jüngsten gültigen
  Stale-Eintrag desselben Namespace/URL. `_bulk_get()` nutzt diese Funktion statt
  des einzelnen `_ck`-Lookups. `api_cache.py` (generischer Cache-Mechanismus für
  weitere Fetcher) bleibt unverändert.
- Dateien: `fetch_atmospheric_snapshot.py`, `tests/test_b325_atmosphere_cross_hour_stale.py`.
- Test: `tests/test_b325_atmosphere_cross_hour_stale.py`.
- Phasen-Status (Hailo): unverändert; reine Robustheits-Verbesserung der
  Atmosphäre-Datenbeschaffung, keine Auswirkung auf Phase B (Hailo-U-Net-Nowcasting).

### B326 — Skywarn: leere Lage (`null`-Payload) ist keine Fehlermeldung ✅ erledigt
- Ursache: `build_success_snapshot()` (`skywarn_export_snapshot.py`) klassifizierte
  jede leere Lage (skywarn.at liefert bei "keine aktive Warnung" JSON `null`) als
  `status="error"` (`error.type="empty_payload"`) — obwohl das der reguläre,
  erwartbare Zustand ist. Nachgelagerte Auswertungen konnten dadurch "Abruf
  fehlgeschlagen" nicht von "Abruf erfolgreich, aktuell keine Warnung" unterscheiden.
  Abgrenzung zu B297: B297 verhindert das Überschreiben eines gültigen Snapshots durch
  einen *echten* Fehler — B326 korrigiert die Klassifikation des leere-Lage-Falls selbst.
- Fix: Neue Funktion `_no_active_warning_snapshot()` liefert `status="ok"`,
  `data_available=False`, `error=None`. Echte Fehler (`http_error`,
  `json_parse_error`, `timeout`, `unexpected_error`) bleiben unverändert
  `status="error"`. Der Erfolgspfad mit echten Warndaten führt zusätzlich
  `data_available=True`. Der B297-Überschreibschutz wurde erweitert: ein
  bereits heute gespeicherter Snapshot mit echten Warndaten darf nicht durch ein
  späteres "keine Warnlage"-Ergebnis überschrieben werden (neue Hilfsfunktion
  `_todays_snapshot_had_real_data()`).
- Dateien: `skywarn_export_snapshot.py`, `tests/test_b175_skywarn_empty_payload.py`
  (3 Assertions an neues Verhalten angepasst), `tests/test_b326_skywarn_no_active_warning.py`.
- Test: `tests/test_b326_skywarn_no_active_warning.py`, `tests/test_b175_skywarn_empty_payload.py`.
- Phasen-Status (Hailo): unverändert; betrifft nur den täglichen Skywarn-Debug-Export,
  keine Auswirkung auf Tracking/Forecast/ML oder Phase B.

### B331 — EUMETView GetCapabilities: Request-Sturm bei anhaltenden Parse-Fehlern ✅ erledigt
- Ursache: `get_latest_wms_time()` (`cloud_height_from_eumetview.py`) cached
  ausschließlich das erfolgreiche Ergebnis. Jeder Fehlerfall (Parse-Fehler nach
  3 Retries, fehlender Ziel-Layer, fehlendes Zeit-Element, Exception) schrieb
  nichts in den Cache — der nächste Aufruf löste daher unabhängig vom zeitlichen
  Abstand erneut den vollen Fetch- + 3-fachen-Parse-Retry-Zyklus aus. Reproduziert:
  1751 `capabilities_request` in 24 h bei 93× `parse-failed-after-retries` und
  insgesamt 155× `timestamp_missing` — deutlich mehr Fremdrequests als nötig,
  entgegen der Zieldefinition ("unnötige Fremdrequests vermeiden").
- Fix: Neuer Negativ-Cache (`eumetview:capabilities_failed`, gleiche TTL wie der
  Erfolgs-Cache, Default 600 s) speichert den zuletzt aufgetretenen Fehlergrund.
  Ein Aufruf innerhalb der TTL überspringt den Fetch komplett und liefert direkt
  den bestehenden Datei-Fallback (`_caps_fallback`). Der Erfolgs-Cache und
  `_caps_fallback()` selbst bleiben unverändert.
- Dateien: `cloud_height_from_eumetview.py`,
  `tests/test_b331_eumetview_capabilities_negative_cache.py`.
- Test: `tests/test_b331_eumetview_capabilities_negative_cache.py`.
- Phasen-Status (Hailo): unverändert; reduziert externe Last für IR-/Cloud-Top-
  Datenbeschaffung, keine Auswirkung auf Phase B (Hailo-U-Net-Nowcasting).

### B332 — Bewegungs-Sequenzbildung nutzt cell_id statt volatiler id (Teilfix) ✅ erledigt
- Ursache: `build_dataset()` (`dataset_builder.py`, beide Sequenzbildungs-Schleifen)
  schlüsselte Sequenzen über die volatile Tracking-`id` statt der von
  `cell_lineage.py` stabil über Merge/Split/IR-Precursor-Brücken gepflegten
  `cell_id`. Ein Wechsel der `id` innerhalb einer Sequenz (z. B. kurzer
  Tracking-Sprung) ließ `common_ids` leerlaufen, obwohl dieselbe fachliche Zelle
  gemeint war.
- **Wichtig:** Dieser Fix behebt NICHT allein das im Debug-Export beobachtete
  `samples=0` — im geprüften 24h-Fenster war `id == cell_id` für jede Zelle
  (kein Merge/Split aufgetreten), das dortige `samples=0` liegt primär an
  `ML_SEQUENCE_LENGTH=6` bei Zell-Lebensdauern von 1-3 Frames. Diese Reduktion
  ändert die LSTM-Eingabeform (`model_training.py`) und erfordert Neutraining —
  das ist eine Architekturentscheidung, kein Bugfix, und wurde NICHT automatisch
  umgesetzt (siehe Rückfrage an Horst).
- Fix: `cell_id` (Fallback `id` für Legacy-Frames) als Sequenzschlüssel in
  beiden Schleifen von `dataset_builder.py`. Rein additiv/rückwärtskompatibel —
  reduziert niemals die Anzahl möglicher Sequenzen gegenüber dem alten Verhalten,
  kann sie in Merge/Split-/IR-Brücken-Fällen erhöhen.
- Dateien: `dataset_builder.py`, `tests/test_b332_dataset_builder_cell_id_key.py`.
- Test: `tests/test_b332_dataset_builder_cell_id_key.py`.
- Phasen-Status (Hailo): unverändert; Datenaufbereitung für das (aktuell im
  kinematischen Fallback laufende) Bewegungs-ML, keine Auswirkung auf Phase B.

### B335 — accuracy_tracker: mae_km/rmse_km/mae_px meldeten faelschlich 0.0 statt None bei verified=0 ✅ erledigt
- Ursache: `evaluate_for_horizon()` setzte `eval_n = verified if verified > 0 else 1`
  (Divisions-Fallback). Die Rueckgabe-Kennzahlen `mae_km`/`rmse_km`/`mae_px`/
  `rmse_x_px`/`rmse_y_px` pruefen `if eval_n else None` — da `eval_n` durch den
  Fallback nie 0 ist, griff der None-Guard nie. Horizonte ohne eine einzige
  verifizierte Vorhersage (z. B. +60 min bei fehlenden Ziel-Radarframes) meldeten
  dadurch eine scheinbar perfekte 0-km-Vorhersage in
  `forecast_quality_diagnosis_latest.json` und der taeglichen Analyse-Mail, obwohl
  `verified=0`. `_finish()` und der `n_total==0`-Base-Case waren bereits korrekt
  (`if ver/verified else None`) — nur der finale Return-Block war betroffen.
- Fix: `eval_n` vollstaendig entfernt; alle fuenf Kennzahlen dividieren jetzt direkt
  gegen `verified` mit `if verified else None`, analog zu `_finish()`.
- Dateien: `accuracy_tracker.py`, `tests/test_b335_accuracy_tracker_verified_zero_none.py`.
- Test: `tests/test_b335_accuracy_tracker_verified_zero_none.py`.
- Phasen-Status (Hailo): unveraendert; reine Korrektheits-Verbesserung der
  Nowcast-Verifikationsmetriken, keine Auswirkung auf Phase B (Hailo-U-Net-Nowcasting).

### B336 — model_usage-Report filterte nur auf samples statt auf verified ✅ erledigt
- Ursache: `_model_usage_from_accuracy_history()` (`tools/diagnose_forecast_quality.py`)
  waehlte pro Horizont die juengste Zeile mit `samples > 0` (= n_total, zaehlt auch
  no_target_frame/frame_empty/missed mit), ohne zu pruefen ob `verified > 0`. Ein
  Horizont ohne jede Verifikation (z. B. +60 min, samples=64, verified=0) landete
  dadurch im `model_usage.by_horizon`-Report und in der taeglichen Analyse-Mail,
  ohne dass Abdeckungskontext (`verified`/`coverage_rate`) im Ausgabeobjekt vorhanden
  war. Voraussetzung/Ergaenzung zu B335, das die Erzeuger-Seite (accuracy_tracker.py)
  korrigiert.
- Fix: Auswahl ueberspringt jetzt Zeilen mit `verified<=0` oder `mae_km is None`.
  `by_horizon`-Eintraege enthalten zusaetzlich `verified` und `coverage_rate`, damit
  ein `mae_km`-Wert nicht mehr ohne Abdeckungskontext interpretiert werden kann.
- Dateien: `tools/diagnose_forecast_quality.py`, `tests/test_b336_model_usage_verified_filter.py`.
- Test: `tests/test_b336_model_usage_verified_filter.py`.
- Phasen-Status (Hailo): unveraendert; reine Korrektheits-Verbesserung des
  Diagnose-/Mail-Reports, keine Auswirkung auf Phase B (Hailo-U-Net-Nowcasting).

### B337 — Codex-Review-Fix zu B336: verified-Filter behandelte fehlendes Feld wie verified=0 ✅ erledigt
- Ursache: B336 prüfte `int(_f(row.get("verified")) or 0) <= 0` — dabei liefert
  `row.get("verified")` sowohl bei explizit `verified=0` als auch bei GAR KEINEM
  `"verified"`-Feld `None`, wodurch beide Faelle identisch als "nicht verifiziert"
  behandelt wurden. `tests/test_b294_model_usage_aggregation.py` (Legacy-Schema
  ohne `"verified"`-Feld) brach dadurch: `_model_usage_from_accuracy_history()`
  lieferte faelschlich `status="not_available"` statt der vorhandenen Daten
  (reproduziert im `install.sh`-Pytest-Lauf: 24 failed, u. a.
  `test_latest_zero_sample_row_does_not_win`, `test_total_samples_consistent_with_by_horizon`,
  `test_newer_nonzero_row_replaces_older_nonzero`).
- Fix: Zeilen werden nur noch uebersprungen, wenn `"verified"` EXPLIZIT vorhanden
  UND `<= 0` ist. Fehlt das Feld komplett, wird die Zeile wie vor B336 behandelt
  (nur `mae_km is None`-Pruefung greift). `verified` im Ausgabe-Dict ist in diesem
  Fall `None` statt eines erfundenen Werts.
- Dateien: `tools/diagnose_forecast_quality.py`, `tests/test_b336_model_usage_verified_filter.py`.
- Test: `tests/test_b336_model_usage_verified_filter.py` (neuer Fall
  `test_model_usage_keeps_legacy_row_without_verified_field`),
  `tests/test_b294_model_usage_aggregation.py` (Regressionsschutz, unveraendert).
- Phasen-Status (Hailo): unveraendert; Korrektur einer eigenen Regression aus B336,
  keine Auswirkung auf Phase B (Hailo-U-Net-Nowcasting).

### B338 — Zwei sys.modules-Leaks aus B330/B331 kontaminierten die gesamte Testsession ✅ erledigt
- Ursache 1 (B331): `_stub_requests()` in
  `tests/test_b331_eumetview_capabilities_negative_cache.py` schrieb
  `sys.modules["requests"]` roh (ohne monkeypatch, ohne Wiederherstellung) mit
  einem unvollstaendigen Stub (fehlt `.exceptions.ConnectionError`, `.Response`).
  Blieb fuer den Rest der Session aktiv, kontaminierte u. a. `test_circuit_breaker.py`,
  `test_outlook_conn_break.py`, `test_outlook_series.py`, `test_training_readiness.py`.
- Ursache 2 (B330): `_import_http_retry_with_fake_requests()` in
  `tests/test_b330_retry_get_http_status_logging.py` entfernte `http_retry` per
  rohem `sys.modules.pop()` und baute einen Fake-`requests` ohne `.Response` —
  `http_retry.py`s Typ-Annotation `-> requests.Response` liess den Reimport mit
  AttributeError fehlschlagen, wonach CPython das Modul automatisch aus
  sys.modules entfernte. `http_retry` blieb danach dauerhaft verschwunden,
  kontaminierte u. a. `test_eumetview_parser.py`, `test_geosphere_nowcast_b88.py`,
  `test_nowcast_out_of_coverage_b131.py` (`KeyError: 'http_retry'`/`'url'`).
  Beide sind Instanzen der dokumentierten Fehlerklasse B96/B160/B161/B334.
- Fix: B331s Stub jetzt per `monkeypatch.setitem` (automatische Wiederherstellung).
  B330s Fake-`requests` bekommt einen `Response`-Platzhalter; der `pop()` ist
  jetzt `monkeypatch.delitem(..., raising=False)`.
- Dateien: `tests/test_b331_eumetview_capabilities_negative_cache.py`,
  `tests/test_b330_retry_get_http_status_logging.py`.
- Test: voller `pytest tests`-Lauf lokal verifiziert — vorher 24 durch diese
  Kontamination verursachte Fehlschlaege, danach 0.
- Phasen-Status (Hailo): unveraendert; reine Test-Infrastruktur-Korrektur
  (behebt eigene B330/B331-Regressionen), keine Auswirkung auf Produktionscode
  oder Phase B (Hailo-U-Net-Nowcasting).

### B339 — Hagelanzeige beruecksichtigte core_violet_ratio (P72) an zwei Stellen nicht ✅ erledigt
- Ursache 1: `MapFullscreen.jsx` (oeffentliche `/karte`-Ansicht ohne Auth) zeigte im
  separaten Hagel-Marker weiterhin `o.hail_prob` (violet-blinde Alt-Heuristik
  core_factor*cape_factor*height_factor) statt `o.hail_prob_effective`, das B324
  bereits korrekt nur in `MapView.jsx` gepatcht hatte. Bei niedrigem CAPE blieb
  der angezeigte Wert klein (z. B. 5%), obwohl `hail_warning` durch einen
  violetten Kern korrekt ausgeloest wurde.
- Ursache 2: `severity_predict._hail_index()` (steuert die Haupt-Popup-Zeile
  `🧊 {hail_cat} (...%)`, identisch in beiden Kartendateien) nutzte nur
  `core_ratio` (Rot+Violett kombiniert), nie `core_violet_ratio`. Bei geringem
  SHIP/CAPE blieb `hail_prob` unter der 0.25-Kategorie-Schwelle, `hail_cat`
  blieb "keiner" und die Zeile wurde komplett ausgeblendet — auch bei
  eindeutig violettem Kern.
- Fix: `_hail_index()` erhaelt denselben Violett-Floor wie
  `main.py._compute_hail_warning()`s `hail_prob_violet`
  (`HAIL_VIOLET_RATIO_SATURATION`, config.py, unveraendert). Der separate
  Kartenmarker (`hail_warning`-CircleMarker+Tooltip) wurde in BEIDEN
  Kartendateien vollstaendig entfernt (User-Vorgabe: keine Hagelanzeige
  ausserhalb des Zellen-Popups). Die bereits bestehende Popup-Zeile
  `o.severity.hail_cat`/`hail_prob` bleibt unveraendert und zeigt nun den
  korrekten Wert.
- Kein Schema-Change, kein Retraining: `core_violet_ratio` ist bereits seit
  P72 Teil von `ML_CELL_FEATURES`; diese Aenderung betrifft ausschliesslich
  den Severity-/Anzeigepfad.
- Dateien: `severity_predict.py`, `frontend/src/pages/MapView.jsx`,
  `frontend/src/pages/MapFullscreen.jsx`.
- Test: `tests/test_b339_severity_hail_violet_floor.py`.
- Phasen-Status (Hailo): unveraendert; reine UI-/Anzeigekorrektur, keine
  Auswirkung auf Phase B (Hailo-U-Net-Nowcasting).

### B340 — Open-Meteo-Fetcher nicht an Circuit-Breaker angebunden ✅ erledigt
- Ursache: `http_retry.retry_get()`s Circuit-Breaker ist vollständig auf
  `if breaker_service and api_circuit_breaker ...` gegated
  (`http_retry.py:148/168/183/236`). Fünf volumenstärkste Open-Meteo-Fetcher
  (`fetch_synoptic_features.py:123`, `fetch_openmeteo_extended.py:128/155/182/216`)
  übergaben `service=` (nur Logging) aber kein `breaker_service`, wodurch der
  Breaker für diese Dienste nie öffnete. Debug-Export 2026-07-11: 196
  wiederholte HTTP-429 in ~3,3 h ohne Breaker-Schutz.
- Fix: `breaker_service="openmeteo_forecast"` (ein gemeinsamer Key,
  providerweites Rate-Limit) an allen fünf Aufrufstellen ergänzt. Bestehende
  `except`-Fallbacks unverändert (fangen `CircuitOpenError` bereits ab, da
  Subklasse von `RequestException`).
- Dateien: `fetch_synoptic_features.py`, `fetch_openmeteo_extended.py`.
- Test: `tests/test_b340_openmeteo_breaker_service.py`.
- Phasen-Status (Hailo): unverändert; reine API-Resilienz-Korrektur, keine
  Auswirkung auf Phase B (Hailo-U-Net-Nowcasting).

### B341 — 12h-Outlook zeigte bei veraltetem 429-Fallback bereits vergangene Stunden ✅ erledigt
- Ursache: `convective_outlook.py:compute_outlook()` übernahm `offset_h`
  und `valid` 1:1 aus dem Serien-Index (Zeilen 222/223/242), ohne Bezug zur
  aktuellen Uhrzeit. Ist `atmosphere_timeseries.json` ein veralteter
  429-Fallback (`fetch_outlook_series.py:_load_fallback`, Zeilen 61-70),
  blieben bereits verstrichene `valid`-Zeitstempel erhalten. Debug-Export
  2026-07-11: `outlook_12h.json` (generated_at 21:58:25Z) zeigte
  `offset_h=1..3` mit `valid` 19:00/20:00/21:00 — bereits vergangen.
- Fix: Stunden mit `valid` vor der aktuellen Uhrzeit werden verworfen,
  `offset_h` wird nach dem Filtern ab 1 neu durchnummeriert. Ist die
  gesamte Serie veraltet, wird `{"hours": [], "stale": true}`
  zurückgegeben statt eines irreführenden leeren/veralteten Payloads.
- Dateien: `convective_outlook.py`.
- Test: `tests/test_b341_outlook_time_anchor.py`.
- Phasen-Status (Hailo): unverändert; reine Vorhersagezeitraum-Korrektur,
  keine Auswirkung auf Phase B (Hailo-U-Net-Nowcasting).

### B342 — IR->Radar-Score-Matching fiel bei Exception still auf Legacy-Matching zurueck ✅ erledigt
- Korrektur zur Original-KI-Analyse: der gemeldete Fehlerort main.py:536-559
  war falsch (Groessen-Regressor-Code) — der tatsaechliche Silent-Fallback
  liegt main.py:577-606 (try/except um `_score_match_ir_radar_lineage()`).
- Ursache: Wirft `_score_match_ir_radar_lineage()`
  (-> `cell_lineage.update_cell_lineage()` -> `apply_ir_radar_lineage_match()`)
  eine Exception, wurde dies nur per `debug_log()` protokolliert (nicht im
  Debug-Export enthalten) und STILL auf `_legacy_ir_radar_distance_match()`
  zurueckgefallen, die kein `ir_to_radar_confirmation`-Event/Positiv-Label
  schreibt. Erklaert strukturell, warum 24 selektierte Strong-Matches im
  Export zu 0 persistierten Confirmations fuehrten (sofern der
  Score-Matching-Zweig tatsaechlich eine Exception wirft).
- Fix: Neue Funktion `cell_lineage.record_lineage_fallback_error()`
  persistiert Exception-Typ/-Message/-Traceback nach
  `ir_radar_lineage_fallback_events.jsonl`; `main.py` ruft sie im
  Except-Zweig auf. Zusaetzlich unabhaengig gefundenen Diagnose-Zaehlfehler
  behoben: `radar_eligible_count` (cell_lineage.py) nutzte
  `_real_cell_id(cell_id)` statt des tatsaechlichen Skip-Kriteriums
  `lineage_status == "radar_confirmed"` aus `select_ir_radar_matches()` —
  seit B263 hat jedes Radar-Objekt eine WX-ID, wodurch der Zaehler
  systematisch nahe 0 blieb.
- Naechster Schritt (separater Prompt, erst nach neuem Export mit
  gefuellter `ir_radar_lineage_fallback_events.jsonl`): konkrete
  Exception-Ursache anhand des Tracebacks beheben.
- Dateien: `cell_lineage.py`, `main.py`.
- Test: `tests/test_b342_ir_radar_lineage_fallback.py`.
- Phasen-Status (Hailo): unveraendert; reine Diagnose-/Fehlersichtbarkeits-
  Korrektur, keine Auswirkung auf Phase B (Hailo-U-Net-Nowcasting).

### B343 — ML-Artefakt-Wegfall (Scaler/Modell) loeste keinen sichtbaren Alarm aus ✅ erledigt
- Ursache: `ml_readiness.check_ml_readiness()` ermittelt
  `ml_artifacts_available=false` (z. B. nach Quarantaene fehlender/invalider
  Scaler) und schreibt dies nur nach `evaluation/ml_readiness.json` — es gab
  KEINEN Mechanismus, der einen Uebergang "Modell war aktiv" -> "Modell
  fehlt jetzt" von einem echten Cold-Start unterscheidet. Debug-Export
  2026-07-11: `fallback_reason="missing_or_invalid_scalers"`, obwohl bis
  2026-07-05 ein promoviertes Modell operativ war (2495 ML-Samples).
- Fix: `check_ml_readiness()` vergleicht bei jedem Aufruf gegen die zuletzt
  persistierte `ml_readiness.json` (dieselbe Datei, die die Funktion selbst
  schreibt) und setzt bei einem Uebergang `true`->`false` das neue Feld
  `regression_alert`=true + `regression_reason`. Wird automatisch ueber
  `/api/ml_readiness` und `/api/admin/forecast-runtime-status`
  durchgereicht (keine Endpunkt-Aenderung nötig). Kinematischer Fallback
  und Shadow-Scoring bewusst UNVERAENDERT (nur Sichtbarkeit ergaenzt).
- Offen (separater Prompt nach Rücksprache): sichtbares Warn-Badge im
  Admin-Frontend bei `regression_alert=true`.
- Dateien: `ml_readiness.py`.
- Test: `tests/test_b343_ml_readiness_regression_alert.py`.
- Phasen-Status (Hailo): unveraendert; reine Beobachtbarkeits-Korrektur,
  keine Auswirkung auf Phase B (Hailo-U-Net-Nowcasting).

### B342-Korrektur — debug_log-Wortlaut und radar_eligible_count zurückgesetzt ✅ erledigt
- Nach Anwendung von B342 traten zwei Testfehlschläge auf:
  1. `test_1l2_ir_radar_score_matching.py::test_legacy_fallback_still_available`
     prüft den Original-Wortlaut der debug_log-Nachricht im Except-Zweig
     (main.py) — B342 hatte ihn um eine Typangabe erweitert und dadurch den
     geprüften Substring zerstört. Wortlaut wiederhergestellt; die
     Exception-Typ-Info ist weiterhin im `exception_type`-Feld von
     `record_lineage_fallback_error()` vorhanden.
  2. `test_b310_ir_radar_match_diagnostics.py::
     test_diagnostics_excludes_radar_objects_with_real_cell_id` zeigte,
     dass die B342-Umstellung von `radar_eligible_count` auf das
     `lineage_status`-Kriterium fachlich falsch war: `_real_cell_id(cell_id)`
     ist die bewusst gewählte, eigenständige Diagnose-Semantik (zählt
     Objekte ohne etablierte reale cell_id) und NICHT identisch mit dem
     Matching-Skip-Kriterium in `select_ir_radar_matches()`. War kein Bug —
     Änderung vollständig zurückgenommen.
- Die sichtbare Fehler-Persistenz aus B342
  (`cell_lineage.record_lineage_fallback_error()` + Aufruf in `main.py`)
  bleibt unverändert bestehen.
- Dateien: `main.py`, `cell_lineage.py`, `tests/test_b342_ir_radar_lineage_fallback.py`.
- Phasen-Status (Hailo): unverändert.

### B343-Korrektur — regression_alert verschwand nach einem Poll (Codex-Review) ✅ erledigt
- Codex-Review (P2) zu ml_readiness.py:263-264: die Bedingung prüfte nur
  den Uebergang true->false im selben Aufruf. Beim naechsten Poll war der
  persistierte Vorzustand bereits false, wodurch derselbe Aufruf
  regression_alert:false zurueckschrieb — der Alarm verschwand nach einem
  einzigen Refresh, obwohl die Artefakte weiterhin fehlten.
- Fix: regression_alert bleibt latched, solange ml_artifacts_available
  false ist (uebernimmt regression_reason des urspruenglichen Uebergangs).
  Zuruecksetzen ausschliesslich bei Recovery (ml_artifacts_available wird
  wieder true). Kein separater Ack-Mechanismus noetig.
- Dateien: `ml_readiness.py`.
- Test: `tests/test_b343_ml_readiness_regression_alert.py` (ergaenzt um
  Latch- und Recovery-Test).
- Phasen-Status (Hailo): unveraendert.

### B344 — Open-Meteo-Fallback-Werte waren unmarkiert (ununterscheidbar von echten Nullwerten) ✅ erledigt
- Ursache: Vier Open-Meteo-Fetcher (`fetch_700hpa_wind_per_object_slim.py`,
  `fetch_arome_openmeteo.py`, `fetch_openmeteo_extended.py`,
  `fetch_synoptic_features.py`) fallen bei API-Fehler/fehlendem Zeitslot auf
  feste Default-Werte zurueck, ohne dies zu markieren. Ein frueherer
  automatisierter Analyse-Report hatte nur zwei der vier betroffenen Module
  zitiert (und den Code-Ref fuer `wind_speed_500hPa` falsch zugeordnet — die
  tatsaechliche Quelle ist `fetch_openmeteo_extended.py`, nicht die zitierten
  Dateien). Zusaetzlich identifiziert: `fetch_synoptic_features.py` faellt
  nicht auf 0.0 zurueck, sondern auf einen plausiblen Klimamittelwert
  (`wind_500_speed=20.0`), wodurch selbst eine `zero_ratio`-Pruefung den
  Ausfall nicht erkennen wuerde.
- Fix: Alle vier Module setzen bei Fallback zusaetzlich `<feature>_fallback=1`
  auf dem Objekt. `accuracy_tracker._detail_record()` schreibt diese Marker
  in `forecast_error_details.jsonl`. `tools/diagnose_forecast_quality.py`
  benoetigte keine Aenderung (`fallback_ratio` liest bereits `<name>_fallback`).
- Bewusst NICHT geaendert: Fallback-WERTE selbst, Verhalten des
  kinematischen Forecasts. Die Konsum-Seite (`prediction.py::
  _steering_motion_vector_from_obj()`, nutzt `wind_500_speed` als
  Steuerstrom-Kandidat) wird in einem separaten Prompt (B345) behandelt.
- Dateien: `fetch_700hpa_wind_per_object_slim.py`, `fetch_arome_openmeteo.py`,
  `fetch_openmeteo_extended.py`, `fetch_synoptic_features.py`,
  `accuracy_tracker.py`.
- Test: `tests/test_b344_openmeteo_fallback_markers.py`.
- Phasen-Status (Hailo): unveraendert; reine Diagnose-/Feature-Qualitaets-
  Korrektur, keine Auswirkung auf Phase B (Hailo-U-Net-Nowcasting).

### B345 — Open-Meteo-Fallback-Wind (500hPa) unbemerkt als Steuerstrom genutzt ✅ erledigt
- Ursache: `prediction.py::_steering_motion_vector_from_obj()` nutzt
  `wind_500_speed` als Steuerstrom-Kandidat fuer junge/bewegungsunsichere
  Zellen (STEERING_BLEND_*). Der Open-Meteo-Fallback-Default fuer diesen
  Wert (`fetch_synoptic_features.py`, 20.0 km/h, konstante Richtung 270°)
  liegt UEBER dem Schwellwert `STEERING_BLEND_MIN_WIND_KMH` (10.0 km/h) und
  wurde dadurch bei API-Ausfall unbemerkt als gueltiger Steuerstrom
  verwendet, statt verworfen zu werden. Verifiziert aktiv in Produktion:
  Debug-Export zeigt reale Forecast-Zeilen mit
  `kinematic_source="...+steering"` und `steering_blend_applied=1`.
- Fix: Kandidat wird verworfen, wenn der B344-Marker
  `wind_500_speed_fallback` gesetzt ist; Funktion faellt in diesem Fall auf
  den 700hpa-Kandidaten zurueck (oder `None`, wenn auch dieser fehlt).
- Bewusst NICHT Teil dieses Fixes: der 700hpa-Kandidat
  (`wind_700hpa`, Quelle `fetch_atmospheric_snapshot.py`) hat noch kein
  aequivalentes Fallback-Marker-Feld — separater Prompt nach Verifikation.
- Nicht bestaetigt: ob der Synoptic-API-Ausfall im urspruenglich analysierten
  Debug-Zeitfenster (2026-07-11) tatsaechlich vorlag — dazu fehlte das
  Journal-Log fuer diesen Zeitraum im verfuegbaren Export. Der Fix behebt
  den Mechanismus unabhaengig davon.
- Dateien: `prediction.py`.
- Test: `tests/test_b345_steering_fallback_guard.py`.
- Phasen-Status (Hailo): unveraendert; reine Forecast-Robustheits-Korrektur,
  keine Auswirkung auf Phase B (Hailo-U-Net-Nowcasting).

### B346 — Restliche Open-Meteo-Fallback-Felder ohne Marker ✅ erledigt
- Ursache: B344 hatte bewusst nur die neun von
  `tools/diagnose_forecast_quality.py` ueberwachten Wetter-Features markiert.
  `fetch_openmeteo_extended.py` und `fetch_synoptic_features.py` liefern
  jedoch weitere Felder (`wind_gust_10m_kmh`, `wind_speed_850hPa`,
  `wind_dir_850_cos/sin`, `wind_dir_500_cos/sin`, `t500_c`, `t700_c`, `lpi`,
  `cin`, `pw`, `z500_dam`, `wind_500_dir_cos/sin`) mit demselben
  unmarkierten 0.0-Fallback-Muster.
- Fix: dieselbe Marker-Konvention (`<feld>_fallback=1`) auf alle vier
  Request-Bloecke in `fetch_openmeteo_extended.py::_apply()` sowie auf
  `fetch_synoptic_features.py::_FALLBACK_MARKERS_SYNOPTIC` ausgeweitet.
- Bewusst NICHT Teil dieses Fixes: Diese Felder werden aktuell NICHT in
  `accuracy_tracker.py`/`forecast_error_details.jsonl` mitgeschrieben
  (verifiziert). Die Marker liegen vorerst nur auf dem `obj`-Dict zur
  Vorbereitung; eine ML-Trainingspfad-Maskierung/-Imputation ist eine
  separate, groessere Entscheidung und nicht Teil dieses Prompts.
- Dateien: `fetch_openmeteo_extended.py`, `fetch_synoptic_features.py`.
- Test: `tests/test_b346_extended_fallback_markers.py`.
- Phasen-Status (Hailo): unveraendert.

### B347 — forecast_error_diagnosis.py::_read_jsonl uebernahm Zeilen ohne Zeitstempel immer ins Fenster ✅ erledigt
- Ursache: `_read_jsonl()` behandelte Zeilen mit unparsbarem/fehlendem
  Zeitstempel als "immer im Fenster" statt sie auszuschliessen —
  inkonsistent zu `drift_detector._parse_ts()` (dort: unparsbar =
  ausgeschlossen). Aktuell wahrscheinlich folgenlos, da
  `accuracy_tracker._detail_record()` alle Zeitstempelfelder zuverlaessig
  schreibt (verifiziert), aber bei Altbestand/Formataenderungen ein
  latentes Risiko fuer dauerhaft verzerrte 24h-Fenster in der
  Root-Cause-Diagnose.
- Fix: unparsbare/fehlende Zeitstempel werden jetzt konsistent
  ausgeschlossen.
- Dateien: `forecast_error_diagnosis.py`.
- Test: `tests/test_b347_read_jsonl_ts_exclusion.py`.
- Phasen-Status (Hailo): unveraendert.

### B348 — Diagnose-Proxy für Beschleunigungs-Validierung (Vorbereitung B349) ✅ erledigt
- Hintergrund: B307 (Beschleunigungsterm) ist per Default deaktiviert und
  nie gegen reale Daten validiert. Mathematische Nachrechnung zeigt: EWMA
  unterschätzt systematisch die Geschwindigkeit beschleunigender Zellen,
  Größenordnung deckt sich mit beobachtetem Drift-Alarm-Bias
  (speed_error_kmh -6 bis -10 km/h).
- Fix: `kinematic_accel_proxy_kmh` (Differenz der letzten zwei
  Intervallgeschwindigkeiten) wird jetzt IMMER berechnet — unabhängig von
  `KINEMATIC_ACCELERATION_ENABLED` — und zusammen mit
  `kinematic_acceleration_applied` (ob der B307-Term tatsächlich in die
  Projektion einging) in `forecast_error_details.jsonl` mitgeschrieben.
- Bewusst NICHT Teil dieses Fixes: kein Verhaltens-Fix, keine automatische
  Auswertung. Die Auswertung folgt in B349 (neues Diagnose-Skript).
- Dateien: `prediction.py`, `accuracy_tracker.py`.
- Test: `tests/test_b348_kinematic_accel_proxy.py`.
- Phasen-Status (Hailo): unverändert.

### B349 — Beschleunigungs-Validierung automatisch im 24h-Export ✅ erledigt
- Ziel: Die Drift-Root-Cause-Hypothese (EWMA unterschätzt Geschwindigkeit
  beschleunigender Zellen, B307/B348) automatisch bei jedem Export prüfen,
  statt manuell per Ad-hoc-Skript.
- Fix: Neues Skript `tools/diagnose_kinematic_acceleration.py` (analog
  `diagnose_forecast_quality.py`), gruppiert `forecast_error_details.jsonl`
  nach Beschleunigungs-Proxy-Bucket, berechnet signierten Speed-Error
  (actual − forecast) und eine Pearson-Korrelation. Wird über
  `export_diagnosis.run_kinematic_acceleration_diagnosis_before_export()`
  automatisch vor jedem 24h-Export ausgeführt (analog
  `run_forecast_quality_diagnosis_before_export`), Ergebnis landet als
  `kinematic_acceleration_validation_latest.json` im Export.
- Bewusst NICHT Teil dieses Fixes: kein Verhaltens-Fix an der Forecast-Logik.
  Aktivierung von `KINEMATIC_ACCELERATION_ENABLED` bleibt eine manuelle
  Entscheidung von Horst anhand der Diagnose-Ergebnisse.
- Dateien: `tools/diagnose_kinematic_acceleration.py` (neu),
  `export_diagnosis.py`, `debug_export.py`.
- Test: `tests/test_b349_kinematic_acceleration_diagnosis.py`.
- Phasen-Status (Hailo): unverändert.

### B350 — Letzter Export immer auf der Logs-Seite verfügbar ✅ erledigt (Fach-Feature)
- Ziel: Export-ZIPs wurden bisher nur im Moment der Erstellung zum Browser
  gestreamt und danach aus dem Temp-Ordner gelöscht — keine persistente,
  jederzeit abrufbare Kopie auf dem Server.
- Fix: `debug_export.persist_latest_export()` legt nach jedem erfolgreichen
  Build eine Kopie an einem stabilen Ort ab (atomarer Wechsel via
  Tmp-Verzeichnis + rename). Neue Endpunkte
  `/api/admin/export/latest/meta` und `/api/admin/export/latest.zip`
  liefern Metadaten bzw. Datei OHNE neuen Build. `Logs.jsx` zeigt den
  zuletzt persistierten Export mit Zeitstempel/Größe/Teileanzahl an und
  bietet direkten Download.
- Dateien: `debug_export.py`, `app.py`, `frontend/src/pages/Logs.jsx`.
- Test: `tests/test_b350_latest_export_download.py`.
- Frontend-Build lokal angestoßen; in dieser Umgebung blockiert die fehlende Rollup-Optional-Dependency `@rollup/rollup-linux-x64-gnu` den Abschluss.
- Phasen-Status (Hailo): unverändert.

### B351 — /api/config lieferte HTTP 500 statt 400 bei QUALITY_TARGET_MAE_KM_<=30 ✅ erledigt
- Ursache: `api_config_save()` fing nur `forbidden_keys_in()`-Verstöße
  (Secrets/UPSCALE_FACTOR) ab. Die unabhängige Sperre für
  `QUALITY_TARGET_MAE_KM_<=30` (zieldefinition.txt) wird erst innerhalb von
  `runtime_config.patch()` via `validate_override_key()` geprüft und wirft
  dort einen `ValueError` — unbehandelt, daher HTTP 500. Reproduziert im
  Live-Betrieb beim Speichern von Runtime-Overrides über das Admin-Panel.
- Fix: `runtime_config.patch(data)`-Aufruf in `api_config_save()` in
  try/except gekapselt; `ValueError` wird als HTTP 400 mit der
  ursprünglichen, bereits verständlichen Fehlermeldung ausgeliefert.
- Dateien: `app.py`.
- Test: `tests/test_b351_config_save_value_error.py`.
- Phasen-Status (Hailo): unverändert.

### B352 — GET /api/config lieferte strukturell nie-überschreibbare Keys ✅ erledigt
- Ursache: Die Admin-UI befüllt das Overrides-Textfeld mit dem kompletten
  `all_effective()`-Dump. Dieser enthält Schlüssel, die als Override
  niemals akzeptiert werden können (`UPSCALE_FACTOR`,
  `QUALITY_TARGET_MAE_KM_FIXED`/`_CONFIGURABLE_DEFAULT`) sowie maskierte
  (aber nicht entfernte) verschachtelte Secret-Pfade wie
  `GITHUB_VERIFY_CONFIG.token`. "Kompletten Stand kopieren, kleine Änderung
  machen, speichern" führte dadurch zuverlässig zu einem Fehler (B351:
  vorher 500, danach 400 — Ursache blieb).
- Fix: `runtime_config.is_editable_override_key()` filtert Top-Level-Keys,
  die `validate_override_key()`/`is_forbidden_override_key()` ohnehin
  ablehnen würden; `runtime_config.strip_forbidden_recursive()` entfernt
  verschachtelte Secret-Pfade vollständig (statt sie nur zu maskieren).
  `GET /api/config` liefert jetzt nur noch Schlüssel, die 1:1
  zurückgepostet werden können.
- Dateien: `runtime_config.py`, `app.py`.
- Test: `tests/test_b352_config_get_excludes_non_editable.py` (inkl.
  Kern-Test: kompletter GET-Response als POST-Payload muss immer 200 liefern).
- Phasen-Status (Hailo): unverändert.

### B353 — Per-Objekt-Services im Admin-Dashboard fälschlich als „überfällig“ markiert ✅ erledigt
- Ursache: `api_cache_status()` berechnet `next_fetch_ts`/STALE-Status TTL-basiert für
  alle Namespaces identisch. Für die acht Per-Objekt-Services (`openmeteo_icon_d2`,
  `openmeteo_icon_eu_li`, `openmeteo_icon_global`, `openmeteo_synoptic_500`,
  `openmeteo_extended_15min/_pressure/_lpi/_gfs_conv`, plus `geosphere_cape`,
  `geosphere_nowcast`), die nur bei aktiv getrackten Sturmzellen einen Fetch auslösen,
  führt das bei 0 Objekten über längere Zeit zuverlässig zu einer irreführenden
  orangen „(fällig)“-Anzeige im Admin-Dashboard, obwohl kein Fehler vorliegt.
- Fix: `app.py::api_cache_status()` liefert je Namespace zusätzlich `per_object: bool`.
  `Dashboard.jsx` zeigt für Per-Objekt-Namespaces bei Überfälligkeit statt der orangen
  „(fällig)“-Warnung einen neutralen Hinweis „bei Bedarf (kein aktuelles Objekt)“.
  Kontinuierlich geplante Services (z. B. `geosphere_tawes_all`) sind unverändert.
- Dateien: `app.py`, `frontend/src/pages/Dashboard.jsx`.
- Test: `tests/test_b353_per_object_cache_status_flag.py`.
- Phasen-Status (Hailo): unverändert.

### B354 — X-Achse der Accuracy-Charts zeigte unbeschrifteten Lauf-Index statt Messzeitpunkt ✅ erledigt
- Ursache: Die drei Zeitreihen-Charts auf „Vorhersagegenauigkeit (Closed-Loop)“ (MAE,
  Hit-Rate, ML-Lernfortschritt) nutzten `dataKey="idx"` (reiner Lauf-Index 1..N) ohne
  Achsenbeschriftung und ohne Zeitbezug im Tooltip, obwohl `/api/accuracy`
  (`timestamp_utc`) und `/api/ml_quality` (`ts`) den echten Messzeitpunkt bereits
  liefern — er wurde beim Aufbau der Frontend-Datenserien nur nie übernommen.
  Zusätzlich fehlte der Hit-Rate-Y-Achse die Einheit „%“.
- Fix: Neue Utility `frontend/src/utils/chartTime.js`
  (`formatChartTimestamp`, `buildIdxTimestampMap`). `Accuracy.jsx` übernimmt `ts`
  in alle drei Datenserien und zeigt auf allen drei Charts den formatierten
  Messzeitpunkt als Achsen-Tick-Label und Tooltip-Titel (Fallback `#<idx>` ohne
  Zeitstempel). Hit-Rate-Y-Achse hat jetzt das Label „%“.
- Hinweis (nicht mitgefixt, separater Root Cause): `/api/accuracy` lädt die
  Historie unabhängig vom „Zeitraum“-Filter immer mit mindestens 7 Tagen
  (`load_history(since_hours=max(since, 24*7))`) — bei Auswahl „24 Stunden“
  werden dadurch bis zu 7× mehr Punkte angezeigt als erwartet. Kandidat für
  einen eigenen B-Nummer-Prompt.
- Dateien: `frontend/src/pages/Accuracy.jsx`, `frontend/src/utils/chartTime.js`
  (neu), `frontend/src/utils/chartTime.test.js` (neu).
- Test: `tests/test_b354_accuracy_chart_axis_timestamps.py`.
- Phasen-Status (Hailo): unverändert.

### B355 — „Zeitraum“-Filter auf der Closed-Loop-Seite wirkte auf mehrere Bereiche nicht ✅ erledigt
- Ursache: Drei getrennte Stellen im selben Code-Pfad ignorierten den vom Nutzer gewählten
  „Zeitraum“ (`hours`) ganz oder teilweise: (1) `api_accuracy()` hob `history` künstlich auf
  mindestens 7 Tage an (`max(since, 24*7)`), wodurch 1h/6h/24h/7d-Auswahl identische
  Chart-Daten lieferte; (2) `api_ml_quality()` tat dasselbe für `series` und
  `verification_coverage_by_horizon` (`max(since, 24)` bzw. `max(since, 24*7)`);
  (3) `/api/api_health` ignoriert `hours` komplett (fester täglicher Check), das Frontend
  suggerierte mit „API-Health (letzte {hours} h)“ dennoch Reaktion auf den Filter.
- Fix: (1)+(2) künstliche Mindest-Klammerungen entfernt — `history`/`series`/
  `verification_coverage_by_horizon` folgen jetzt exakt dem gewählten Zeitraum, wie es
  `evaluate_all()`/`current` bereits tat. (3) Karten-Überschrift und Beschreibungstext
  korrigiert, zeigt jetzt den eigenen `checked_at_utc`-Zeitpunkt statt einen irreführenden
  `{hours}`-Bezug; Fake-Parameter aus dem Frontend-Fetch entfernt. Zusätzlich zeigt die
  Diagnose-Kachel jetzt ihr eigenes festes Diagnose-Fenster (`hours`-Feld) mit Hinweis, dass
  sie unabhängig vom Zeitraum-Dropdown ist.
- Dateien: `app.py`, `frontend/src/pages/Accuracy.jsx`.
- Test: `tests/test_b355_accuracy_zeitraum_filter.py`.
- Phasen-Status (Hailo): unverändert.

### B356 — ConvLSTM-Wochentraining: RLIMIT_AS wurde vom System-OOM-Killer unterlaufen ✅ erledigt
- Ursache: `CONVLSTM_TRAIN_MEM_LIMIT_GB` (statisch 12 GB) wurde 1:1 als RLIMIT_AS
  des isolierten Trainings-Subprozesses gesetzt, ohne den tatsächlich freien RAM
  zum Trainingszeitpunkt zu berücksichtigen. Laufen `wetterprojekt`,
  `wetterprojekt-scheduler`, `wetterprojekt-admin` und nginx parallel weiter, kann
  der real freie RAM unter 12 GB liegen — dann greift der system-weite
  Kernel-OOM-Killer (SIGKILL, rc=-9) BEVOR der Prozess selbst an sein eigenes
  Adressraum-Limit stößt. Der beabsichtigte planbare, abfangbare
  MemoryError-Pfad (inkl. Batch-Size-Retry) wurde dadurch nie erreicht. Zusätzlich
  fing der bisherige Retry nur `"ResourceExhausted" in str(exc)` ab (TF-spezifisch),
  nicht ein rohes `MemoryError`, und kaskadierte nur einmal (4→2), nicht bis 1.
- Fix: `scheduler.run_convlstm_weekly_job()` berechnet das effektive RLIMIT_AS jetzt
  dynamisch als `min(CONVLSTM_TRAIN_MEM_LIMIT_GB, aktuell_frei_GB via psutil -
  CONVLSTM_TRAIN_MEM_SAFETY_MARGIN_GB)` (neue Konfig-Konstante, Default 1.5 GB) und
  loggt den berechneten Wert. `radar_convlstm.train_convlstm()` kaskadiert bei
  Speichermangel jetzt über `batch_size → 2 → 1` und fängt sowohl `MemoryError`
  als auch `ResourceExhausted` ab.
- Bewusst NICHT Teil dieses Fixes: keine Änderung an der Streaming-Sequence (B147)
  oder am Frame-Cap (`CONVLSTM_MAX_FRAMES`) — die Datenhaltung war nicht die Ursache.
- Dateien: `config.py`, `scheduler.py`, `radar_convlstm.py`.
- Test: `tests/test_b356_convlstm_mem_cascade.py`.
- Phasen-Status (Hailo): unverändert.

### B357 — ConvLSTM-Trainingsergebnis strukturiert erfassen (Diagnose zu B356) ✅ erledigt
- Ziel: Nach B356 (dynamisches RLIMIT_AS + Batch-Size-Kaskade bis 1) automatisch
  sichtbar machen, ob ein Trainingslauf erfolgreich war, mit welcher batch_size
  er lief, oder ob er trotzdem vom System-OOM-Killer/Timeout beendet wurde —
  ohne dafür manuell im journal-Export nach Freitext-Logzeilen suchen zu müssen.
- Fix: `radar_convlstm.py` schreibt bei jedem Trainingslauf (Erfolg, Skip,
  Exception) einen strukturierten Eintrag in
  `train_data/evaluation/convlstm_training_runs.jsonl`. Für die beiden Fälle,
  in denen der Kind-Prozess keine Chance mehr dazu hat (System-OOM-Kill,
  Timeout), schreibt `scheduler.run_convlstm_weekly_job()` selbst einen
  Fallback-Eintrag mit den nur dort bekannten Werten (effektives RLIMIT_AS,
  statisches Limit). Neues Skript `tools/diagnose_convlstm_training.py`
  (analog `diagnose_kinematic_acceleration.py`) fasst die letzten Läufe
  zusammen und landet automatisch vor jedem Export als
  `convlstm_training_diagnosis_latest.json` im Export.
- Bewusst NICHT Teil dieses Fixes: keine Änderung an der Trainingslogik selbst
  (B356 bleibt unverändert), keine automatische Reaktion auf wiederholte
  OOM-Kills (z. B. automatisches Absenken von `CONVLSTM_MAX_FRAMES`) — das
  bleibt eine manuelle Entscheidung von Horst anhand der Diagnose-Ergebnisse.
- Dateien: `radar_convlstm.py`, `scheduler.py`, `export_diagnosis.py`,
  `debug_export.py`, `tools/diagnose_convlstm_training.py` (neu).
- Test: `tests/test_b357_convlstm_training_telemetry.py`.
- Phasen-Status (Hailo): unverändert.

### B358 — RAM-Verlauf im Dashboard + ConvLSTM-Trainingsstatus im Admin Panel ✅ erledigt (Fach-Feature)
- Ziel: B356 (dynamisches RLIMIT_AS) und B357 (Trainings-Telemetrie) waren
  bisher nur im 24h-Debug-Export sichtbar. Horst wollte den ConvLSTM-
  Trainingsstatus direkt im Admin Panel sehen, zusammen mit einem
  allgemeinen Arbeitsspeicher-Verlauf, um beurteilen zu können, wie knapp
  der RAM tatsächlich wird.
- Fix Teil A: Neues `mem_monitor.py` (analog `cpu_monitor.py`) sampelt RAM
  alle 5 Min via psutil, speichert `train_data/system/mem_history.jsonl`
  (max. 288 Einträge/24h). Neuer Endpoint `/api/mem_history`, neue
  `MemChart`-Komponente im Dashboard (analog `CpuChart`).
- Fix Teil B: Neuer Endpoint `/api/admin/convlstm/status` liest die letzten
  Einträge aus `convlstm_training_runs.jsonl` (B357) über die neue Funktion
  `radar_convlstm.get_recent_training_runs()`. Neue `ConvlstmStatusCard`-
  Komponente auf der Training-Seite zeigt Ergebnis, verwendete `batch_size`
  und ggf. OOM-/Timeout-Warnung des letzten Laufs direkt neben den
  bestehenden Zeitplan-Einstellungen.
- Dateien: `mem_monitor.py` (neu), `scheduler.py`, `app.py`,
  `radar_convlstm.py`, `frontend/src/pages/Dashboard.jsx`,
  `frontend/src/pages/Training.jsx`.
- Test: `tests/test_b358_ram_verlauf_und_convlstm_status.py`.
- Phasen-Status (Hailo): unverändert.

### B359 — sys.modules-Kontamination von accuracy_tracker verwaiste app.py-Referenzen ✅ erledigt
- Ursache: Vier Testdateien riefen `sys.modules.pop("accuracy_tracker", None)`
  auf, um vor dem Import ein gestubtes `debug_utils` einzuschleusen. Das
  erzeugt bei jedem Aufruf ein neues Modul-Objekt in `sys.modules` — `app.py`s
  bereits beim ersten Import gebundene Referenzen (`evaluate_all`,
  `load_history`) zeigten danach für den Rest der Testsession auf das ALTE,
  verwaiste Modul-Objekt. Dadurch schlug
  `test_b355_accuracy_zeitraum_filter.py::test_history_respects_narrow_window_without_7day_floor`
  fehl, sobald eine der vier Dateien vorher lief (alphabetische
  Collection-Reihenfolge) — `monkeypatch.setattr(accuracy_tracker, "HISTORY_FILE", ...)`
  patchte ein Modul-Objekt, das `app.py` gar nicht mehr verwendete, wodurch
  echte Produktions-/Testdaten statt der Fixture-Daten gelesen wurden. Kein
  Zusammenhang mit B355 selbst oder mit B356/B357/B358.
- Fix: `sys.modules.pop("accuracy_tracker", ...)` in allen vier Dateien
  entfernt. Statt eines gestubten `debug_utils`-Moduls vor dem Reimport wird
  jetzt das bereits importierte, session-weit EINE `accuracy_tracker`-Modul
  direkt per `monkeypatch.setattr(at, "debug_log", ...)` gepatcht (automatisches
  Teardown durch pytest, kein `sys.modules` wird mehr verändert).
- Dateien: `tests/test_b296_nn_threshold_and_median.py`,
  `tests/test_b335_accuracy_tracker_verified_zero_none.py`,
  `tests/test_accuracy_tracker_horizon_mode.py`,
  `tests/test_c1_dashboard_forecast_mode.py`.
- Test: `tests/test_b359_accuracy_tracker_no_sys_modules_pop.py`.
- Phasen-Status (Hailo): unverändert.

### B360 — std::bad_alloc (SIGABRT) umging die kindseitige Batch-Size-Kaskade komplett ✅ erledigt
- Ursache: Realer Testlauf zeigte `rc=-6` mit `terminate called after throwing
  an instance of 'std::bad_alloc'`. TensorFlows nativer C++-Allocator wirft
  bei Erreichen von RLIMIT_AS (B356) keine abfangbare Python-Exception,
  sondern beendet den Prozess per SIGABRT via std::terminate() — die
  kindseitige Batch-Size-Kaskade (B356, train_convlstm) erreicht dabei
  nie einen try/except. Zusaetzlich schrieb `scheduler.run_convlstm_weekly_job()`
  nur fuer rc in (-9, 137) einen Fallback-Telemetrie-Eintrag (B357) — rc=-6
  und andere Signal-Tode blieben unsichtbar in `convlstm_training_runs.jsonl`,
  die ConvlstmStatusCard (B358) zeigte weiterhin "noch kein Lauf".
- Fix: `scheduler.run_convlstm_weekly_job()` kaskadiert jetzt selbst ueber
  `--batch-size 4 → 2 → 1`, sobald das Kind durch ein Signal (rc < 0) stirbt —
  nur der Elternprozess kann jeden Tod des Kindes zuverlaessig erkennen.
  `_write_convlstm_fallback_record()` erweitert um `batch_size`/`attempt`;
  jeder Signal-Tod (nicht nur SIGKILL) erzeugt jetzt einen Telemetrie-Eintrag
  (`system_oom_kill` fuer -9/137, generisch `child_aborted_signal_<N>` fuer
  andere Signale wie SIGABRT). Diagnose-Skript und ConvlstmStatusCard erklaeren
  den neuen Outcome-Typ verstaendlich.
- Bewusst NICHT Teil dieses Fixes: die kindseitige B356-Kaskade bleibt
  bestehen (Defense-in-Depth fuer abfangbare Faelle) und wird nicht entfernt.
- Dateien: `scheduler.py`, `tools/diagnose_convlstm_training.py`,
  `frontend/src/pages/Training.jsx`.
- Test: `tests/test_b360_convlstm_parent_batch_cascade.py`.
- Phasen-Status (Hailo): unverändert.

### B361 — Codex-Review-Fix zu B360: batch_size=1 wurde nie wirklich versucht ✅ erledigt
- Ursache (Codex-Review-Finding P1 zur B360-PR): `train_convlstm()` hob jeden
  angeforderten `batch_size` unter 2 per `safe_batch_size = 2 if batch_size < 2
  else batch_size` wieder auf 2 an. Seit B360 waehlt der Elternprozess
  (`scheduler.py`) `batch_size=1` als expliziten, eigenstaendigen letzten
  Rettungsversuch — dieser Clamp sorgte dafuer, dass der dritte
  Kaskaden-Versuch faktisch batch_size=2 ein zweites Mal ausfuehrte, statt
  echt mit batch_size=1 zu trainieren.
- Fix: Clamp durch `safe_batch_size = max(1, int(batch_size))` ersetzt —
  batch_size=1 wird jetzt unveraendert durchgereicht, batch_size=2/4
  verhalten sich wie zuvor (kein Regress).
- Zweiter Codex-Finding (P2, `_os`-Scope in `_write_convlstm_fallback_record`)
  war beim Review bereits im committeten Code korrekt geloest — kein
  Handlungsbedarf.
- Dateien: `radar_convlstm.py`.
- Test: `tests/test_b361_batch_size_one_not_clamped.py`.
- Phasen-Status (Hailo): unverändert.

### B362 — Cross-Process-Race verursachte stillen Verlust von Runtime-Overrides ✅ erledigt
- Ursache: LOCATIONS_WATCHLIST (inkl. E-Mail/WhatsApp je Ort) verschwand
  nachweislich zwischen zwei install.sh-Laeufen aus runtime_overrides.json,
  ohne dass install.sh oder ein Speichern ueber die Admin-Oberflaeche dafuer
  ursaechlich war. Root Cause: `wetterprojekt`, `wetterprojekt-scheduler` und
  `wetterprojekt-admin` laufen als unabhaengige Prozesse mit je eigenem
  In-Memory-Cache (runtime_config._OVERRIDES). `patch()`/`patch_exact_key()`
  mergten gegen diesen moeglicherweise veralteten Cache statt gegen den
  tatsaechlichen Platteninhalt und schrieben danach die GESAMTE Datei zurueck
  — ein `patch()`-Aufruf fuer einen VOELLIG ANDEREN Key aus einem Prozess mit
  veraltetem Cache konnte dadurch zwischenzeitliche Schreibvorgaenge eines
  ANDEREN Prozesses lautlos ueberschreiben.
- Fix: `patch()` und `patch_exact_key()` rufen jetzt unmittelbar vor dem
  Merge `reload_overrides()` auf — laden also den aktuellen Platteninhalt,
  statt sich auf den In-Memory-Cache zu verlassen. Schliesst das Race-Fenster
  auf die kurze Spanne zwischen Reload und Save (dateibasiert per fcntl.flock
  bereits geschuetzt), ohne die Aufrufer-API zu aendern.
- Bewusst NICHT Teil dieses Fixes: eine vollstaendige cross-process
  Transaktion ueber den gesamten Reload-Merge-Save-Zyklus (echter
  Exclusive-Lock ueber die gesamte Operation) — falls der Verlust danach
  nochmal auftritt, ist das der naechste Schritt.
- Dateien: `runtime_config.py`.
- Test: `tests/test_b362_runtime_config_cross_process_race.py`.
- Phasen-Status (Hailo): unverändert.

### B363 — Veralteter B357-Test nach B360-Refactor korrigiert ✅ erledigt
- Ursache: B360 ersetzte die feste Zeile `outcome="system_oom_kill"` in
  `run_convlstm_weekly_job()` durch eine Fallunterscheidung, die zusaetzlich
  `child_aborted_signal_N` (SIGABRT/std::bad_alloc, siehe B360) abdeckt —
  bewusste, korrekte Aenderung. Der aeltere B357-Test pruefte aber noch
  wortwoertlich auf die alte, feste Aufruf-Form und schlug dadurch fehl.
  Kein Funktionsfehler im Produktivcode.
- Fix: Testassertion an die neue Struktur angepasst (prueft jetzt auf das
  `outcome`-Literal, `child_aborted_signal_`-Praefix und `outcome=outcome`
  statt auf die feste alte Zeile).
- Dateien: `tests/test_b357_convlstm_training_telemetry.py`.
- Test: kein neuer Test noetig, bestehender Test korrigiert.
- Phasen-Status (Hailo): unverändert.

### B364 — B362 durchbrach Test-Isolationsmuster (reload_overrides() ungemockt) ✅ erledigt
- Ursache: B362 fuegte `reload_overrides()` als erste Zeile von
  `runtime_config.patch()`/`patch_exact_key()` ein (korrekt, schliesst die
  Cross-Process-Race). Mehrere Tests isolierten sich bislang nur ueber
  `monkeypatch.setattr(rc, "_OVERRIDES", {...})` + `monkeypatch.setattr(rc,
  "save", ...)`, ohne `reload_overrides()` zu mocken — seit B362 ueberschreibt
  dieser Aufruf den bewusst gesetzten Testzustand mit dem Inhalt der ECHTEN
  `train_data/runtime_overrides.json` von der Platte. Kein Regressionsfehler
  im Produktivcode, reiner Testisolationsbruch.
- Fix: Alle betroffenen `patch()`-aufrufenden Tests mocken jetzt zusaetzlich
  `reload_overrides` als No-Op. Tests, die nur `get()`/GET-Requests nutzen
  (kein `patch()`-Aufruf), sind unveraendert, da nicht betroffen.
- Dateien: `tests/test_b351_config_save_value_error.py`,
  `tests/test_config_override_guard.py`,
  `tests/test_hydro_runtime_config_contract.py`.
- Test: `tests/test_b364_runtime_config_test_isolation.py`.
- Phasen-Status (Hailo): unverändert.

### B365 — Stage-2-Fallback-Matching erlaubte Fehlzuordnung an unabhängige Zellen bei fast aufgelöster Ursprungszelle ✅ erledigt
- Ursache: Die Distanzschwelle des Stage-2-Centroid-Fallbacks
  (`_STAGE2_MAX_DIST` = `MAX_CELL_SPEED_KMH / PX_TO_KMH × UPSCALE_FACTOR ×
  1.5` ≈ 18,75 km) galt unabhaengig vom Zustand der Ursprungszelle. Anhand
  echter Debug-Export-Daten (2026-07-14) verifiziert: Zelle `MSAXMF9K`
  wurde bei `core_ratio = 0.0` (praktisch aufgeloest) faelschlich mit
  einer 16,9 km entfernten, unabhaengigen Zelle fortgesetzt (Sprung in
  einem 5-Min-Frame, Richtung drehte von 100° ESE auf 315° NW). `lineage`
  blieb durchgehend "continued", kein Merge/Split. Kalman-Geschwindigkeit
  und -Richtung wurden dadurch korrumpiert und in der Live-Karte falsch
  angezeigt.
- Fix: Neue Konstante `STAGE2_WEAK_CELL_MAX_SPEED_KMH` (60 km/h, kein
  1.5×-Puffer) greift, wenn `core_ratio` der Vorperiode unter
  `WAS_ACTIVE_CORE_RATIO_THRESHOLD` liegt. Aktive/kraeftige Zellen sind
  unveraendert vom bisherigen, grosszuegigeren Cap betroffen.
- Dateien: `config.py`, `object_tracking.py`.
- Test: `tests/test_b365_stage2_weak_cell_match_cap.py`.
- Phasen-Status (Hailo): unveraendert — reiner Tracking-Genauigkeits-Fix,
  keine Hailo-Auswirkung. Hinweis fuer MAE-Drift-Untersuchung: dieser Bug
  ist ein potenzieller (bisher nicht dokumentierter) weiterer Beitrag zur
  MAE-Drift, da falsche Zugrichtung/-geschwindigkeit direkt in Kinematik-
  Fallback und ML-Features (vx/vy, core_ratio-Serie) einfliesst. Sollte in
  der naechsten Drift-Analyse gegen die drift_detector.py-Historie
  beruecksichtigt werden.

### P73 — Letzte Stationsbegegnung der Zelle zur Abschätzung zu erwartender Böen ✅ erledigt
- Feature: Neues Feld `last_station_encounter` hält fest, was an Wind
  (FF), Böe (FFX) und Richtung (DD) gemessen wurde, als die Zelle
  ZULETZT im engen Bereich (Default 10 km, `STATION_ENCOUNTER_MAX_KM`,
  Admin-Panel-tunbar) einer TAWES-Station war — bleibt über den
  gesamten weiteren Lebenszyklus der Zelle erhalten, auch nachdem die
  Zelle die Station wieder verlassen hat. Ziel: reale Ist-Messung zur
  Abschätzung/Plausibilisierung zu erwartender Böen. Anzeige im
  Zell-Popup der Live-Karte, Archivierung im Track-Ende-Record
  (`track_ends.jsonl`).
- Persistenz: `update_tracking_memory()` liefert NEUE, von
  `tracking_memory` unabhängige Dicts zurück (verifiziert) — daher folgt
  die Implementierung exakt dem bereits etablierten
  `accumulate_severity_maxima()`-Muster (explizites Write-back per ID
  aus main.py via neuer Funktion `accumulate_station_encounter()`).
- Keine neue externe API-Anbindung — nutzt ausschließlich bereits
  vorhandene `fetch_tawes_stations()`-Daten (GeoSphere tawes-v1-10min).
- Dateien: `config.py`, `init_runtime_overrides.py`, `fetch_tawes_gust.py`
  (neue Funktion `nearest_station_wind`), `object_tracking.py`,
  `track_statistics.py` (neue Funktion `accumulate_station_encounter`,
  Erweiterung `write_track_end`), `main.py`,
  `frontend/src/pages/MapView.jsx`.
- Test: `tests/test_p73_last_station_encounter.py`.
- Phasen-Status (Hailo): unverändert — reines Live-Karte-/Böen-
  Plausibilisierungs-Feature, keine Hailo-/ML-Auswirkung
  (`last_station_encounter` bewusst nicht in `ML_CELL_FEATURES`).

### B366 — Veraltete sys.modules-Stubs für fetch_tawes_gust brachen main.py-Import seit P73 ✅ erledigt
- Ursache: `tests/test_b262_risk_watch_retry.py`,
  `tests/test_hydro_disabled_no_requests.py` und
  `tests/test_ir_wms_time_logic.py` isolieren main.py-Importe ueber
  `monkeypatch.setitem(sys.modules, "fetch_tawes_gust", <Stub>)`. Diese
  Stubs stammen aus der Zeit vor P73 und enthielten nur
  `fetch_tawes_stations`/`max_gust_near` — seit P73 importiert main.py
  zusaetzlich `nearest_station_wind`, was in den Stub-Namespaces fehlte.
  Kein Funktionsfehler im Produktivcode, reine Testnachpflege (wie B364).
- Fix: `nearest_station_wind` als No-Op-Lambda in alle drei
  Stub-Dicts ergaenzt.
- Dateien: `tests/test_b262_risk_watch_retry.py`,
  `tests/test_hydro_disabled_no_requests.py`,
  `tests/test_ir_wms_time_logic.py`.
- Test: kein neuer Test noetig, bestehende Tests korrigiert.
- Phasen-Status (Hailo): unveraendert.

### B367 — save_tracking_snapshot() lief vor Enrichment-Schleife (first_seen/total_active_frames/history fehlten im persistierten Snapshot) ✅ erledigt
- Ursache: In `update_tracking_memory()` wurde `save_tracking_snapshot()`
  VOR der Enrichment-Schleife aufgerufen, die `first_seen`,
  `total_active_frames`, `history` und P-S01-Lifecycle-Akkumulatoren erst
  setzt. Anhand echter Debug-Export-Daten (2026-07-14, 13:50) verifiziert:
  im persistierten `tracking_memory_snapshot.json` hatten alle aktiv
  erkannten Zellen (`missing==0`, z. B. `LEPRY15Q`) `first_seen: null`
  und `total_active_frames: null`, obwohl sie laut `cells_log.jsonl`
  durchgehend seit mehreren Frames getrackt wurden. Nach jedem
  Service-Neustart verloren dadurch alle zu diesem Zeitpunkt aktiven
  Zellen ihr echtes Alter und ihre History (Live-Karte zeigte falsche
  "Erstmals"-Zeiten, ML-Trainingssequenzen wurden verkuerzt).
- Fix: `save_tracking_snapshot()` ans Ende von `update_tracking_memory()`
  verschoben (direkt vor `return objects`), nachdem alle Felder gesetzt
  sind.
- Dateien: `object_tracking.py`.
- Test: `tests/test_b367_snapshot_save_order.py`.
- Phasen-Status (Hailo): unveraendert — reiner Tracking-Genauigkeits-Fix.
  Hinweis fuer MAE-Drift-Untersuchung: verlorene History nach
  Service-Neustarts ist ein weiterer potenzieller (bisher nicht
  dokumentierter) Beitrag zur MAE-Drift und sollte in der naechsten
  Drift-Analyse gegen drift_detector.py-Historie beruecksichtigt werden.

### B369 — last_station_encounter-Carry-over wurde nie nach tracking_memory zurückgeschrieben (Testfund nach B367) ✅ erledigt
- Ursache: `update_tracking_memory()` übernahm `last_station_encounter`
  aus der Vorperiode korrekt in `obj_clean`, schrieb den Wert aber im
  B117-Write-back-Block nicht zurück nach `obj`/`tracking_memory[obj_id]`
  (fehlte in der Feldliste neben `first_seen`/`active_frames`/
  `total_active_frames`). Der Wert existierte dadurch nur im an den
  Aufrufer zurückgegebenen `objects`-Ergebnis, nicht in `tracking_memory`
  selbst — ging beim naechsten `save_tracking_snapshot()` verloren,
  sobald in einem Zyklus keine NEUE Begegnung gemeldet wurde (Normalfall).
  Aufgedeckt durch den nach B367 (PR #1001) und der parallelen PR #1000
  hinzugekommenen Test
  `test_update_tracking_memory_snapshots_after_station_encounter_carry_over`.
  Bug existierte bereits vor B367, unabhaengig von der Snapshot-Save-
  Position.
- Fix: `last_station_encounter` in die B117-Write-back-Zeilenliste
  aufgenommen.
- Dateien: `object_tracking.py`.
- Test: bereits vorhanden (`tests/test_object_tracking_regression.py::test_update_tracking_memory_snapshots_after_station_encounter_carry_over`), kein neuer Test noetig.
- Phasen-Status (Hailo): unveraendert — reiner Tracking-Genauigkeits-Fix,
  keine Hailo-Auswirkung.

### B368 — Live-Karte zeigte „Station 11086“ statt echtem Stationsnamen bei last_station_encounter ✅ erledigt
- Ursache: `fetch_tawes_stations()` las den Stationsnamen aus
  `props.get("name", ...)` der `/current/tawes-v1-10min`-Response. Laut
  GeoSphere-API-Spezifikation enthalten die Feature-`properties` dieses
  Endpunkts jedoch KEINEN Stationsnamen (nur `station`-ID und
  `parameters`-Metadaten je Messgroesse) — der Fallback
  `f"Station {station_id}"` griff daher fuer JEDE Station, nicht nur
  fuer Station 11086 aus dem gemeldeten Fall. Echte Namen liefert nur
  der separate `/metadata`-Endpunkt.
- Fix: Neue Funktion `_fetch_station_name_map()` ruft
  `/v1/station/current/tawes-v1-10min/metadata` einmalig ab (gecacht,
  Default 24h via neuer Konstante `TAWES_STATION_METADATA_TTL_SECONDS`,
  Admin-Panel-tunbar) und liefert ein `{station_id: name}`-Mapping.
  `fetch_tawes_stations()` nutzt dieses Mapping vorrangig, faellt bei
  Fehler/fehlendem Eintrag weiterhin sicher auf `f"Station {id}"` zurueck.
- Hinweis: Die exakte Feldstruktur der `/metadata`-Antwort konnte nicht
  per Live-Request aus der Entwicklungsumgebung verifiziert werden
  (Netzwerk-Sandbox ohne Zugriff auf dataset.api.hub.geosphere.at). Die
  Parsing-Logik ist daher defensiv gegen mehrere plausible Strukturen
  (flache `stations`-Liste vs. GeoJSON-`features`) und loggt bei
  unbekannter Struktur statt zu crashen. Nach dem ersten produktiven
  Lauf `debug_log`-Ausgabe `[TAWES-META]` pruefen, ob Namen tatsaechlich
  aufgeloest wurden — ggf. Feldnamen in `_fetch_station_name_map()`
  nachschaerfen.
- Dateien: `config.py`, `fetch_tawes_gust.py`.
- Test: `tests/test_b368_tawes_station_name.py`.
- Phasen-Status (Hailo): unveraendert — reines Live-Karte-Anzeige-Fix
  fuer P73 (last_station_encounter), keine Hailo-/ML-Auswirkung.

### B370 — merge_close_contours() war nicht transitiv (reihenfolgeabhängige Zellgruppierung) ✅ erledigt

**Root-Cause:** Die innere Schleife verglich ausschließlich gegen die Startkontur `cnt1`. Neu zur
Gruppe hinzugefügte Konturen wurden nie selbst als Nachbarschaftsquelle genutzt. Bei A–B, B–C,
aber nicht A–C entstand je nach OpenCV-Konturreihenfolge `{A,B}+{C}` oder `{A,B,C}`.

**Wirkung:** Derselbe Gewitterkomplex wurde in aufeinanderfolgenden Frames unterschiedlich
gruppiert → fluktuierende Außenkonturen → ID-Switches, Schwerpunktsprünge, Forecast-Fehler.

**Fix:** Nachbarschaft als Graph (Knoten = Kontur, Kante = Berührung), Zusammenhangskomponenten
per Union-Find mit Pfadkompression und Union-by-Rank. Ergebnis per Konstruktion
reihenfolgeinvariant. Bounding-Box-Pruning (`_bboxes_can_touch`) vor dem Maskenvergleich hält die
Laufzeit auf dem Pi 5 stabil. Die Buffer-Union-Unbuffer-Semantik aus B276 bleibt unverändert.

**Tests:** `tests/test_b370_merge_close_contours_transitiv.py` — transitive Kette, Invarianz über
alle 6 Permutationen, disjunkte Konturen, Leereingabe, BBox-Gate vs. echte Berührung.

**Phasen-Status:** Phase A (Stabilität) — Segmentierungs-Determinismus hergestellt. Erster Schritt
der Tracking-Sanierung (Analyse 14.07.2026, Finding 5.1). Folgeprompts: B371 (Event-Dedup),
B372 (Diagnose-Export), B373–B375 (globales Matching), B376 (adaptive Subcell-Segmentierung).

### B371 — Merge/Split-Ereignisse wurden in jedem Folgeframe erneut geschrieben ✅ erledigt

**Root-Cause:** Ein Merge ist ein Übergangsereignis, wurde aber als Dauerzustand protokolliert.
`update_split_merge_lineage()` ruft für jedes Objekt mit `lineage=="merged"` erneut
`record_cell_merge()` auf; dieses schrieb jedes Mal ein neues Event. Die vorhandene Dedup war
wirkungslos: `append_lineage_event()` schreibt ungeprüft, und `_append_unique()` vergleicht nur
exakte dict-Gleichheit — durch das eingebettete `timestamp`-Feld war jedes Event pro Frame
verschieden.

**Belegt (Debug-Export 14.07.2026, 258 Snapshots, 724 Beobachtungen):** 160× `lineage="merged"`,
davon 160/160 mit eigener Track-ID in `parents`; 23 Merge-Serien, Mittel 6.6 Frames, längste 11
Frames (≈ 55 min); 0× `lineage="split"`. Fallstudie `1C04EV5M`: 10 Frames in Folge `merged`
(15:20–16:05) bei wechselnder Parentmenge (2–8).

**Fix:** Zeitstempelfreie Ereignis-Signatur `sha1(event_type|sorted(parents)|sorted(children))`.
Ein bestätigtes Ereignis wird genau einmal geschrieben; Folgeframes aktualisieren nur noch
`emitted_event_last_seen`. Die Zustandspflege (`last_seen_timestamp`, Alias-IDs, `radar_to_cell`)
läuft unverändert in jedem Frame. Signatur-Gedächtnis über
`CELL_LINEAGE_EVENT_SIGNATURE_MEMORY` (Default 2000) begrenzt.

**Tests:** `tests/test_b371_cell_lineage_event_dedup.py` — 10 Wiederholungen → 1 Event,
Konstellationswechsel → neues Event, Reihenfolge-/Timestamp-Invarianz der Signatur,
Split-Dedup, State-Fortschreibung, Gedächtnisbegrenzung.

**Phasen-Status:** Phase A — Ereignissemantik auf Lineage-Ebene korrigiert (Analyse 14.07.2026,
Finding 5.12). Die **Ursache** in `object_tracking.py` (`lineage` als Dauerzustand) wird in B373
behoben; B371 ist die dauerhaft notwendige Absicherung auf der Fachschicht.

### B372 — Lineage-Eventledger fehlte im Debug-Export, Schreibfehler wurden still verschluckt ✅ erledigt

**Root-Cause:** Fehlende Beobachtbarkeit der Lineage-Persistenz. Der Debug-Export vom 14.07.2026
enthielt unter `train_data/cell_lineage/` ausschließlich `ir_lead_time_labels.jsonl` — weder
`cell_lineage_events.jsonl` noch `cell_lineage_state.json`. Das ist kein Konfigurationsfehler:
`CELL_LINEAGE_SPLIT_MERGE_ENABLED=True`, das Verzeichnis wird exportiert (`debug_export.py`
Zeile 324), und `record_cell_merge()` läuft nachweislich (160/724 Objekte tragen
`lineage_status="merged"` + `merged_from_cell_ids`, beides wird nur dort gesetzt).

Ursache war die stille Fehlerbehandlung in `append_lineage_event()`: jeder Schreibfehler landete
in einer `debug_log`-Zeile. Da das Journal im Export zeitlich abgeschnitten wird (08:00–13:06;
die Konvektionsphase 15:00–16:05 fehlt), war ein Totalausfall der Event-Persistenz nicht
nachweisbar. `_state_dir()` liefert zudem einen **relativen** Pfad — das Ziel hängt vom CWD des
systemd-Dienstes ab.

**Fix:**
- `append_lineage_event()` löst den Pfad über `resolve()` **absolut** auf.
- Neue Statusdatei `cell_lineage_write_status.json` (letzter Versuch, aufgelöster Pfad, CWD,
  ok-/error-Zähler, letzter Fehler) — Erfolg *und* Fehler sind exportiert nachweisbar.
- `cell_lineage_events.jsonl`, `cell_lineage_state.json` und die Statusdatei stehen jetzt in
  `_ALWAYS_INCLUDE_NAMES` und werden unabhängig vom 24-h-mtime-Fenster exportiert.
- Persistenzfehler stoppen den Radarzyklus weiterhin nicht.

**Tests:** `tests/test_b372_lineage_export_und_schreibfehler.py` — Ledger + Status bei Erfolg,
absolute Pfadauflösung, Fehler wird protokolliert statt verschluckt, kein Exception-Durchschlag,
Always-Include-Abdeckung, Zählerakkumulation.

**Phasen-Status:** Phase A — Beobachtbarkeit der Lineage hergestellt. Voraussetzung für die
Abnahmekriterien der Tracking-Sanierung (0 wiederholte Eventsignaturen, Analyse 14.07.2026,
Abschnitt 10/12). **Nach dem Deployment ist der nächste Debug-Export dahingehend zu prüfen, ob
`cell_lineage_write_status.json` `last_result="ok"` meldet** — falls `error`, liefert
`resolved_events_path` + `cwd` die konkrete Ursache.

### B373 — Assoziationsbibliothek: Kostenmatrix, physikalische Gates, globale 1:1-Zuordnung ✅ erledigt

**Root-Cause:** `update_tracking_memory()` vergibt Track-IDs greedy und konturweise
(`for contour in contours` + `used_ids`). Die OpenCV-Konturreihenfolge entscheidet damit über die
Zellidentität. Gegenfall: X passt gut zu A und etwas schlechter zu B, Y passt nur zu A — greedy
liefert X→A und Y→`new`, global optimal wäre X→B, Y→A. Verstärkend: Stage-1-Score
`max(IoU, recall×0.7)` ab 0.10 ohne Form/Richtung/Kernlage; Stage-2-Cap
`(150/4)×3×1.5 = 168.75 px` in Pixeln statt Kilometern und ohne tatsächlichen Zeitabstand
(belegte Live-Matches: 88.0, 111.7, 143.2, 151.5 px).

**Fix (additiv):** Neues Paket `tracking/` mit `association.py`:
- Gates in **echten Kilometern** und **tatsächlichem dt** (Radarlücken 10/15 min korrekt behandelt).
- **Suchellipse** statt Suchkreis — quer zur Bewegung um Faktor `ASSOC_ELLIPSE_CROSS_FACTOR`
  (Default 0.45) enger; Hauptquelle für Fehlzuordnungen an Nachbarzellen entfällt.
- Zeitabhängiges Flächengate (`ASSOC_MAX_AREA_GROWTH_PER_MIN`) statt fixem 10×-Faktor.
- Richtungsgate erst ab `ASSOC_MIN_AGE_FRAMES_FOR_DIR_GATE` (junge Tracks haben keinen Vektor).
- Gewichtete Kostenmatrix (Position, IoU, Fläche, Richtung, Kern, Track-Alter), global gelöst mit
  `scipy.optimize.linear_sum_assignment`; Matches über `ASSOC_MAX_COST` werden verworfen.
- Vollständige Diagnose-Payload (Kostenmatrix, Kandidatenpaare inkl. Einzelkomponenten,
  Ablehnungsgründe) — Grundlage für das Abnahmekriterium „Exportierte Kandidaten-/Kosten-Diagnosen“.

B365 (`STAGE2_WEAK_CELL_MAX_SPEED_KMH`) bleibt gültig und wird durch die physikalischen Gates
verallgemeinert, nicht ersetzt.

**Tests:** `tests/test_b373_tracking_association.py` — Hungarian-Gegenbeispiel, Reihenfolge-
invarianz, echte Zeit statt fixem Frame, Ellipse quer vs. längs, Flächengate, junger Track ohne
Richtungsgate, Gating in der Matrix, leere Eingaben, Diagnosevollständigkeit.

**Abhängigkeit:** `scipy>=1.11.0` bereits in `requirements.txt` — keine neue Abhängigkeit.

**Phasen-Status:** Phase A — Assoziationsbibliothek steht und ist isoliert getestet.
`object_tracking.py` ist **noch unverändert**; die Umstellung des Live-Pfads erfolgt in **B374**,
der Merge/Split-Resolver in **B375**.

### B374 — Greedy-Zuordnung im Live-Pfad durch globale 1:1-Optimierung ersetzt ✅ erledigt

**Root-Cause:** `update_tracking_memory()` vergab Track-IDs greedy und konturweise
(`for contour in contours` + `used_ids`). Die OpenCV-Konturreihenfolge entschied über die
Zellidentität; Stage-2 gatete in skalierten Pixeln bei implizit angenommenem 5-Minuten-Takt.

**Fix:**
- Vorschleife baut alle Detektionen auf (Filter identisch zur Hauptschleife: `min_object_area`,
  Ausschlusszonen, BBOX) → genau **ein** `solve_global_assignment()`-Aufruf pro Frame.
- Stage 1/2/3 ersatzlos entfallen; beide Sonderfälle deckt die Kostenmatrix ab (Stage-2-Fall über
  `c_pos`+`c_area`, Stage-3-Fall über den isotropen Suchkreis bei `speed<1 km/h`).
- **Merge-Fallback greift nur noch auf unmatched Tracks** — ein global 1:1 zugeordneter Track kann
  nicht mehr zusätzlich Merge-Parent einer anderen Kontur werden. Das war die Hauptquelle der
  Scheinmerges (160/724 Beobachtungen, alle mit eigener Track-ID in `parents`).
- `_tracking_dt_minutes()` liefert den **tatsächlichen** Zeitabstand (Fallback 5.0 nur beim ersten
  Lauf oder bei implausiblem Delta) — Radarlücken von 10/15 min werden korrekt behandelt.
- Kein stiller Greedy-Fallback bei Fehlern: ein Fehlschlag ist im Debugexport sichtbar
  (`method="failed"`), statt unbemerkt falsch zu laufen.
- Neue Diagnose `train_data/association/<timestamp>.json` (Kostenmatrix, Kandidatenpaare inkl.
  Einzelkomponenten, Ablehnungsgründe, dt) — erfüllt das Abnahmekriterium „Exportierte
  Kandidaten-/Kosten-Diagnosen: 100 % der aktiven Frames“. Im Debug-Export unter `diagnostics/`.

**Tests:** `tests/test_b374_globales_matching_integration.py` — dt-Ermittlung inkl.
Implausibilitäts- und Rückwärtsschutz, km-Projektion, Nachweis der Stage-Entfernung,
Diagnose-Persistenz und Fehlertoleranz, Export-Abdeckung.

**Phasen-Status:** Phase A — Zuordnung ist global optimal und reihenfolgeinvariant.
**Offen:** `lineage` ist weiterhin ein Dauerzustand und der Split-Pfad bleibt durch `used_ids`
blockiert → **B375** (Transition-Resolver, Event/State-Trennung). Die Kostengewichte
(`ASSOC_W_*`) sind noch mit den B373-Defaults belegt und **gegen den nächsten realen Debug-Export
zu kalibrieren** (Replay `1C04EV5M`, 15:00–16:05).

### B375 — `lineage` war ein Dauerzustand, der Split-Pfad war strukturell blockiert ✅ erledigt

**Root-Cause:** `lineage` vermischte Zustand und Ereignis. `object_tracking.py:1276` setzte
`lineage="merged"`, solange die Geometrie einen Verbund zeigte — in jedem Frame neu. Aus demselben
Defekt folgte die Split-Blockade: der Split-Zweig (Zeile 1421–1426) verlangt, dass dieselbe alte
ID mehreren neuen Objekten zugeordnet wird — genau das verhindert `used_ids`.

**Belegt:** 0× `lineage="split"` in 724 Beobachtungen, obwohl P66 im Service-Log nachweislich
Sub-Zellen meldet (`2→2`, `4→4`, `3→3`). Demgegenüber 160× `merged` in 23 Serien (Mittel 6.6,
längste 11 Frames ≈ 55 min).

**Fix:** Neues Modul `tracking/transition_resolver.py`. Merge/Split werden **nach** dem globalen
1:1-Matching aus dem verbleibenden bipartiten Überlappungsgraphen abgeleitet:
- **n:1-Merge:** nur unmatched Parents, jeder mit `TRANSITION_MERGE_MIN_PARENT_COVERAGE` (0.40)
  Beitrag der eigenen alten Fläche; alle zusammen müssen `TRANSITION_MERGE_MIN_EXPLAINED` (0.50)
  der neuen Fläche erklären. Der alte 0.30-Fallback ließ kleine Randtracks zu Parents werden.
- **1:n-Split:** eine unmatched alte Zelle überdeckt ≥2 neue Zellen mit je
  `TRANSITION_SPLIT_MIN_CHILD_SHARE` (0.15) Anteil.
- **Zustandsautomat** `candidate → confirmed → closed` / `reverted`: Bestätigung erst nach
  `TRANSITION_CONFIRM_FRAMES` (2) konsistenten Frames. Die Karte darf sofort `candidate` zeigen,
  die Identität ändert sich erst bei `confirmed`.
- Neue Objektfelder: `track_state`, `origin_type`, `transition_event` (**nur** im Ereignisframe),
  `transition_phase`, `transition_signature`, `association_method`. In Folgeframes ist das Objekt
  `continued`, auch wenn seine Herkunft ein Merge war.

`lineage` bleibt aus Kompatibilitätsgründen befüllt (Frontend/ML), trägt aber jetzt die korrekte
Ereignissemantik.

**Tests:** `tests/test_b375_transition_resolver.py` — Split wird erkannt (Kernbefund),
Mindestbeiträge, Scheinmerge einer Systemhülle abgelehnt, Bestätigung erst ab Frame 2,
`reverted` bei Verschwinden, 10 Folgeframes → genau 1 Ereignissignatur, Signatur-Invarianz.

**Phasen-Status:** Phase A — Ereignissemantik und Split-Pfad hergestellt. Zusammen mit B371
(Event-Dedup) ist das Abnahmekriterium „0 wiederholte Eventsignaturen in Folgeframes“ erfüllt.
**Offen:** Segmentierung (Voronoi → adaptive Hysterese) → **B376**; Primary-Policy-Konsistenz →
**B377**. Der Replay-Regressionstest für `1C04EV5M` (15:00–16:05) ist nach B376 zu erstellen.

### B378 — Zellherkunft nach B375 nicht mehr abfragbar (Karte verlor Verbund-Kennzeichnung) ✅ erledigt

**Root-Cause:** B375 stellt `lineage` korrekt von einem Dauerzustand auf ein **Ereignis** um
(`merged` nur im Bestätigungsframe). Zwei Folgen fing B375 nicht auf:

1. `origin_type` wurde pro Frame aus `lineage` neu abgeleitet. Da `lineage` ab Frame 2
   `continued` lautet, fiel `origin_type` auf `"new"` zurück — eine aus einem Merge
   hervorgegangene Zelle behauptete ab dem zweiten Frame, sie sei neu entstanden.
2. Drei Frontend-Konsumenten lasen `lineage` als Dauerzustand:
   `MapFullscreen.jsx:134–135`, `MapView.jsx:138–139` (identisches `cellStroke`-Duplikat) und
   `LiveDaten.jsx:146–147` (⊕/⊗-Badges). Die Verbund-Kennzeichnung wäre nach einem einzigen Frame
   verschwunden — eine 55-Minuten-Gewitterlinie hätte ab Minute 5 wie eine Einzelzelle ausgesehen.

**Fix:**
- `_resolve_origin_type()`: Herkunft wird im Ereignisframe gesetzt und in Folgeframes aus dem
  `previous_snapshot` **fortgeschrieben**. Ein neues Ereignis überschreibt die alte Herkunft.
- Karte und Live-Liste stellen auf `origin_type` (Dauerzustand) um. **Die Optik bleibt exakt
  identisch** — nur die Datenquelle ist korrekt. Fallback auf `lineage` hält die Anzeige während
  eines Rolling-Deployments lesbar, solange Objekte ohne `origin_type` im Payload stehen.

**Tests:** `tests/test_b378_origin_type_carryover.py` — Ereignisframes setzen die Herkunft,
`continued` erbt sie, Herkunft überlebt eine 11-Frame-Serie (55 min), Neuereignis überschreibt,
defensive Fälle (kein Vorgänger, ungültiger Wert, kein dict).

**Phasen-Status:** Phase A — **Blocker für die Serie B370–B377 beseitigt.** Ohne B378 hätte das
Deployment eine sichtbare Regression im Probebetrieb erzeugt.

**Bekannt, bewusst offen:** `cellStroke()` existiert dupliziert in `MapFullscreen.jsx` und
`MapView.jsx`. Beide Stellen werden identisch gepflegt; die Deduplizierung ist ein eigener
Root-Cause und wird separat geführt. Die Darstellung von `transition_phase="candidate"`
(gestrichelte Übergangskandidaten) ist ein Fach-Feature → **P75**.

### B376 — Euklidische Voronoi-Teilung erzeugte künstliche Zellgrenzen quer durch Kernflächen ✅ erledigt

**Root-Cause:** Der P66-Multi-Core-Split trennte geometrisch statt physikalisch — das
Intensitätsfeld ging nirgends ein.
- `_core_path_gap_px()` prüfte nur die **gerade** Verbindungslinie (kein topologisch robuster
  Trennpfad); `MULTI_CORE_MIN_GAP_PX=2.0` ließ zwei Pixel Quantisierungs-/JPEG-Rauschen genügen;
  ein **einziges** geeignetes Kernpaar gab den gesamten Mehrkernkomplex frei (`break`/`break`).
- `_voronoi_split()` ordnete jeden Pixel der Außenkontur dem euklidisch nächsten Kernzentrum zu →
  gerade/keilförmige Grenzen quer durch starke rote/violette Flächen, Schwerpunktsprünge bei
  minimalen Markerbewegungen.

**Fix (AINT-Prinzip, arXiv:2509.02929):**
- `_intensity_field()`: Reflektivitäts-Proxy aus HSV (V×S).
- `_core_saddle_ratio()`: Split nur bei echtem **Intensitätseinschnitt** zwischen zwei Kernen
  (`MULTI_CORE_MIN_SADDLE_RATIO`, Default 0.35) — eine elongierte Böenlinie mit mehreren Maxima
  ohne Sattel bleibt **eine** Zelle.
- **Alle** geprüften Kernpaare müssen trennbar sein, nicht nur eines.
- `_watershed_split()`: marker-gesteuerte Watershed-Expansion auf dem invertierten
  Intensitätsfeld — die Grenzen folgen den Reflektivitätsminima statt der euklidischen Mitte.
- `_voronoi_split()` bleibt als Notfall-Fallback (als DEPRECATED markiert), falls Watershed wirft.

**Tests:** `tests/test_b376_adaptive_subcell_segmentierung.py` — kein Sattel bei durchgehender
Struktur, Sattel bei schwacher Brücke, 2 Sub-Zellen, Grenze folgt dem Tal, Einzelkern-Passthrough,
`min_child_area`-Respektierung, Config-Default, Fallback-Verfügbarkeit.

**Phasen-Status:** Phase A — Segmentierung folgt dem Intensitätsfeld. **Offen:**
Primary-Policy-Konsistenz → **B377**. Die Trennung von `support_mask` (Systemhülle, großzügiges
Closing) und `core_tracking_mask` (Zellkerne, feines Closing) ist ein **Architektur-Feature**
(System-/Zellhierarchie `system_id`/`cell_id`) und wird als eigener P-Prompt geführt — erst
danach ist der Replay-Regressionstest `1C04EV5M` (15:00–16:05) sinnvoll aufsetzbar.

### B377 — Radar-Track-Policy und fachliche Cell-Policy widersprachen sich ✅ erledigt

**Root-Cause:** Bei einem Merge entschieden zwei verschiedene Regeln, welche Identität überlebt —
und die im Admin-Panel konfigurierte Policy steuerte die primäre Identität **nicht**:
- **Radar-Ebene** (`object_tracking.py:1259–1263`): `_primary_s = _old_area_s` — der
  flächengrößte Parent behielt die Radar-ID. `core_ratio` spielte keine Rolle.
- **Fach-Ebene** (`cell_lineage.py:1168–1174`): der B268-Survivor-Vorrang überstimmte
  `CELL_LINEAGE_PRIMARY_MERGE_POLICY = highest_core_ratio` im Normalfall vollständig; die Policy
  griff nur im `else`-Zweig (Survivor ohne etablierte `cell_id`).

Fachliche Folge: Bei einer zerfallenden Systemhülle gewann die **Fläche** statt des konvektiv
aktiven Kerns. Die de-facto-Regel war nirgends dokumentiert.

**Fix:** Neues Modul `tracking/primary_policy.py` als **einzige Quelle der Wahrheit**; beide
Ebenen rufen dieselbe Auswahl auf.
- Neue Default-Policy **`continuity_score`**: gewichteter Score aus Trackalter (0.30),
  Kernstärke (0.30), relativem Flächenbeitrag (0.25) und absoluter Kernfläche (0.15), mit
  Alterssättigung bei `PRIMARY_AGE_SATURATION_FRAMES` (12).
- Die bisherigen Verhalten bleiben als Policy-Optionen wählbar: `highest_core_ratio` (altes
  Fach-Verhalten), `largest_area` (altes Radar-Verhalten), `survivor_first` (B268-Verhalten).
- B268 ist damit eine bewusste Wahl statt einer unausweichlichen Regel; das Admin-Panel steuert
  jetzt tatsächlich die primäre Identität — auf beiden Ebenen konsistent.
- Auswahl ist deterministisch (Index als letzter Tiebreak).

**Tests:** `tests/test_b377_primary_policy_konsistenz.py` — Flächen-Dominanz aufgehoben, alle vier
Policies wählbar und wirksam, Trackalter zählt, Score beschränkt, Determinismus bei Gleichstand,
Fallback bei ungültiger Policy, Delegation der Fachebene an die gemeinsame Policy.

**Phasen-Status:** Phase A — **Tracking-Sanierungsserie B370–B377 abgeschlossen.**
Segmentierungs-Determinismus (B370), Ereignissemantik (B371/B375), Beobachtbarkeit (B372),
globale Zuordnung (B373/B374), intensitätsbasierte Segmentierung (B376) und Policy-Konsistenz
(B377) stehen.

**Offen (bewusst nicht in dieser Serie):**
- **P-Prompt System-/Zellhierarchie** (`system_id`/`cell_id`, `support_mask` vs.
  `core_tracking_mask`) — Architektur-Feature, user-facing → mit Benutzerhandbuch-Eintrag.
- **P-Prompt Übergangskandidaten auf der Karte** (gestrichelte Darstellung) — user-facing.
- **P-Prompt feldbasierter probabilistischer Hazard-Nowcast** — entkoppelt Warnungen von der
  Zell-ID (Phase B, Hailo-8/U-Net).
- **Replay-Regressionstest `1C04EV5M`** (15:00–16:05) — erst nach der System-/Zellhierarchie
  sinnvoll aufsetzbar.
- **ML-Schutz:** Frames mit `transition_event != null` dürfen nicht als normale
  Translationslabels ins Training (`transition_mask`) — eigener Prompt nach der ML-Reaktivierung.
- **Kalibrierung:** Die Gewichte aus B373/B375/B376/B377 sind gegen den ersten Debug-Export mit
  aktiver Serie nachzujustieren.

### B379 — Flächengate verwarf jede Merge-Kontur; B365-Kernschwäche fehlte in den Gates ✅ erledigt

**Root-Cause:** Die Gates aus B373 waren gegen die falsche Physik kalibriert.

1. **Flächengate:** `1.25^dt` erlaubte bei dt=5 min nur **3.05×**. Eine Merge-Kontur wächst aber
   genau um ein Vielfaches (B117-Testfall: 6.400 px² → 40.000 px² = **6.25×**) → das Paar wurde
   gegatet, die Kontur wurde `lineage="new"` mit **neuer ID**. Die B117-Kontinuität brach bei
   jedem Merge. Der Legacy-Stage-2-Code war mit `_aratio2 >= 0.10` (~10×) großzügiger — B373 war
   strenger als der Code, den es ersetzte.
2. **B365:** Die B374-Changelog behauptete, B365 sei „in den physikalischen Gates aufgegangen".
   Das war falsch — `object_tracking.py` übergab `MAX_CELL_SPEED_KMH` (150) für **alle** Tracks.
   Die Kostenkomponenten `c_core`/`c_age` greifen zu spät, weil das Gate vorher entscheidet.

**Behobene Regressionen** (gegen Baseline `a7912311` abgegrenzt):
`test_b117_track_continuity`, `test_object_tracking_regression`, `test_b365_stage2_weak_cell_match_cap`.

**Fix:**
- `_max_area_ratio()`: Basisfaktor `ASSOC_MAX_AREA_RATIO_BASE` (10.0) im Normaltakt; der
  zeitabhängige Anteil greift **nur** für Lücken oberhalb `ASSOC_NORMAL_FRAME_MINUTES` (5.0).
  Merge (Wachstum) und Split (Schrumpfung) sind zulässig; absurde Verhältnisse werden weiter
  abgefangen. Die Feinbewertung leistet `c_area`.
- `_effective_max_speed()`: B365-Semantik in den Gates — `core_ratio < ASSOC_WEAK_CORE_THRESHOLD`
  (0.05) → `ASSOC_WEAK_MAX_SPEED_KMH` (60). Ein global engerer Cap wird nie aufgeweitet.
- `build_candidate_features()` nutzt dieselbe Basis wie das Gate, sonst normiert `c_pos` gegen
  einen anderen Radius als der zugelassene.

**Tests:** `tests/test_b379_assoc_gates_merge_und_kernschwaeche.py` — Merge-Wachstum und
Split-Schrumpfung zulässig, absurde Ratio weiter gegatet, Basisfaktor bei 5 min, Zeitzuschlag erst
darüber, Schwach-/Stark-Cap inkl. Gegenprobe, End-to-End-Match der Merge-Kontur auf den dominanten
Parent.

**Phasen-Status:** Phase A — Korrekturserie B379–B386 gestartet. **Offen:** Split-Integration
(B381), Pre-Frame-Parent-Snapshot (B382), IR-Entkopplung (B383), Resolver-Geometrie (B384),
stabile Signaturen/`closed` (B385), Hungarian-Unmatched + Zeitbasis (B386), Segmentierung (B380).

### B380 — Intensitätsfeld der Segmentierung war nicht ordnungserhaltend (Hue ignoriert) ✅ erledigt

**Root-Cause:** `_intensity_field()` (B376) nutzte `V×S` und ignorierte den **Hue-Kanal** — genau
den Kanal, der in der ARSO-INCA-Skala die Reflektivität trägt. Da alle Radarfarben vollgesättigt
sind (S≈255, V≈255), lieferte `V×S` für Orange (49 dBZ), Rot (54 dBZ) und Violett (57 dBZ)
**denselben Wert**. Das Feld war innerhalb einer Zelle uniform; Watershed hatte keine Information
und folgte bestenfalls JPEG-Artefakten. Der Legacy-Voronoi-Code konnte den Fall lösen, weil er rein
geometrisch arbeitete — B376 ersetzte die Geometrie durch ein Intensitätsmaß, das keine Intensität
maß.

**Belegte Regression:** `test_b275_multi_core_gap_check::test_u_shape_with_two_cores_and_real_gap_is_split`
(Baseline `a7912311` grün → rot). Zwei rote Kerne (Hue≈0, 54 dBZ), verbunden über eine orange
U-Brücke (Hue≈15, 49 dBZ) — meteorologisch ein klarer Sattel, für `V×S` identisch.

**Fix:**
- `RADAR_DBZ_BANDS` in `config.py`: explizites, ordnungserhaltendes Band-Mapping
  (grün 0.20 < gelb 0.35 < orange 0.55 < rot 0.80 < violett 1.00). Ein Hue-**Vergleich** wäre
  ebenso falsch wie `V×S`, weil die Skala nicht monoton in Hue ist: Rot wrapt über 0/179, Violett
  liegt bei 125–160. Beide Rot-Bänder (0–10, 165–179) mappen identisch.
- `RADAR_DBZ_MIN_SAT`/`RADAR_DBZ_MIN_VAL`: Graustufen/Kartenrand liefern Intensität 0.
- `_intensity_field()` vektorisiert über numpy-Masken; `np.maximum` sorgt dafür, dass sich bei
  überlappenden Bändern das stärkere durchsetzt statt des zuletzt geprüften.
- `_core_peak_intensity()`: Kernmaximum robust aus der Kernumgebung (Radius 3) statt aus einem
  rauschanfälligen Einzelpixel.
- `_core_saddle_ratio()`: Referenz ist jetzt das **schwächere** Kernmaximum
  (`min(peak_1, peak_2)`) — so beschreibt es auch `MULTI_CORE_MIN_SADDLE_RATIO`. Mit dem stärkeren
  Endwert wurde ein Nebenmaximum leichter als getrennt eingestuft.

**Tests:** `tests/test_b380_dbz_intensitaetsfeld.py` — Reihenfolge grün<orange<rot<violett,
Rot/Orange unterscheidbar, Rot-Wrap konsistent, ungesättigte Pixel = 0, Maskenrespektierung,
rauschrobustes Kernmaximum, Sattelreferenz am schwächeren Kern, B275-U-Form.

**Phasen-Status:** Phase A — Segmentierung misst wieder Intensität. Voraussetzung für **B381**
(Split-Integration): ohne funktionierende Sub-Zellen gibt es keine Split-Kandidaten.
**Offen:** Mehrkern-Komponentengraph („alles oder nichts", P2-4) → **B387**.

### B381 — Split-Pfad war auch nach B375 praktisch unerreichbar ✅ erledigt

**Root-Cause:** B375 hat das ursprüngliche Kernproblem (0 Splits in 724 Beobachtungen trotz
sichtbarer Sub-Zellen) **nicht** behoben. Drei Integrationsfehler:

1. **Resolver sah nur unmatched Tracks.** Bei einem normalen Split `A → X + Y` ordnet Hungarian A
   korrekterweise 1:1 einem Kind zu. A ist damit *matched* und fehlte in `_unmatched_polys` — der
   Resolver sah genau den Fall nicht, für den er gebaut wurde.
2. **Objektschleife hatte keinen Split-Zweig.** Zeile 1710 prüfte nur
   `phase == "confirmed" and len(overlaps) >= 2` — für ein Split-Kind nie erfüllt, da jedes Kind
   höchstens einen Parent hat. Bestätigte Split-Kandidaten blieben wirkungslos.
3. **Alt-Nachlauf tot.** `assigned_old_to_new` verlangte dieselbe alte ID in `parents` mehrerer
   neuer Objekte — nach der globalen 1:1-Zuordnung per Konstruktion unmöglich. Die einzige Stelle,
   die `lineage="split"` setzte (Zeile 1900), war damit unerreichbar.

**Fix (AINT-Regel, arXiv:2509.02929):**
- `find_split_candidates(all_tracks, …)` erhält **alle** alten Tracks. Das globale 1:1-Match ist
  kein Ausschlusskriterium, sondern die Information, **welches** Kind das primäre ist.
- `TransitionCandidate.primary_child`: das gematchte Kind; ohne Match das flächengrößte.
- Neuer Split-Zweig in der Objektschleife: primäres Kind führt die Parent-ID fort, weitere Kinder
  erhalten neue IDs, alle tragen `parents=[parent_id]` und `lineage="split"` **nur** im
  bestätigten Ereignisframe. `best_id` zeigt bei allen Kindern auf den Parent, damit Trend- und
  Kern-Carry-over die Herkunft nutzen können.
- `children`/`lineage_end` stammen aus den bestätigten Ereignissen; der tote
  `assigned_old_to_new`-Nachlauf ist ersatzlos entfallen.

**Tests:** `tests/test_b381_split_integration.py` — Split mit **gematchtem** Parent (Kernfall),
primäres Kind = gematchtes Kind, Flächen-Fallback, Einzelkind kein Split, Erklärungsschwelle,
Bestätigung ab Frame 2, `primary_child` überlebt die Bestätigung, toter Pfad entfernt,
Split-Zweig vorhanden.

**Phasen-Status:** Phase A — der Split ist erstmals im integrierten Live-Ablauf erreichbar.
**Verifikationspflicht:** Im nächsten Debug-Export muss `lineage="split"` bei Multi-Core-Lagen
**auftreten** (bisher 0/724). Bleibt der Wert 0, ist die Ursache in der Segmentierung (B380) oder
den Schwellen (`TRANSITION_SPLIT_MIN_EXPLAINED`/`MIN_CHILD_SHARE`) zu suchen.
**Offen:** Merge-Erklärung/Survivor-Fläche (B384), stabile Signaturen + `closed` (B385).

### B382 — Merge-Kandidatenphase brach die ID-Kontinuität (jeder Merge erzeugte eine neue ID) ✅ erledigt

**Root-Cause (P0):** Im ersten Frame eines Merges griff **kein einziger Zweig** der Objektschleife.
`_overlap_by_id` enthält dann bereits 2 Parents (`len(overlaps) == 2`), während
`_transition.phase` noch `"candidate"` ist (B375: `TRANSITION_CONFIRM_FRAMES=2`). Damit war weder
der Split-Zweig, noch der Merge-Zweig (nicht `confirmed`), noch der `continued`-Zweig
(`len(overlaps) == 1`) erfüllt. `obj_id` blieb `None` → `generate_id()` → `lineage="new"`.

**Beweis (Laufzeit-Spy, Testfall B117):** Das globale Matching arbeitet einwandfrei —
`matches={0:'VDEPFC5X'}`, `cost=0.3773`, der kleine Parent wird zu Recht gegatet
(`area_ratio=44.4>10`). Die Objektschleife verwarf dieses Ergebnis und vergab `N04TDN6A`.
Es war **kein** Gate-Problem: B379 hatte das Flächengate korrekt geweitet (6.25× < 10×).

**Wirkung:** Bei **jedem** Merge brach die ID-Kontinuität — Kalman-Zustand, Trend-Historie,
Lebensdauer, Warnhistorie und ML-Sequenz gingen verloren, die Zelle erschien als Neuzelle. Das ist
gravierender als der ursprüngliche Befund (wiederholte Merge-Events), den B375 beheben sollte.

**Fix — Identität sofort, Ereignis verzögert** (Analyse Abschnitt 9.5): Die Bedingung lautet jetzt
`elif overlaps:`. Der dominante Parent (erster freier Eintrag der nach B377-Policy sortierten
`overlaps`) behält seine ID **auch während der Kandidatenphase**; `lineage` bleibt `continued` und
`parents` enthält nur den fortgeführten Parent. Die vollständige Parentmenge und `lineage="merged"`
entstehen weiterhin ausschließlich im **bestätigten** Ereignisframe. B375 hatte Identität und
Ereignisbestätigung gekoppelt — das war der Fehler.

**Behobene Regressionen:** `test_b117_track_continuity::test_merge_inherits_dominant_parent_id`,
`test_object_tracking_regression::test_merge_with_dominant_parent_without_kf_does_not_crash`.

**Tests:** `tests/test_b382_kandidatenphase_id_kontinuitaet.py` — dominanter Parent behält ID im
Kandidatenframe, Kandidat ist `continued` (nicht `merged`), höchstens ein Parent, 1:1-Fall
unverändert, Kalman-Zustand überlebt, alte Bedingung kehrt nicht zurück.

**Phasen-Status:** Phase A — ID-Kontinuität bei Merge wiederhergestellt.
**Offen:** Segmentierung/`test_b275` (B383), `test_b365`-Testmaßstab (B384), Pre-Frame-Parent-
Snapshot P0-2 (B385), IR-Entkopplung P1-1 (B386), Resolver-Geometrie P1-2 (B387), stabile
Signaturen/`closed` P1-3/4/5 (B388), Hungarian-Unmatched P1-7 + Zeitbasis P2-2 (B389),
Mehrkern-Komponentengraph P2-4 (B390).

### B383 — cv2.watershed konnte Sub-Zellen ohne Intensitätsgradienten nicht trennen ✅ erledigt

**Root-Cause:** `_watershed_split()` (B376) nutzte `cv2.watershed()`. Dessen Meyer-Algorithmus
arbeitet auf **Gradienten** und versagt, wenn der Verbindungsweg in sich uniform ist — der
Normalfall bei einer durchgehend gleich starken Regenbrücke.

**B380 hat das nicht behoben.** Das Intensitätsfeld ist seit B380 nachweislich korrekt
(RED→204, ORANGE→140); der Fehler lag eine Stufe später, im Flutungsalgorithmus.

**Laufzeitbeleg (U-Form aus B275):** Kerne (2), `saddle=1.0`, `gap_px=79.0` — alle Vorstufen
korrekt. `cv2.watershed` lieferte dann `[3910, 342]` px bei 4801 px Gesamtfläche. Mit dem
produktiven `MULTI_CORE_MIN_CHILD_AREA_PX=800` fiel das zweite Kind heraus → `len < 2` → Rückfall
auf die Originalkontur. Der Legacy-Voronoi konnte den Fall lösen, weil er rein geometrisch war.

**Fix — geodätische Priority-Flutung** (AINT, arXiv:2509.02929): `_geodesic_priority_assign()`
flutet bandweise vom stärksten Intensitätsband abwärts; alle Marker wachsen gleichzeitig um 1 px
pro Schritt innerhalb des aktuellen Bandes. Daraus folgen beide Eigenschaften ohne Sonderfälle:
- uniformer Verbindungsweg → reine geodätische Distanz, Grenze mittig, Hindernisse respektiert;
- Intensitätssattel vorhanden → Grenze landet automatisch im schwächsten Bereich.

Geodätisch statt euklidisch: Der Weg verläuft **innerhalb** der Maske — genau der Unterschied zum
alten Voronoi. Bandgrenzen werden aus `RADAR_DBZ_BANDS` abgeleitet, damit eine Änderung der
Farbskala nicht nachgezogen werden muss. Watershed-Grenzpixel (`-1`) entfallen; jeder erreichbare
Pixel wird genau einem Kern zugewiesen.

**Gemessen:** U-Form 2520/2541 px in **11 ms**; Sattelfall: Grenze exakt in der schwachen Brücke
(x=100 bei Brücke 60–140). Identisch zu `skimage.segmentation.watershed` (2541/2520) — **ohne neue
Abhängigkeit**; `scikit-image` steht nicht in `requirements.txt`, die Lösung nutzt nur OpenCV/numpy.

**Behobene Regressionen:** `test_b275_multi_core_gap_check::test_u_shape_with_two_cores_and_real_gap_is_split`,
`test_b380_dbz_intensitaetsfeld::test_u_shape_with_real_gap_is_still_split`.

**Tests:** `tests/test_b383_geodaetische_flutung.py` — ausgewogene Teilung bei uniformer Brücke,
2 Kinder beim **Live-Wert** 800, Grenze folgt dem Sattel, Hindernisse respektiert, keine
unzugeordneten Pixel, Einzelkern, Marker außerhalb der Maske, keine skimage-Abhängigkeit,
`cv2.watershed` entfernt.

**Phasen-Status:** Phase A — Segmentierung trennt Sub-Zellen wieder zuverlässig. Voraussetzung
dafür, dass B381 (Split-Integration) im Livebetrieb überhaupt Kandidaten sieht.

### B384 — Drei Bestandstests kodierten die vor-B373-Architektur ✅ erledigt

**Root-Cause:** Kein Code-Defekt. Drei Tests prüften Annahmen, welche die Sanierungsserie bewusst
und begründet geändert hat. Ohne Anpassung bliebe die Suite dauerhaft rot und verdeckte echte
Regressionen. **Nur Testdateien geändert, kein Produktivcode.**

**Klasse 1 — Merge im Kandidatenframe erwartet** (`test_b117_track_continuity`,
`test_object_tracking_regression`): B375 bestätigt einen Übergang erst im zweiten konsistenten
Frame (`TRANSITION_CONFIRM_FRAMES=2`); B382 hält die **Identität** sofort. Der Zweck beider Tests
war bereits erfüllt — im `test_object_tracking_regression` ist die entscheidende Zeile
`assert [obj["id"] …] == ["DOM"]` grün; nur die Folgezeile prüfte `lineage == "merged"` im
Kandidatenframe. Beide Tests prüfen jetzt: Frame 2 = `continued` **mit erhaltener ID**, Frame 3 =
`merged` **ohne ID-Wechsel** und mit vollständiger Parentmenge. Damit decken sie die neue Semantik
strenger ab als zuvor.

**Klasse 2 — positionsloser Geo-Mock** (`test_b365_stage2_weak_cell_match_cap`): Der Mock lieferte
`lambda x, y: (46.7, 14.3)` — konstant. Jede Kontur bekam dieselbe Koordinate, die Distanz war
immer 0 km, jedes km-Gate prinzipiell wirkungslos. Bis B374 folgenlos, weil Stage 2 in skalierten
Pixeln aus Konturmomenten rechnete und `pixel_to_geo` nicht benutzte. Der B379-Schwach-Cap ist
nachweislich korrekt und isoliert getestet (grün) — er greift bei 0 km korrekterweise nicht.
Neuer Mock mit aus `config.py` abgeleitetem Maßstab: `PX_TO_KMH=4.0` → 0.333 km/Original-Pixel,
`UPSCALE_FACTOR=3` → **0.111 km/skaliertem Pixel**; die 90-px-Testdistanz entspricht damit ≈ 10 km.

**Tests:** `tests/test_b384_testsemantik_und_massstab.py` — Maßstab aus der Config ableitbar,
90 px ≈ 10 km, Schwach-Cap greift bei 10 km und nicht bei 0 km, `TRANSITION_CONFIRM_FRAMES=2`,
konstanter Mock kehrt nicht zurück, B117 prüft Frame 3.

**Phasen-Status:** Phase A — Testsuite prüft wieder die tatsächliche Architektur.
**Offen:** Pre-Frame-Parent-Snapshot P0-2 (B385), IR-Entkopplung P1-1 (B386), Resolver-Geometrie
P1-2 (B387), stabile Signaturen/`closed` P1-3/4/5 (B388), Hungarian-Unmatched P1-7 + Zeitbasis
P2-2 (B389), Mehrkern-Komponentengraph P2-4 (B390).

### B385 — Fachliche Cell-Policy bewertete bereits überschriebene Parent-Daten ✅ erledigt

**Root-Cause (P0):** B377 hat die Auswahl-*Funktion* vereinheitlicht, nicht die *Eingabedaten*.
`update_tracking_memory()` arbeitet auf `previous_snapshot = tracking_memory.copy()` und ersetzt
am Ende den globalen Speicher (`tracking_memory = new_memory`, Zeile 2145). **Danach** rief
`main.py:598` die fachliche Lineage mit `previous_objects=tracking_memory` auf — also mit dem
bereits überschriebenen Stand.

Darin trägt der **Survivor** bereits das neue, verschmolzene Objekt (Fläche der Systemkontur), und
die beendeten **Secondary-Parents fehlen vollständig** → `po = {}` → `area=0`, `core_ratio=0`,
`total_active_frames=0`. `continuity_score()` gewichtet genau diese Felder (0.30/0.30/0.25/0.15) →
Score **0.0** → jeder Secondary-Parent verlor automatisch, unabhängig von seiner Stärke. Betrifft
**alle vier** Policies. Das Abnahmekriterium „Radar- und fachliche Primary wählen denselben
Parent" war damit strukturell unerfüllbar.

**Fix:** Neues Modulattribut `object_tracking.last_previous_snapshot` wird **vor** dem Ersetzen von
`tracking_memory` gefüllt und hält den unveränderlichen Pre-Frame-Zustand. `main.py` reicht ihn als
`previous_objects` durch; Fallback auf `tracking_memory` nur, falls das Attribut fehlt
(Alt-Deployment) — dann greift das alte Verhalten, statt dass die Lineage ganz ausfällt. Der
Vertrag wird damit von einer impliziten Annahme zu einer expliziten Übergabe. Signaturen bleiben
unverändert.

**Tests:** `tests/test_b385_pre_frame_parent_snapshot.py` — Attribut existiert, Snapshot trägt den
Pre-Frame-Stand, beendeter Secondary-Parent bleibt mit `area>0` erhalten, Survivor trägt **nicht**
das verschmolzene Objekt (Gegenprobe gegen `tracking_memory`), leeres Parent-Dict verliert immer,
`main.py` reicht durch, Snapshot ist von `tracking_memory` entkoppelt.

**Phasen-Status:** Phase A — Radar- und Fachebene bewerten dieselben Daten.
**Offen:** IR-Entkopplung P1-1 (B386), Resolver-Geometrie P1-2 (B387), stabile Signaturen/`closed`
P1-3/4/5 (B388), Hungarian-Unmatched P1-7 + Zeitbasis P2-2 (B389), Mehrkern-Komponentengraph P2-4
(B390), IR-`cell_id` umgeht Merge-Policy P2-1.

### B386 — Radarbasierte Merge/Split-Lineage hing an der Satellitenpipeline ✅ erledigt

**Root-Cause (P1):** `update_split_merge_lineage()` lag in `main.py` **doppelt verschachtelt**
(Einrückung 25) im erfolgreichen IR-Pfad. Die Radar-Lineage wurde in drei Fällen übersprungen,
obwohl Radartracking und Objekterkennung erfolgreich liefen:
1. `run_ir_precursor_pipeline()` (Zeile 578) wirft — z. B. kein aktuelles EUMETView-TIFF;
2. `_score_match_ir_radar_lineage()` (Zeile 583) wirft → `except` bei 604 → der Legacy-IR-Fallback
   läuft, aber der Lineage-Aufruf wird nie erreicht;
3. jeder Fehler dazwischen.

Das ist eine plausible Miterklärung für den B372-Befund (weder `cell_lineage_events.jsonl` noch
`cell_lineage_state.json` im Debug-Export vom 14.07.2026, obwohl 160 Objekte ein von
`record_cell_merge()` gesetztes `lineage_status` trugen): In jedem Zyklus ohne aktuelles IR-TIFF
fiel die gesamte Radar-Lineage aus.

**Fix:** Die Radar-Lineage läuft als **eigenständiger Schritt mit eigener Fehlerdomäne**
unmittelbar nach der Radar-Objekterkennung, **vor** der IR-Pipeline. Die IR→Radar-Lineage bleibt
danach als zusätzliche Herkunfts-/Alias-Beziehung erhalten. Der Pre-Frame-Snapshot aus B385 wird
unverändert durchgereicht.

**Nebenbefund (verifiziert, mitbehoben):** `_lineage_events.extend(_split_merge_events or [])`
(Zeile 601) war **wirkungslos** — `_lineage_events` wird nach Zeile 587 nie mehr gelesen; die
Persistenz erfolgt über `append_lineage_event()` innerhalb von `record_cell_merge/split()`. Die
Zeile entfiel daher ersatzlos.

**Tests:** `tests/test_b386_radar_lineage_unabhaengig_von_ir.py` — Aufruf vor der IR-Pipeline,
Einrückung ≤ 17 (nicht mehr im IR-Block), genau ein Aufruf, toter `extend` entfernt, eigener
Exception-Handler, B385-Snapshot erhalten, `main.py` kompiliert.

**Phasen-Status:** Phase A — Radar-Lineage aus der IR-Fehlerdomäne gelöst.
**Verifikationspflicht:** Im nächsten Debug-Export muss `cell_lineage_events.jsonl` vorhanden sein
und `cell_lineage_write_status.json` `last_result="ok"` melden (B372).
**Offen:** Resolver-Geometrie P1-2 (B387), stabile Signaturen/`closed` P1-3/4/5 (B388),
Hungarian-Unmatched P1-7 + Zeitbasis P2-2 (B389), Mehrkern-Komponentengraph P2-4 (B390),
IR-`cell_id` umgeht Merge-Policy P2-1.

### B387 — Merge-Erklärung zählte den Survivor mit 0 und addierte überlappende Flächen doppelt ✅ erledigt

**Root-Cause (P1):** `explained` maß nicht, was es zu messen vorgab — zwei Rechenfehler im selben
Ausdruck.

1. **Survivor trug 0 bei.** `survivor = matched.get(det_idx)` ist per Definition ein global
   1:1 gematchter Track; der Parameter `unmatched_tracks` enthält ausschließlich **nicht**
   gematchte. `survivor in unmatched_tracks` war damit immer falsch → Beitrag immer `0.0`. Der
   Survivor ist aber typischerweise der **größte** Beitragende. Beispiel: Survivor 70 % +
   Secondary 25 % = 95 % → gezählt wurden 25 % → Merge fiel an
   `TRANSITION_MERGE_MIN_EXPLAINED=0.50` durch. **Echte Merges wurden systematisch verworfen.**
2. **Überlappende Parents wurden doppelt gezählt.** `explained += inter` addierte die
   Einzelschnitte. Bei konvergierenden Zellen kurz vor der Fusion — genau der zu erkennende Fall —
   wurde der gemeinsame Bereich mehrfach gezählt; `explained` konnte **> 1.0** werden.

Beide Fehler wirkten gegenläufig (Unter- bzw. Überschätzung) und machten `explained` unbrauchbar.
Das Abnahmekriterium „`explained_ratio` liegt immer zwischen 0 und 1 und enthält den
Survivor-Beitrag" war in **beiden** Teilen verletzt.

**Fix:**
- `find_merge_candidates(all_tracks, …)` erhält **alle** alten Tracks (analog B381 für Splits).
  Der Survivor ist per globalem Match qualifiziert und umgeht die Eigenabdeckungsschranke; ein
  Track, der 1:1 einer **anderen** Detektion zugeordnet ist, wird als eigenständig
  weiterlebend ausgeschlossen.
- `_explained_union_ratio()`: **geometrische Vereinigung** (`shapely.ops.unary_union`) der
  Parent-Schnittflächen statt deren Summe → jeder Bereich zählt genau einmal, Ergebnis per
  Konstruktion in `[0, 1]`. Fallback ohne `unary_union` deckelt auf die Zielfläche, statt falsch
  zu bestätigen.
- `TRANSITION_MERGE_MIN_PARENT_COVERAGE` bleibt für alle Nicht-Survivor unverändert wirksam.

**Tests:** `tests/test_b387_merge_erklaerung_union.py` — Survivor-Beitrag zählt (95 %-Kernfall),
keine Doppelzählung bei Überlappung, `explained` in [0,1], Gegenprobe gegen die alte Summenlogik
(hätte 5.0 ergeben), anderweitig gematchter Track ist kein Parent, Eigenabdeckung bleibt wirksam,
Einzelparent, unzureichende Erklärung, Leereingaben.

**Phasen-Status:** Phase A — Merge-Erklärung ist geometrisch korrekt.
**Offen:** Stabile Signaturen P1-3, `closed`-Zustand P1-5, bestätigte Parentmenge P1-4 (B388),
Hungarian-Unmatched P1-7 + Zeitbasis P2-2 (B389), Mehrkern-Komponentengraph P2-4 (B390),
IR-`cell_id` umgeht Merge-Policy P2-1.

### B388 — Transition-Signaturen enthielten frameweise Detektionsindizes ✅ erledigt

**Root-Cause (P1):** Eine frameübergreifende Identität wurde aus frameweise gültigen Daten
gebildet. `transition_signature("merge", parents, [str(det_idx)])` bzw.
`("split", [tid], [str(c) for c in children])` enthielten **Detektionsindizes** — Positionen in der
Rückgabeliste von `cv2.findContours()`, gültig nur innerhalb eines Frames.

`confirm_candidates()` führt den Bestätigungszähler über die Signatur. Wechselte sie bei
**unveränderter Geometrie**, war `pending.get(signature)` leer → `frames_seen=1` → der Kandidat
fiel zurück und wurde **nie bestätigt**; gleichzeitig galt die alte Signatur als `reverted`.

Besonders tückisch: Bei einem Merge ändert sich die Konturanzahl per Definition (2 Zellen → 1
Kontur), die Indizes verschieben sich im Bestätigungsframe also **regelmäßig**. B370 hat die
*Gruppierung* reihenfolgeinvariant gemacht, nicht die *Indizierung*. Folge: Mit
`TRANSITION_CONFIRM_FRAMES=2` entstand oft **gar kein** Ereignis — kein `merged`, kein `split`,
kein Ledger-Eintrag; die Kandidatenphase (B382) lief endlos weiter.

**Fix — Identität aus frameübergreifend stabilen Größen:**
- **Merge:** `sha1("merge" | sorted(parent_ids))`. Die Kindmenge ist implizit — dieselben Parents
  verschmelzen zu **einer** Zelle; der Detektionsindex trägt keine Information (`_stable_merge_key`).
- **Split:** `sha1("split" | parent_id | "n=<anzahl>")`. Die Kinder haben noch keine Track-IDs;
  die **Anzahl** ist stabil und trennt einen 2er- von einem 3er-Split desselben Parents
  (`_stable_child_key`).
- `TransitionCandidate.children` bleibt für die Objektschleife erhalten, geht aber nicht mehr in
  die Identität ein.

Damit ist das Abnahmekriterium „Übergänge bestätigen unabhängig von der Konturreihenfolge"
erfüllt. Die zeitstempelfreie Ereignis-Signatur in `cell_lineage.py` (B371) ist unberührt — sie
arbeitet bereits nur mit `cell_id`s.

**Tests:** `tests/test_b388_stabile_transition_signaturen.py` — Merge/Split-Signatur überlebt
Indexwechsel, Bestätigung erfolgt trotz Indexverschiebung ohne falsches `reverted`,
unterschiedliche Kinderanzahl = anderes Ereignis, andere Parentmenge = andere Signatur,
Parent-Reihenfolge irrelevant, Indizes kehren nicht zurück, `children` bleibt nutzbar.

**Phasen-Status:** Phase A — Übergänge bestätigen reihenfolgeunabhängig.
**Offen:** `closed`-Zustand P1-5 (B389), bestätigte Parentmenge P1-4 (B390),
Hungarian-Unmatched P1-7 + Zeitbasis P2-2, Mehrkern-Komponentengraph P2-4,
IR-`cell_id` umgeht Merge-Policy P2-1.

### B389 — Suchradius ohne bekannten Bewegungsvektor nutzte den engen Querradius ✅ erledigt

**Root-Cause:** Invertierte Logik in `_search_radii_km()`. Bei `speed < 1.0` wurde
`(b_km, b_km)` zurückgegeben — der **Querradius**, isotrop angewendet. Der Kommentar
(„isotroper Kreis mit dem engeren Radius") beschrieb den Denkfehler exakt.

Der Querradius ist eng, **weil** die Bewegungsrichtung bekannt ist: eine nach Osten ziehende Zelle
springt nicht 12 km nach Norden. Diese Einschränkung setzt den Vektor voraus. Fehlt er, gibt es
kein „quer" — die Zelle kann in **jede** Richtung mit voller Geschwindigkeit ziehen.

**Nachgerechnet** (`MAX_CELL_SPEED_KMH=150`, `dt=5 min`): `reach=12.50 km`, `a_km=14.50 km`,
`b_km=7.62 km`. Der Code lieferte **7.62 km isotrop** statt 14.50 km — **39 % zu eng**, und das
ausgerechnet für die Tracks mit der größten Positionsunsicherheit: jede neue Zelle im zweiten
Frame (Kalman noch ohne Geschwindigkeit), stationäre orografisch gebundene Konvektion (in Kärnten
häufig) und Tracks ohne Kalman-Filter. Folge: Match verworfen → neue ID → Verlust von
Kalman-Zustand, Trend, Lebensdauer und ML-Sequenz.

**Fix:** `return (a_km, a_km, 1.0, 0.0)`. Der Schwach-Cap aus B379 bleibt unberührt und wirkt jetzt
**schärfer**, weil er gegen den richtigen Radius greift (60 km/h → 7.00 km statt 4.25 km).

**Behobene Regression:** `test_b365_stage2_weak_cell_match_cap::test_strong_cell_still_matches_at_same_distance`.
Bei der realistischen Testdistanz aus B384 (90 skalierte px ≈ 10.0 km): starke Zelle → Radius
14.50 km → **Match**; schwache Zelle → Radius 7.00 km → **gegatet**. Beide Testfälle korrekt.

**Tests:** `tests/test_b389_suchradius_ohne_vektor.py` — isotroper Radius nutzt `a_km`, Radius ≥
Cap-Reichweite, bewegter Track behält engen Querradius (B373-Kernidee), stehende starke Zelle
matcht bei 10 km, schwache bleibt gegatet, absurde Distanz weiter gegatet, Skalierung mit realem dt.

**Phasen-Status:** Phase A — Suchraum entspricht der konfigurierten Physik.
**Offen:** Merge-Bestätigung mit verschwindendem Secondary-Parent (B390), bestätigte Parentmenge
P1-4, Hungarian-Unmatched P1-7, Zeitbasis Polygon/Position P2-2, Mehrkern-Komponentengraph P2-4,
IR-`cell_id` umgeht Merge-Policy P2-1.

### B390 — Test-Snapshot nutzte konstante lat/lon, inkonsistent zum Geo-Mock ✅ erledigt

**Root-Cause:** Alter Track und neue Detektion wurden aus **zwei verschiedenen Geo-Quellen**
gespeist — durch **B384** eingeführt, kein Defekt der Gates.
- Detektion: `pixel_to_geo` — seit B384 positionsabhängig (0.111 km/skaliertem Pixel).
- Alter Track: `_snapshot_obj()` setzte hart `"lat": 46.7, "lon": 14.3` — **konstant**, also die
  Koordinate von Pixel (0,0). B384 hat den Mock korrigiert, den Snapshot nicht nachgezogen.

**Nachgerechnet:** Zentren (75,75) → (165,75) = 90 px = **10.0 km** (gewollt). Tatsächlich
gemessen wurde `lon=14.3` gegen `lon=14.5399` → **20.1 km** > 14.5 km Radius → gegatet. Der alte
Track wurde gegen den **Bildursprung** statt gegen sein Konturzentrum gemessen; der Fehler
entspricht exakt seiner Absolutposition. **B389 ist korrekt und wirksam** (eigener Test 9/9 grün);
der 14.5-km-Radius reicht nur nicht für eine künstlich verdoppelte Distanz.

**Fix:** `_geo_from_pixel_for_test()` als **einzige** Geo-Quelle — Snapshot und `pixel_to_geo`-Mock
verwenden dieselbe Abbildung.

**Zweiter Teil desselben Root-Cause — stiller Skip:** `_build_track_candidates()` verwarf Tracks
ohne `lat`/`lon` **lautlos** (`continue`). Produktiv wäre das ein ID-Totalverlust ohne Spur im Log:
alle Konturen des Tracks würden `new`. Jetzt: Fallback auf Rekonstruktion aus `x`/`y` über
`pixel_to_geo`; nur ohne **jede** Position wird ausgeschlossen — dann mit explizitem
`[B390] … ID-Verlust!`-Logeintrag.

**Behobene Regression:** `test_b365_stage2_weak_cell_match_cap::test_strong_cell_still_matches_at_same_distance`.

**Tests:** `tests/test_b390_geo_konsistenz.py` — konstante Koordinate kehrt nicht zurück, 90 px =
10 km, Track ohne lat/lon wird rekonstruiert, Track ohne jede Position wird protokolliert,
Normalfall unverändert.

**Phasen-Status:** Phase A — Geo-Quellen konsistent, ID-Verlust bei unvollständigem Snapshot
ausgeschlossen.
**Offen:** Merge-Bestätigung mit verschwindendem Secondary-Parent (B391), bestätigte Parentmenge
P1-4, Hungarian-Unmatched P1-7, Zeitbasis Polygon/Position P2-2, Mehrkern-Komponentengraph P2-4,
IR-`cell_id` umgeht Merge-Policy P2-1.

### B392 — IR-Bestätigung überschrieb bestätigte Radar-Merge-/Split-Lineage ✅ erledigt

**Root-Cause:** B386 führte die Radar-Lineage korrekt unabhängig und vor der optionalen
IR-Pipeline aus. `apply_ir_radar_lineage_match()` setzte danach jedoch immer die IR-`cell_id`,
`lineage_status="radar_confirmed"` und `radar_to_cell` neu. Bei einem Merge/Split im selben Zyklus
widersprachen sich dadurch Ledger-Ereignis, finales Radarobjekt und gespeicherter State. Auch der
Legacy-Distanzfallback überschrieb die Objekt-`cell_id`.

**Fix:** Eine bestätigte strukturelle Radar-Lineage behält ihre kanonische `cell_id` und ihren
Merge-/Split-Status. Die spätere IR-Bestätigung wird auf diese ID reconciled. Radarobjekt,
IR-Track, `radar_to_cell`, `ir_to_cell` und `ir_to_radar_confirmation`-Event verwenden danach
dieselbe ID. Die frühere IR-ID bleibt als bestätigter Alias nachvollziehbar und kann kein negatives
Lead-Time-Label mehr erzeugen. Normale IR→Radar-Bestätigungen ohne Merge/Split übernehmen weiterhin
die IR-Vorläufer-ID.

B386 bleibt unverändert: Radar-Lineage läuft weiterhin auch bei Ausfall der IR-Pipeline.

**Tests:** `tests/test_b392_ir_match_erhaelt_radar_lineage.py`.

### B393 — Split-Signatur bestand nach B388 nur aus Parent-ID und Kinderanzahl ✅ erledigt

**Root-Cause:** B388 entfernte zu Recht frame-lokale Detektionsindizes, ersetzte sie beim Split
aber nur durch `n=<anzahl>`. Zwei geometrisch verschiedene 2er-Splits desselben Parents erhielten
damit dieselbe Pending-Signatur. `confirm_candidates()` konnte den zweiten, anderen Split mit dem
Zähler des ersten bestätigen.

**Fix:** Die Split-Signatur enthält eine sortierte, quantisierte Parent-lokale Kindgeometrie:
relative Schwerpunktposition und erklärter Parent-Flächenanteil je Kind. Sie bleibt unabhängig von
Detektionsindex, Kindreihenfolge, gemeinsamer Translation und Skalierung, unterscheidet aber
verschiedene räumliche Aufteilungen und deutlich andere Flächenanteile.

**Tests:** `tests/test_b393_split_signatur_geometrie.py` sowie Erweiterung von
`tests/test_b388_stabile_transition_signaturen.py`.

### B391 — Secondary-Parent wurde im Kandidatenframe beendet: kein Merge konnte je bestätigt werden ✅ erledigt

**Root-Cause (P0):** Die Bestätigung braucht zwei Frames, der zweite Parent überlebte aber nur
einen. B375 verlangt `TRANSITION_CONFIRM_FRAMES=2`, und ein Merge-Kandidat verlangt **≥ 2
Parents**. Der Secondary-Parent ist nicht 1:1 gematcht (der Survivor bekam die Kontur), landet
nicht in `new_memory` und wurde in `object_tracking.py:2093 ff.` als `dissolved` ausgebucht. Im
Bestätigungsframe existierte er nicht mehr → `len(parents) < 2` → **0 Kandidaten**.

**Laufzeitbeleg** (Spy auf `find_merge_candidates`, `test_object_tracking_regression`):
```
FRAME 2: tracks=['CHILD','DOM'] -> 1 Kandidat (explained=0.7941), danach memory=['DOM']
FRAME 3: tracks=['DOM']         -> 0 Kandidaten -> nie bestaetigt
```

**Tragweite:** **Kein Merge konnte im gesamten System jemals bestätigt werden** — kein
`lineage="merged"`, kein Eventledger-Eintrag (B371), kein `origin_type="created_by_merge"` (B378),
die Karte zeigte nie einen Verbund, die Primary-Policy (B377/B385) lief ins Leere. Der
ursprüngliche Befund der Analyse (160 Merge-Beobachtungen) hätte sich in **0 bestätigte Merges**
verkehrt.

`test_b117_track_continuity` war grün, weil dort beide Parents die Merge-Kontur ausreichend
überlappen und der kleine Parent über den Merge-Fallback erneut in `overlaps` landet. Der Defekt
ist nicht geometrieabhängig, sondern nur **geometrieabhängig sichtbar**.

**Fix:** Ein Track, der Parent eines **noch nicht bestätigten** Übergangs ist, ist nicht aufgelöst
— er bleibt bis zur Entscheidung (`confirmed`/`reverted`) im Speicher, mit
`tracking_state="merge_pending"`, `is_active_cell=False`, `silent_tracking=True`. Das entspricht
dem bestehenden `inactive_rain`-Muster (stilles Tracking). Pending-Parents werden **nicht** als
Zellen ausgegeben — weder auf der Karte noch in Warnungen oder ML-Sequenzen.
`TRANSITION_CONFIRM_FRAMES` bleibt bei 2; eine Senkung auf 1 hätte den Defekt kaschiert und den
Schutz gegen flackernde Pixelbrücken entwertet.

**Tests:** `tests/test_b391_merge_parent_ueberlebt_kandidatenphase.py` — beide Parents überleben
den Kandidatenframe, Merge wird in Frame 3 bestätigt, Pending-Parent erscheint nicht als Zelle,
`merge_pending`-Zustand korrekt, Zustand endet nach der Bestätigung, echte aufgelöste Zelle
expiriert weiterhin, Bestätigungsschwelle unverändert.

**Phasen-Status:** Phase A — der Merge-Pfad ist erstmals vollständig funktionsfähig.
**Verifikationspflicht:** Im nächsten Debug-Export muss `lineage="merged"` **auftreten** und
`cell_lineage_events.jsonl` `cell_merge`-Einträge enthalten — bei gleichzeitig **höchstens einem**
Ereignis je Signatur (B371).
**Offen:** Bestätigte Parentmenge P1-4, Hungarian-Unmatched P1-7, Zeitbasis Polygon/Position P2-2,
Mehrkern-Komponentengraph P2-4, IR-`cell_id` umgeht Merge-Policy P2-1.

### B394 — Testgeometrien in B385/B391 erklärten ihre Merge-Kontur nicht ✅ erledigt

**Root-Cause:** Kein Code-Defekt. Die Testgeometrien bildeten **keinen gültigen Merge-Kandidaten**
und scheiterten an einer Vorbedingung, die sie selbst verletzten. **Nur Testdateien geändert.**

**B391 ist nachweislich wirksam:** `tests/test_object_tracking_regression.py` läuft **6/6 grün**,
inklusive `test_merge_with_dominant_parent_without_kf_does_not_crash`, das zuvor am
verschwindenden Secondary-Parent scheiterte.

**Nachgerechnet (B391-Test):** Parents 6.400 + 2.500 px, Merge-Kontur 36.100 px →
`explained = 7.050/36.100 = 0.195` < `TRANSITION_MERGE_MIN_EXPLAINED = 0.50` → kein Kandidat →
`_pending_parent_ids` leer → der B391-Schutz konnte nicht greifen. Im B385-Test identisch:
`explained = 0.119`. Die Parent-Coverage war in beiden Fällen erfüllt (0.75/0.90) — nur die
Erklärung der Zielkontur nicht.

**Warum die Geometrie falsch war:** Die Merge-Kontur war jeweils ~4× größer als die Summe ihrer
Parents. Das ist fachlich **kein Merge**, sondern eine Systemhülle — der Code lehnte sie korrekt ab
(Analyse 5.9). Ursache: `_square()` erzeugt ein **Quadrat**; zwei nebeneinanderliegende Parents
brauchen eine breite, **flache** Kontur. Ein Quadrat, das beide horizontal umschließt, ist
zwangsläufig auch vertikal riesig und damit größtenteils leer.

**Gegen reale Daten belegt** (Debug-Export 14.07.2026, 160 Merge-Beobachtungen mit
Parent-Geometrie, `explained` nach B387-Union-Rechnung): **Median 1.00**, p75 1.00, p25 0.69,
p10 0.48. Reale Merge-Konturen werden von ihren Parents im Median vollständig erklärt; 0.195 und
0.119 liegen weit unter dem 10 %-Perzentil. Die Schwelle 0.50 wird von **89 %** der realen
Beobachtungen erfüllt — die verworfenen 11 % sind genau die Scheinmerges, die B375/B387
aussortieren sollen. `TRANSITION_MERGE_MIN_EXPLAINED` bleibt daher **unverändert**.

**Fix:** Neuer Helfer `_rect_contour(x1, y1, x2, y2)` in beiden Testdateien. Neue Geometrie:
Parents 60..140 und 150..230 (je 80×80), Merge 60..230 × 160..240 (170×80) →
coverage 1.00/1.00, **explained 0.94** — realistisch.

**Tests:** `tests/test_b394_testgeometrie_erklaert_merge.py` — neue Geometrie erzeugt einen
Kandidaten (explained ≈ 0.94), alte Quadrat-Geometrie wird korrekt verworfen (Beleg, dass der Code
richtig lag), Coverage je Parent erfüllt, Schwelle liegt unter dem realen p10, `_rect_contour` in
beiden Dateien vorhanden.

**Phasen-Status:** Phase A — **Serie B370–B394 abgeschlossen, keine offenen Regressionen.**
Verbleibend nur vorbestehend: `test_b150_tawes_breaker`, `test_b243_baseline_gate` (beide bereits
in Baseline `a7912311` rot) und `test_frontend_build` (benötigt `vite`).
**Offen (funktionale Verbesserungen, keine Blocker):** Bestätigte Parentmenge P1-4, `closed`-Zustand
P1-5, Hungarian-Unmatched P1-7, Zeitbasis Polygon/Position P2-2, Mehrkern-Komponentengraph P2-4,
IR-`cell_id` umgeht Merge-Policy P2-1.
**Nächster fachlicher Schritt:** Debug-Export der nächsten Konvektionslage auswerten — B391 macht
bestätigte Merges erstmals möglich; `lineage="merged"` und `cell_merge`-Einträge im Ledger müssen
auftreten, bei höchstens einem Ereignis je Signatur (B371).

### B395 — Bestätigter Merge übernahm Parents, die der Resolver nie bestätigt hat ✅ erledigt

**Root-Cause (P1-4):** Die Parentmenge des Ereignisses stammte aus einer anderen Quelle als die
Bestätigung. Zwei Auswahlen mit **unterschiedlichen Schwellen** liefen nebeneinander:
- **Resolver** (`transition_resolver.py`): `TRANSITION_MERGE_MIN_PARENT_COVERAGE = 0.40` plus
  `MIN_EXPLAINED = 0.50` → `_transition.parents`.
- **Objektschleife** (`object_tracking.py:1756`): `_old_coverage_m >= 0.30` → `_overlap_by_id`.

Beim bestätigten Merge wurde **die zweite** verwendet (`parents = [oid for oid, _ in overlaps]`,
Zeile 1869). `_transition` diente nur als **Auslöser**; seine bestätigte Menge wurde verworfen.

**Folge:** Ein Randtrack mit 31 % Abdeckung erfüllt `>= 0.30`, aber nicht `>= 0.40`. Er war nicht
Teil des bestätigten Ereignisses, landete trotzdem in `parents` — erschien im `cell_merge`-Event
(B371), wurde über `lineage_end="merged_into:…"` als beendet markiert und verlor seine Identität,
und konnte bei hohem Trackalter/Kernwert sogar die Primary-Policy (B377/B385) gewinnen. **Die
0.40-Schwelle war damit wirkungslos** — genau der Defekt, den sie verhindern sollte (Analyse 5.9).

**Belegte Relevanz** (Debug-Export 14.07.2026, 373 Parent-Beziehungen aus 160 Merges):
≥ 0.30 → 313/373 (84 %), ≥ 0.40 → 292/373 (78 %). **21 Beziehungen (~6 %)** liegen zwischen beiden
Schwellen und wurden fälschlich übernommen.

**Fix:** `parents` wird auf `_transition.parents` gefiltert; `overlaps` liefert nur noch die
**Reihenfolge** (dominanter Parent zuerst, nach B377-Policy sortiert), nicht die Mitgliedschaft.
Ein bestätigter Parent, der nicht in `overlaps` steht, geht defensiv nicht verloren. Der dominante
Parent — und damit die geerbte ID — stammt jetzt zwingend aus der bestätigten Menge. Die
0.30-Schwelle bleibt für die **Kandidatenermittlung** und die Kandidatenphase (B382) unverändert;
dort ist das weite Netz korrekt.

**Tests:** `tests/test_b395_bestaetigte_parentmenge.py` — Randtrack zwischen 0.30 und 0.40 wird
nicht übernommen, Resolver-Schwelle ist strenger als die Schleifen-Schwelle, ID stammt aus der
bestätigten Menge, sauberer 2er-Merge unverändert, statischer Nachweis der Quelle,
Kandidaten-Schwelle bleibt erhalten.

**Phasen-Status:** Phase A — Ereignis und Bestätigung nutzen dieselbe Parentmenge.
**Offen:** `closed`-Zustand P1-5, Hungarian-Unmatched P1-7, Zeitbasis Polygon/Position P2-2,
Mehrkern-Komponentengraph P2-4.

### B396 — Zustandsautomat kannte kein `closed`: Übergänge blieben dauerhaft `confirmed` ✅ erledigt

**Root-Cause (P1-5):** Der dokumentierte Automat existierte nicht. Der Modul-Docstring beschreibt
`candidate -> confirmed -> closed` / `-> reverted`; implementiert war nur
`candidate -> confirmed`. `confirm_candidates()` schrieb **jede** Signatur zurück in
`new_pending` — auch bereits bestätigte. `frames_seen` wuchs unbegrenzt (3, 4, 5 …) und blieb
`>= need`, sodass derselbe Übergang in **jedem Folgeframe erneut als `confirmed`** gemeldet wurde —
ein Zustand, der als **Ereignis** gemeint war.

Strukturell derselbe Defekt, den B371 auf der Fachschicht behob (wiederholte Merge-Events), nur
eine Ebene tiefer: B371 dedupliziert den Ledger, die Transition-Logik meldete weiter.

**Der bestehende Test war blind:** `test_repeated_merge_confirms_once_not_every_frame` prüfte nur
`len(set(signatures)) == 1` — zehn identische Bestätigungen erfüllen das ebenso wie eine einzige.
Er ist jetzt um `len(signatures) == 1` ergänzt.

**Warum es bisher nicht auffiel:** B371 (Ledger-Dedup) und B391 (Parent lebt nur bei
`phase == "candidate"`, wird danach ausgebucht) fingen es als **Nebeneffekt** ab. Sobald ein Parent
aus anderem Grund erhalten bleibt (`inactive_rain`, Rain-Support, künftiger Konsument), hätte der
Resolver denselben Merge erneut bestätigt — mit `lineage="merged"` in jedem Folgeframe, also exakt
dem Ausgangsbefund der Analyse (23 Serien, Mittel 6.6, längste 11 Frames).

**Fix:** `pending` speichert jetzt `{"frames_seen": int, "phase": str}` statt einer blanken Zahl.
`confirmed` wird **genau einmal** ausgegeben — beim Übergang von `candidate`; danach ist der
Übergang `closed` (die Konstellation besteht fort, das Ereignis ist abgeschlossen). Da die
Objektschleife `phase == "confirmed"` prüft, ist `lineage="merged"` damit automatisch auf den
Ereignisframe begrenzt. `_pending_entry()` liest das Alt-Format (blanke Zahl) abwärtskompatibel,
damit ein Deployment ohne Neustart nicht doppelt bestätigt. `reverted` und
`TRANSITION_CONFIRM_FRAMES=2` bleiben unverändert; B391 (`phase == "candidate"`) und B395 bleiben
unberührt.

**Tests:** `tests/test_b396_closed_zustand.py` — 10 Frames → genau 1 Bestätigung, Phase wird
`closed`, Kandidatenphase unverändert (B391-Kopplung), `reverted` vor und nach `closed`,
Alt-Format lesbar, Alt-State bestätigt nur einmal, andere Konstellation wird nicht blockiert.

**Phasen-Status:** Phase A — der Zustandsautomat entspricht seiner Dokumentation.
**Offen:** Hungarian-Unmatched P1-7, Zeitbasis Polygon/Position P2-2, Mehrkern-Komponentengraph
P2-4.


### B397 — `merge_pending`-Parent kontaminierte B94-/ML-Nachbarfeatures ✅ erledigt

**Root-Cause:** B391 hält einen Secondary-Parent während der Merge-Kandidatenphase korrekt als
`tracking_state="merge_pending"` und `silent_tracking=true` in `new_memory`, damit derselbe
Übergang im zweiten Frame bestätigt werden kann. Der Parent wird später aus Karte, Warnungen und
ML-Sequenzen übersprungen. Der davor laufende B94-Durchlauf verwendete jedoch
`list(new_memory.values())` ungefiltert. `_compute_neighbor_ahead()` zählte den versteckten Parent
dadurch als eigenständigen Nachbarn einer sichtbaren Zelle.

Betroffen waren `neighbor_count_ahead`, `neighbor_max_core_ahead`,
`neighbor_min_dist_km_ahead` und `strat_area_ahead_px`. Dasselbe physikalische System konnte
während eines Merge-Kandidaten doppelt in ML-/Forecast-Features eingehen.

**Fix:** Zentrale `_is_neighbor_feature_eligible()`-Regel. `merge_pending` wird sowohl aus dem
B94-Objektpool entfernt als auch defensiv direkt in `_compute_neighbor_ahead()` als Subjekt und
Nachbar ausgeschlossen. Der Parent bleibt für B391/B395/B396 vollständig im Tracking-Speicher.
Andere Tracking-Zustände, insbesondere `inactive_rain`, bleiben unverändert.

**Testkorrektur:** B396 änderte `pending` von einer Zahl auf
`{"frames_seen": ..., "phase": ...}`. Der B393-Geometrietest wurde auf das neue Schema migriert;
die `closed`-Produktionslogik bleibt unverändert.

**Tests:** `tests/test_b397_merge_pending_neighbor_features.py`, Erweiterung von
`tests/test_b391_merge_parent_ueberlebt_kandidatenphase.py` und Korrektur von
`tests/test_b393_split_signatur_geometrie.py`.

**Phasen-Status:** Technisch erhaltene Übergangsparents sind nun auch aus abgeleiteten
ML-/Umgebungsfeatures vollständig ausgeschlossen.

### B398 — Volltest nach B397: vier Testregressionen und doppelte `.env`-Schlüssel ✅ erledigt

Der vollständige Pi-Lauf nach B397 endete mit `1940 passed, 4 failed, 1 skipped`; die B397-Kernregressionen waren grün.

- **B117:** unrealistische Quadrat-Scheinmerge-Geometrie durch erklärbare Rechteckgeometrie ersetzt.
- **B150:** Messdaten- und Metadata-Circuit-Breaker werden getrennt und ohne Capture-Überschreibung geprüft.
- **B391/B397:** Frame-2-State wird pro Objekt kopiert, damit Frame 3 den Test-Snapshot nicht mutiert.
- **`.env`:** Install-/Upgrade entfernt aktive Duplikate atomar unter Erhalt des bisher effektiven letzten Werts, der Kommentare und Dateirechte; Secret-Werte werden nicht geloggt.

Produktions-Tracking, Transition-Gates, TAWES-Requests und B397 wurden nicht verändert.


### B399 — letzte zwei Pytest-Metatestfehler nach B398 ✅ erledigt

**Ausgangslage:** Der vollständige Pi-Lauf nach B398 sammelte 1955 Tests und endete mit
`1951 passed, 2 failed, 2 skipped`. Die eigentlichen B398-Fixes waren grün: B117-Merge-Test,
beide TAWES-Breaker-Tests, B391-Snapshot, B397-Nachbarfeatures und `.env`-Deduplizierung.

**B384 Root-Cause:** Der Metatest suchte weiterhin exakt nach dem alten lokalen Variablennamen
`m3`, obwohl der erfolgreiche B117-Test die fachlich identische Assertion über `objs3[0]`
ausführt. Der Metatest analysiert nun gezielt die Funktion
`test_merge_inherits_dominant_parent_id` und prüft variablennamenunabhängig den dritten Frame
sowie `lineage == "merged"`.

**B391 Root-Cause:** Der Test behandelte den internen Value aus `tracking_memory` als
vollständiges Ausgabeobjekt und griff auf `pending_parent["id"]` zu. Die kanonische Track-ID ist
jedoch der Key des Mappings. Die Emissionsprüfung verwendet nun diesen Key und erzwingt kein
redundantes `id`-Feld im internen State.

**Produktivcode:** unverändert.

**Tests:** Anpassung von `tests/test_b384_testsemantik_und_massstab.py` und
`tests/test_b391_merge_parent_ueberlebt_kandidatenphase.py`; neuer Vertrags-Schutz
`tests/test_b399_test_contracts.py`.

### B400 — `ASSOC_MAX_COST` war unerreichbar; Hungarian konnte keine Nicht-Zuordnung wählen ✅ erledigt

**Root-Cause (P1-7):** Die Qualitätsschwelle der Zuordnung war rechnerisch unerreichbar und griff
zu spät.

1. **Unerreichbar:** Alle sechs Kostenkomponenten sind auf `[0,1]` normiert, die `ASSOC_W_*`-Gewichte
   summieren sich auf **exakt 1.00** (0.35+0.25+0.15+0.10+0.10+0.05). Die teuerste mögliche Paarung
   kostet damit 1.00; verworfen wurde bei `cost > max_cost` mit `ASSOC_MAX_COST = 1.0` — **nie**.
   Die Schwelle war toter Code; es filterten ausschließlich die harten Gates (`_INF`).
2. **Zu spät:** `linear_sum_assignment()` minimiert die **Gesamtsumme** und muss jeder Zeile eine
   Spalte zuweisen — eine Option „keine Zuordnung" existierte nicht. Ein schlechtes Paar konnte ein
   gutes verdrängen (`D1→T2` 0.95 + `D2→T1` 0.20 = 1.15 wird gegenüber `D1→T1` 0.10 + `D2→T2` 0.99
   = 1.09 gewählt); die nachgelagerte Filterung reparierte das nicht, weil die Matrix nicht neu
   gelöst wurde. Strukturell derselbe Fehler wie beim Greedy-Matching, das B374 beseitigt hat.

**Wirkung:** Die Kostenfunktion aus B373 bewertete korrekt, aber **ohne Konsequenz** — jedes nicht
gegatete Paar wurde akzeptiert. Besonders relevant nach B389, das den Suchraum für vektorlose
Tracks fast verdoppelte (7.62 → 14.50 km); die dortige Review-Note verwies auf `c_iou`/`c_area`/
`c_core` als Gegengewicht — was voraussetzt, dass die Kostenschwelle überhaupt wirkt.

**Fix:**
- `ASSOC_MAX_COST = 0.75` — erreichbar.
- Paare über der Schwelle werden **vor** Hungarian auf `_INF` gesetzt.
- Jede Detektion erhält eine **Dummy-Spalte** mit `ASSOC_UNMATCHED_COST = 0.80` (knapp über
  `MAX_COST`, damit ein akzeptables Paar immer vorgezogen wird). Der Solver bezieht die
  Nicht-Zuordnung damit **in die Optimierung ein**, statt sie nachträglich zu korrigieren.
- Neue Ablehnungsursache `no_acceptable_track` in der Diagnose, inkl. der besten verfügbaren
  Kosten.

**Kalibrierung:** `ASSOC_MAX_COST = 0.75` und `ASSOC_UNMATCHED_COST = 0.80` sind **nicht gegen
reale Daten kalibriert** — im Debug-Export vom 14.07.2026 existiert `train_data/association/`
noch nicht (erst ab B374). **Beim nächsten Konvektions-Debugexport gegen
`train_data/association/*.json` prüfen:** Verteilung von `cost` über akzeptierte Matches; häufen
sich `no_acceptable_track`-Ablehnungen bei real korrekten Zuordnungen, ist die Schwelle zu streng.

**Tests:** `tests/test_b400_hungarian_unmatched_option.py` — Schwelle liegt unter der maximal
möglichen Paarung, `UNMATCHED_COST > MAX_COST`, gutes Paar wird nicht verdrängt (Kernfall),
Solver darf Nicht-Zuordnung wählen, Ablehnungsgrund in der Diagnose, gute Paare matchen weiterhin,
alles gegatet, mehr Detektionen als Tracks und umgekehrt, Diagnosevollständigkeit, Leereingaben.

**Phasen-Status:** Phase A — die Kostenfunktion hat erstmals Wirkung.
**Offen:** Zeitbasis Polygon/Position P2-2, Mehrkern-Komponentengraph P2-4.

### B401 — Fallback-Zuordnung war Brute-Force und explodierte seit B400 kombinatorisch ✅ erledigt

**Root-Cause:** `_fallback_linear_sum_assignment()` löste das Zuordnungsproblem durch vollständige
Aufzählung (`itertools.combinations` × `itertools.permutations`) — **faktorielle** Laufzeit, obwohl
für das Problem seit 1955 ein `O(n³)`-Verfahren existiert.

**B400 machte den Defekt akut:** Die Dummy-Spalten erweitern die Matrix von `n_det × n_trk` auf
`n_det × (n_trk + n_det)`. Da `k = min(n_rows, n_cols)` weiterhin `n_det` ist, verdoppelt sich die
Basis der Permutation:

| Zellen | vor B400 | nach B400 | Faktor |
|---:|---:|---:|---:|
| 8 | 40.320 | **518.918.400** | 12.870× |
| 10 | 3.628.800 | 670.442.572.800 | 184.756× |

Bei der beobachteten Last von **7.78 Zellen je aktivem Frame** (Debug-Export 14.07.2026) sind das
≈ **17 Minuten pro Frame** auf dem Pi 5 — bei 5-Minuten-Radartakt ein **Totalausfall**, keine
Verlangsamung.

**Warum es unbemerkt blieb:** Der Pfad greift nur, wenn `scipy` fehlt. `scipy>=1.11.0` steht in
`requirements.txt` und ist in der Testsuite installiert — der Code wurde **nie ausgeführt**.
Schlägt der scipy-Import auf dem Pi einmal fehl (defektes venv nach `install.sh --mode=upgrade`,
ARM-Wheel-Problem), fällt das System stillschweigend auf einen Pfad zurück, der bei realer
Zellzahl nicht terminiert: kein Fehler, kein Log, nur ein hängender Radarzyklus.

**Korrektheit war nicht das Problem** — die Aufzählung lieferte das richtige Ergebnis (verifiziert
an einer rechteckigen 2×4-Matrix: `rows=[0,1] cols=[0,3]`, D1→T1 mit 0.10, D2→Dummy mit 0.80). Sie
war nur unbrauchbar langsam.

**Fix:** Hungarian/Kuhn-Munkres mit Potentialen, `O(n²m)` — derselbe Algorithmus wie
`scipy.optimize.linear_sum_assignment`. Bei 8×16 sind das ~1.000 Operationen statt 519 Millionen.
Für `n > m` wird transponiert (der Algorithmus setzt `n ≤ m` voraus; nach B400 ist das ohnehin
immer erfüllt). Rückgabe wie scipy: `(row_ind, col_ind)`, aufsteigend nach `row_ind`.

**Tests:** `tests/test_b401_fallback_hungarian.py` — Ergebnisgleichheit mit scipy auf quadratischen,
rechteckigen und 20 zufälligen Matrizen, konkreter B400-Dummy-Fall, mehr Zeilen als Spalten,
Eindeutigkeit der Zuordnung, **8×16 unter 1 s** (Kernregression), 12×24 terminiert, Leereingaben,
keine Brute-Force-Reste, `row_ind` sortiert.

**Phasen-Status:** Phase A — der scipy-freie Pfad ist erstmals produktionstauglich und getestet.
**Offen:** Zeitbasis Polygon/Position P2-2, Mehrkern-Komponentengraph P2-4.

### B402 — Polygon-Prädiktion unterstellte einen festen 5-Minuten-Takt, die Position nicht ✅ erledigt

**Root-Cause (P2-2):** Position und Geometrie desselben Tracks wurden auf **zwei verschiedene
Zeitpunkte** prädiziert und flossen gleichzeitig in dieselbe Kostenfunktion.

| Komponente | Quelle | Zeitbasis |
|---|---|---|
| `c_pos` | `predict_track_state()` (B374) | **echtes dt** |
| `c_iou` | `pred_polys` (`_dx_s = vx * UPSCALE_FACTOR`) | **immer 5 min** |

`vx`/`vy` sind Original-Pixel **pro Frame**; der Versatz entsprach damit implizit einem Frame.

**Folge:** Bei einer 15-min-Radarlücke und 60 km/h zieht die Zelle ~15 km, das prädizierte Polygon
nur ~5 km → kaum Überlappung → `c_iou` nahe 1.0, obwohl `c_pos` nahe 0 liegt. Mit
`ASSOC_W_IOU = 0.25` kostet das bis zu 0.25. **Seit B400 ist `ASSOC_MAX_COST = 0.75` erreichbar** —
ein korrekter Track kann dadurch allein wegen der falschen Polygon-Zeitbasis abgelehnt werden. Vor
B400 war die Schwelle wirkungslos und der Defekt folgenlos; B400 macht ihn **akut**. Betroffen sind
**schnelle Zellen bei Radarlücken** — der Fall, in dem Tracking-Kontinuität am wertvollsten ist.
Stehende Zellen (`_dx_s ≈ 0`) sind nicht betroffen.

**Kein B374-Versäumnis:** Die `pred_polys`-Berechnung liegt **vor** dem Assoziationsblock und
stammt aus der Zeit vor der globalen Zuordnung. Der Widerspruch entstand erst dadurch, dass beide
Größen jetzt in dieselbe Kostenfunktion fließen.

**Fix:** Neuer Faktor `_dt_frames = _dt_minutes / FRAME_INTERVAL_MIN` skaliert Polygonversatz **und**
prädizierten Schwerpunkt auf den tatsächlichen Zeitabstand. Bei 5 min ist der Faktor exakt 1.0 —
das Verhalten im Normalfall bleibt **bitgleich**. `_dt_minutes` wird dafür vor die
`pred_polys`-Schleife gezogen; `_tracking_dt_minutes()` schreibt `_last_tracking_timestamp` fort und
darf pro Lauf nur **einmal** aufgerufen werden (durch Test abgesichert). Neue Konstante
`FRAME_INTERVAL_MIN = 5.0` in `config.py`, konsistent zu `ASSOC_NORMAL_FRAME_MINUTES`.

**Tests:** `tests/test_b402_polygon_zeitbasis.py` — Konstanten konsistent, `_dt_minutes` steht vor
der Prädiktion, genau ein `_tracking_dt_minutes`-Aufruf, Versatz skaliert mit dt (5/10/15 min),
Normaltakt unverändert, schnelle Zelle überlebt 15-min-Lücke, statische Zelle unbeeinflusst,
`FRAME_INTERVAL_MIN` über runtime_config lesbar.

**Phasen-Status:** Phase A — Position und Geometrie teilen dieselbe Zeitbasis.
**Offen:** Mehrkern-Komponentengraph P2-4.

### B403 — Mehrkern-Split war „alles oder nichts": ein untrennbares Paar blockierte alle anderen ✅ erledigt

**Root-Cause (P2-4):** Die Split-Freigabe war eine **Konjunktion** über alle Kernpaare
(`eligible = _pairs_checked > 0 and _pairs_ok == _pairs_checked`). Ein einziges untrennbares Paar
setzte `eligible = False` und blockierte den gesamten Komplex.

**Fehlerfall:** Linie A━━B (durchgehend, kein Sattel) plus separate Zelle C. A–B nicht trennbar
(korrekt), A–C und B–C trennbar → `_pairs_ok=2`, `_pairs_checked=3` → **C wurde nicht abgespalten**,
obwohl es meteorologisch eindeutig eine eigene Zelle ist. In Kärnten der Regelfall bei Mischlagen:
elongierte Linie plus eigenständige, orografisch ausgelöste Zelle daneben.

**Herkunft:** Die Konjunktion stammt aus **B376** und war dort eine bewusste Verschärfung gegen den
Vorgängerzustand („ein einziges geeignetes Kernpaar gibt den gesamten Komplex frei", `break`/`break`).
Damit wurde ein zu weites ODER durch ein zu enges UND ersetzt — **beide Extreme betrachten die
Struktur nicht**. Die B376-Review-Note hatte genau darauf hingewiesen.

**Fix — Kernbeziehungen als Graph** (analog B370 für Konturen):
- Knoten = Kern; Kante „gehört zusammen" = kein ausreichender Sattel **und** keine Lücke;
  zusätzlich werden Kerne unter `MULTI_CORE_MIN_DIST_PX` zusammengefasst.
- Zusammenhangskomponenten via Union-Find (`_uf_find`/`_uf_union` aus B370 wiederverwendet).
- **1 Komponente** → kein Split (Böenlinie bleibt eine Zelle). **≥ 2 Komponenten** → Split.
- `_watershed_split()` erhält **einen Marker je Komponente** (flächenstärkster Kern als
  Repräsentant) statt je Kern — die Maxima derselben Linie dürfen nicht gegeneinander segmentiert
  werden.
- Ergebnis deterministisch (Komponenten nach kleinstem Kernindex sortiert).

`MULTI_CORE_MIN_SADDLE_RATIO` und `MULTI_CORE_MIN_GAP_PX` bleiben **unverändert** — die Schwellen
waren nicht das Problem, ihre Verknüpfung war es.

**Tests:** `tests/test_b403_kern_komponentengraph.py` — Linie+Zelle ergibt 2 Komponenten
{A,B}/{C} (Kernregression), Linienkerne bleiben zusammen, durchgehende Linie bleibt 1 Komponente
(B376-Regression), drei getrennte Kerne → 3 Komponenten, Kerne unter `MIN_DIST` verschmelzen,
Einzelkern, Leereingabe, Determinismus, Konjunktion entfernt, End-to-End 2 Sub-Konturen.

**Phasen-Status:** Phase A — **alle Findings des Codex-Reviews vom 14.07.2026 sind abgearbeitet**
(P0-1, P0-2, P1-1 … P1-7, P2-1 … P2-5).
**Nächster fachlicher Schritt:** Debug-Export der nächsten Konvektionslage. Zu prüfen:
`lineage="merged"` und `lineage="split"` treten auf (bisher 160/0), je Signatur genau **ein**
Ledger-Eintrag, `train_data/association/*.json` zur Kalibrierung von `ASSOC_MAX_COST` (0.75,
nicht gegen reale Daten kalibriert) und den Transition-Schwellen.

### B404 — B403-Testszene lag unter der produktiven Sattelschwelle ✅ erledigt

**Ausgangslage:** Der vollständige Raspberry-Pi-Testlauf nach B403 endete mit
`2012 passed, 3 failed, 1 skipped`. Fehlgeschlagen waren ausschließlich drei Tests in
`tests/test_b403_kern_komponentengraph.py`.

**Root-Cause:** Die synthetische Szene verwendete rote starke Bereiche und eine orange Brücke.
Laut produktiver `RADAR_DBZ_BANDS`-Skala besitzt Rot den Proxy `0.80`, Orange `0.55`.
Der tatsächliche Sattel war damit nur `1 - 0.55/0.80 = 0.3125` und lag unter
`MULTI_CORE_MIN_SADDLE_RATIO=0.35`. Da die Brücke Bestandteil der Zellmaske war, galt zusätzlich
`gap_px=0`. `_core_components()` ordnete deshalb A, B und C korrekt derselben Komponente zu.

**Fix:** Die starken Testbereiche verwenden nun das violette Radarband mit Proxy `1.00`.
Die unveränderte orange Brücke erzeugt damit einen Sattel von ungefähr `0.45`: A-B bleibt eine
durchgehende Komponente, C ist gegenüber A und B trennbar. Ein neuer Szenenvertrag prüft die drei
Sattelwerte und stellt sicher, dass keine geometrische Maskenlücke den Test künstlich erfüllt.

**Produktivcode:** unverändert. Keine Schwelle wurde abgesenkt.

**Tests:** `tests/test_b403_kern_komponentengraph.py`.

### B405 — q10/q90-Unsicherheitspunkte umgingen die ML-Dekodierung ✅ erledigt

**Root-Cause:** Der q10/q90-Zweig ignorierte `target_encoding` — als **einziger von drei Zweigen
desselben Codeblocks**:
- Zeile ~1697 Zentralwert: `_decode_ml_position(obj, _x_raw, _y_raw, _target_encoding)` ✓
- Zeile ~1690 ML-Schatten (P52): `_compute_ml_shadow(..., _target_encoding)` ✓
- Zeile 1745–1748 q10/q90: `float(prediction_q10[idx*2]) * _UF` ✗

Bei `target_encoding="delta"` liefert das Modell eine **Verschiebung** von wenigen Pixeln (P58).
Ohne die Addition von `obj["x"]/obj["y"]` wurde sie als **Absolutposition** gelesen → der Punkt landete
nahe dem Bildursprung, also am Rand des Radarbildes.

**Gemessen** (Export `2026-07-15_20-55-00`, Distanz vom Zellzentrum, Horizont 10 min):

| Zelle | Zentralwert | q10 | q90 |
|---|---:|---:|---:|
| E47G23ND | 3.4 km | **123.7 km** | **111.2 km** |
| H6B04FCG | 4.3 km | **151.1 km** | **138.2 km** |
| ZR1R2GLC | 3.3 km | **167.2 km** | **152.0 km** |
| DWSWZ7J7 | 4.9 km | **197.2 km** | **184.0 km** |

Der Zentralwert ist plausibel (3–5 km in 10 min ≈ 20–30 km/h), die Quantile lagen um **Faktor
30–40** daneben. Das ist nur mit `"delta"` erklärbar — bei `"absolute"` wäre die Zeile korrekt
gewesen.

**Wirkung:** Der Frontend-Korridor (B130) spannt aus q10/q90 ein Polygon auf — von der Zelle bis
~150 km. Sichtbar als magenta Band von ~100 km Länge quer über die Karte, dessen Achse mit der
Zellbewegung nichts zu tun hat (sie verbindet die Zelle mit einem Artefakt am Bildrand). Fachlich
suggerierte der Unsicherheitsbereich, die Zelle könne in **10 Minuten** irgendwo in einem
150-km-Band landen — schlechter als gar keine Anzeige.

**Warum unbemerkt:** Nur bei ML-Prognosen mit Quantilmodellen. Im kinematischen Fallback — dem
Normalfall der letzten Wochen — existieren q10/q90 nicht und `corridor` ist `null`. Erst mit aktivem
ML **und** realer Konvektion wurde es sichtbar; im Export vom 15.07. tragen genau die vier Zellen
mit `forecast_mode="ml"` q10/q90-Werte.

**Fix:** Beide Quantile laufen über `_decode_ml_position(obj, …, _target_encoding)` — dieselbe
Funktion, die Zentralwert und Schatten bereits nutzen. Kein Frontend-Eingriff nötig: Der
Korridor-Code (B130) ist korrekt und zeichnet nur, was er bekommt.

**Tests:** `tests/test_b405_quantil_dekodierung.py` — P58-Konvention für delta/absolute,
Fehlergröße belegt, manuelle `_UF`-Multiplikation entfernt, `target_encoding` an beide Quantile
durchgereicht, alle drei Zweige konsistent, Quantile bleiben beim Zentralwert.

**Phasen-Status:** Phase A — Unsicherheitskorridor zeigt wieder einen plausiblen Bereich.
**Verifikationspflicht:** Im nächsten Konvektions-Debugexport prüfen, dass
`forecast_lat/lon_{h}_q10/q90` in derselben Größenordnung wie `forecast_lat/lon_{h}` liegen
(Abweichung wenige km, nicht > 100 km). **`training_meta.json` fehlt im Debug-Export** — der Wert
von `target_encoding` ist daher nicht direkt belegbar, sondern aus der Fehlergröße erschlossen.
Die Aufnahme in den Export ist als eigener Punkt zu führen.

### B406 — Debug-Export verpackte seine eigenen Vorgänger; Assoziations-Diagnose fehlte ✅ erledigt

**Root-Cause:** Der Export enthielt die falschen Daten — seine eigenen Vorgänger statt der
Diagnose, für die er gebaut wurde. Ursache: `_iter_files()` (Zeile 282–288) sammelt jedes
Verzeichnis rekursiv **ohne jeden Ausschluss**.

**Ausprägung 1 — Rekursion:** `_latest_export_base_dir()` legt die fertigen Export-ZIPs unter
`train_data/evaluation/latest_export/` ab; Zeile 325 exportiert das gesamte
`evaluation`-Verzeichnis. **Jeder Export verpackte damit die ZIPs des vorherigen Laufs.** Belegt
am Export `2026-07-16_04-58-40` (3 Teile, 56–81 MB): Er enthielt
`evaluation/train_data/evaluation/latest_export/wetterextended_debug2.zip` und `…3.zip` — darin
der **vollständige Export vom 15.07.**, inkl. 316 MB `external_responses`. Folgen: aufgeblähtes
Übertragungsvolumen über den Mobilfunk des Pi; beim Entpacken mehrerer Teile überlagern **alte
Daten die neuen**, sodass eine Auswertung unbemerkt auf den Vortag zugreift.

**Ausprägung 2 — fehlende Diagnose:** `train_data/association` steht seit B374 in der Exportliste
und wird von `object_tracking.py:1545` befüllt — im Export vom 16.07. dennoch **0 Dateien**
(geprüft in allen drei Teilen und in den verschachtelten Archiven). Damit ist
`ASSOC_MAX_COST` (B400, Default 0.75) **nicht kalibrierbar** — die einzige Schwelle, die aktiv
Matches verwirft.

**Fix:**
- `_EXPORT_EXCLUDE_DIRS = {"latest_export"}` und `_EXPORT_EXCLUDE_SUFFIXES = {".zip"}`:
  Ein Debug-Archiv enthält nie ein anderes Archiv. `_iter_files()` filtert beide Fälle.
- `_diagnosis_presence_report()`: unterscheidet `missing` / `empty` / `stale` / `ok` samt
  aufgelöstem Pfad. Ein leeres Diagnoseverzeichnis ist sonst nicht von einem fehlerhaften Export
  zu unterscheiden — beides ergibt „0 Dateien". Das stille Fehlen ist besonders teuer: Es fällt
  erst auf, wenn die Kalibrierung ansteht, also nach der nächsten Konvektionslage.
- `diagnostics/diagnosis_presence.json` wird beim Export geschrieben und zusätzlich im Manifest
  gespiegelt, damit fehlende oder veraltete Diagnosequellen nicht mehr still untergehen.

**Neu: `AIChecks.md` im Project Root — ab sofort verbindlich.** Jeder Prompt trägt seine offenen
Prüfungen dort ein; erledigte Punkte werden mit Datum und Ergebnis abgeschlossen statt gelöscht.
Initial befüllt mit AC-001 bis AC-009 (Assoziations-Diagnose, `ASSOC_MAX_COST`,
Transition-Schwellen, instabile Quellen-Rangfolge, Sattel-Schwelle, `lineage="split"`,
Ledger-Eindeutigkeit, weitere `_UF`-Stellen, `training_meta.json`).

**Tests:** `tests/test_b406_export_ohne_eigene_ausgaben.py` — ZIPs und `latest_export`
ausgeschlossen, normale Dateien nicht, `_iter_files` überspringt eigene Exports,
Diagnose-Report erkennt `missing`/`empty`/`ok`, Exporteintrag erhalten, `AIChecks.md` vorhanden.

**Phasen-Status:** Phase A — der Export ist wieder eindeutig datierbar und meldet fehlende
Diagnosen. **Nach dem nächsten Export prüfen:** `diagnostics/train_data/association/*.json`
vorhanden? Falls `status="empty"` → die Diagnose wird nicht geschrieben (AC-001); falls
`status="ok"` → Kalibrierung von `ASSOC_MAX_COST` möglich (AC-002).

### B407 — Pauschaler `.zip`-Ausschluss verwarf legitime Nutzdaten; AIChecks.md dokumentierte statt anzuweisen ✅ erledigt

**Root-Cause:** B406 hat die Rekursion mit einem zu breiten Mittel bekämpft. Sie entsteht
ausschließlich dadurch, dass `_latest_export_base_dir()` die eigenen Export-ZIPs unter
`train_data/evaluation/latest_export/` ablegt und die Exportliste das gesamte
`evaluation`-Verzeichnis mitnimmt — `_EXPORT_EXCLUDE_DIRS = {"latest_export"}` deckt das
**vollständig** ab.

Der zusätzliche `_EXPORT_EXCLUDE_SUFFIXES = {".zip"}` griff dagegen **projektweit** und verwarf
jedes `.zip` an jeder Stelle, auch legitime Nutzdaten (z. B. heruntergeladene Archive unter
`external_responses`), die für die Fehlersuche wertvoll sind und mit der Rekursion nichts zu tun
haben. Der Kommentar begründete ihn mit „ein Debug-Archiv darf kein anderes Archiv enthalten" —
das ist die Symptombeschreibung, nicht die Ursache.

**Fix:** `_EXPORT_EXCLUDE_SUFFIXES` ersatzlos entfernt; `_is_excluded_from_export()` prüft nur noch
den Verzeichnisausschluss. Tests entsprechend geschärft: eigenes Export-ZIP bleibt gefiltert,
Fremd-ZIP wird exportiert.

**Zweiter Teil — `AIChecks.md`:** Die Datei war als Befundsammlung angelegt (99 Zeilen mit Belegen,
Messtabellen, Herleitungen) und doppelte damit den Changelog. Sie enthält jetzt **ausschließlich
Arbeitsanweisungen**: imperativ, ausführbar, jede mit konkreter Datenquelle, ohne Herleitung. Der
Grund einer Anweisung steht im Changelog, hier steht nur der Auftrag. AC-001 bis AC-010 neu
formuliert (Diagnose-Präsenz, `ASSOC_MAX_COST`, Transition-Schwellen, Quellen-Rangfolge über
mehrere Lagen, Sattel-Schwelle, Split-Auftreten, Ledger-Eindeutigkeit, `_UF`-Stellen,
`training_meta.json`, Fremdarchive im Export).

**Tests:** `tests/test_b407_aichecks_arbeitsanweisungen.py` — Zweck deklariert, keine
Messtabellen/Befunde, alle Einträge imperativ, jede Anweisung mit Datenquelle, eigenes Export-ZIP
gefiltert, Fremd-ZIP erhalten, Suffix-Filter entfernt, `_EXPORT_EXCLUDE_DIRS` unverändert.

**Phasen-Status:** Phase A — Export filtert gezielt, AIChecks.md ist handlungsleitend.

### B408 — Hydro-Catchment-Flood-Forecast repariert ✅ erledigt

**Root-Cause:** Der Hydro-Flood-Pfad war nicht durchgängig an reale Einzugsgebiete, Messzeitpunkte und ML-Trainingsdaten gekoppelt; dadurch konnten Catchment-Niederschlag, Durchflusslabels und öffentliche Warnwerte nicht belastbar aus den vorhandenen Hydro- und Zellinformationen abgeleitet werden.

**Fix:** `hydro_flood_ml.py` wurde breit erweitert: Feature-Aufbau, Niederschlagsaggregation, History-/Dataset-Erzeugung, Heuristik und Training wurden mit Catchment- und Q-Zielgrößen verbunden. `hydro_impact.py` liefert Catchment-Index und Attribution, `hydro_fetch.py` erhält robustere Hydro-Zeitdaten, `config.py` und `debug_export.py` ergänzen Hydro-Konfiguration und Exportdaten. Zusätzlich wurden `frontend/src/utils/hydroFloodPopup.js`, `docs/HYDRO_IMPACT_PEGEL_ATTRIBUTION.md`, `docs/WetterExtended_Benutzerhandbuch.md` und der damals noch root-seitige `HAILO_INTEGRATION.md` angepasst.

**Tests:** `tests/test_b408_hydro_catchment_precip_pipeline.py` prüft Catchment-Niederschlag und Pipeline-Zusammenhang, `tests/test_b408_hydro_ml_samples.py` die ML-Sample-Erzeugung, `tests/test_b408_hydro_multi_cell_dwell_q.py` die Mehrzellen-/Dwell-/Q-Aggregation.

**Phasen-Status:** Phase A — Hydro-Flood-ML ist als datengetriebener Fallback-Pfad vorbereitet, aber nicht als promotetes Modell belegt. Phase B (Hailo-8 U-Net) bleibt blockiert.

### B409 — Hydro-Flood-Produktionspfad gehärtet ✅ erledigt

**Root-Cause:** Der B408-Pfad war für Produktion noch zu weich: Zellfilterung, Shapely-Geometriepfad, Routing, Dataset-Integrität, Runtime-Konfiguration, ML-Inferenz und Frontend-Warnanzeige waren nicht ausreichend abgesichert.

**Fix:** `hydro_flood_ml.py` wurde um produktionsnähere Zell-/Geometrie-, Routing-, Dataset- und Inferenzlogik erweitert; `config.py` und `runtime_config.py` erhielten zugehörige Parameter; `frontend/src/pages/MapView.jsx`, `frontend/src/pages/MapFullscreen.jsx` und `frontend/src/utils/__tests__/hydroFloodPopup.test.mjs` deckten die Warnanzeige ab.

**Tests:** `tests/test_b409_hydro_cell_filtering.py` prüft Zellfilterung, `tests/test_b409_hydro_dataset_integrity.py` Dataset-Labels und damalige JSONL-Annahmen, `tests/test_b409_hydro_ml_inference.py` ML-Inferenz, `tests/test_b409_hydro_routing.py` Routing-Effekte, `tests/test_b409_hydro_shapely_production_path.py` den Shapely-Produktionspfad. Die gemeldete Verifikation „Shapely-Test grün und nicht geskippt" traf nicht zu: `tests/test_b409_hydro_routing.py` und `tests/test_b409_hydro_shapely_production_path.py` scheiterten bis B412 an einem `AttributeError`, bevor eine Assertion lief. Der Shapely-Produktionspfad war von B409 bis B412 ungetestet; die Reparatur erfolgt in B412.

**Phasen-Status:** Phase A — Hydro-Flood läuft weiterhin im kinematischen bzw. physikalischen Fallback; ML ist nicht promotet. Phase B (Hailo-8 U-Net) bleibt blockiert.

### B410 — Hydro-Flood-Produktionspipeline gehärtet ✅ erledigt

**Root-Cause:** Nach B409 fehlten weitere Produktionsgarantien für Frische der Zellframes, Provenienz, Feature-Snapshots, Modellpromotion, öffentliche Payloads, Readiness, Routing-Zeitlinie und Sample-Store.

**Fix:** `hydro_flood_ml.py` wurde erneut deutlich erweitert: Frische- und Provenienzbewertung, Feature-Snapshot-Verwaltung, Readiness, Routing-Zeitleiste, Sample-Store und Modellpromotion wurden gehärtet. `app.py`, `config.py`, `hydro_fetch.py`, `frontend/src/utils/hydro.js`, `frontend/src/utils/hydroFloodPopup.js`, `frontend/src/pages/MapView.jsx`, `frontend/src/pages/MapFullscreen.jsx` und Frontend-Response-Tests wurden passend angepasst.

**Tests:** `tests/test_b410_hydro_cell_frame_freshness.py`, `tests/test_b410_hydro_dataset_provenance.py`, `tests/test_b410_hydro_feature_snapshot.py`, `tests/test_b410_hydro_model_promotion.py`, `tests/test_b410_hydro_public_payload.py`, `tests/test_b410_hydro_readiness.py`, `tests/test_b410_hydro_routing_timeline.py` und `tests/test_b410_hydro_sample_store.py` prüfen die genannten Pipeline-Garantien; `tests/test_b409_hydro_shapely_production_path.py` wurde ebenfalls berührt.

**Phasen-Status:** Phase A — Hydro-Flood bleibt im Fallback-Betrieb mit gehärteter Produktionspipeline; ML ist nicht promotet. Phase B (Hailo-8 U-Net) bleibt blockiert.

### B411 — Hydro-Flood-SQLite und Härtungslücken geschlossen ✅ erledigt

**Root-Cause:** Der produktive Sample-Store und mehrere Randbedingungen waren noch nicht robust genug: SQLite musste Source of Truth werden, Pending-Migration, Retention, optionale Features, Modellintegrität, Event-Split, atomare Fetches, Deferred-Q-Refresh und Debug-Zugriff brauchten Absicherung.

**Fix:** `hydro_flood_ml.py` machte SQLite zum produktiven Sample-Store und ergänzte Migration, Retention, Export-Snapshot, Readiness und Modellintegritätslogik. `app.py`, `hydro_fetch.py`, `config.py` und `runtime_config.py` wurden für Zugriff, atomare Schreibpfade und Konfiguration angepasst.

**Tests:** `tests/test_b411_hydro_debug_access.py`, `tests/test_b411_hydro_deferred_q_refresh.py`, `tests/test_b411_hydro_effective_overlap_time.py`, `tests/test_b411_hydro_event_split.py`, `tests/test_b411_hydro_fetch_atomic_write.py`, `tests/test_b411_hydro_model_integrity.py`, `tests/test_b411_hydro_optional_features.py`, `tests/test_b411_hydro_pending_migration.py`, `tests/test_b411_hydro_retention.py` und `tests/test_b411_hydro_sqlite_source_of_truth.py` prüfen die jeweiligen Härtungen; insbesondere belegt `test_b411_hydro_sqlite_source_of_truth.py`, dass Readiness aus SQLite und nicht aus einem defekten JSONL-Snapshot gelesen wird.

**Phasen-Status:** Phase A — Hydro-Flood-ML ist im kinematischen bzw. physikalischen Fallback, produktive Samples liegen in SQLite, ML ist nicht promotet. Phase B (Hailo-8 U-Net) bleibt unverändert blockiert.

### B412 — Hydro-Testverifizierbarkeit wiederhergestellt ✅ erledigt

**Root-Cause:** Die B409/B410-Shapely-Produktionspfadtests konnten vor ihren Fachassertions an einem Test-Importfehler scheitern; dadurch war die grüne Suite als Belegstelle nicht belastbar.

**Fix:** Die Tests wurden so repariert, dass sie den realen Produktionspfad ausführen und Attribute-/Importfehler nicht mehr verdecken.

**Tests:** `tests/test_b409_hydro_shapely_production_path.py`, `tests/test_b410_hydro_public_payload.py`, `tests/test_b410_hydro_cell_frame_freshness.py` und die Hydro-Flood-Basissuite belegen die wiederhergestellte Verifizierbarkeit.

**Phasen-Status:** Phase A — Hydro-Flood-Tests sind wieder als Produktionspfad-Nachweis nutzbar. Phase B (Hailo-8 U-Net) bleibt unverändert blockiert.

### B413 — Prognose-Gates unterdrückten die gemessene Grenzwertüberschreitung ✅ erledigt

**Root-Cause:** Die aktuelle Q-Messung einer Pegelstation wurde an vier Stellen wie ein Forecast-Ergebnis behandelt: `heuristic_score()` brach bei Geometrie-Gates vor der Grenzwertprüfung ab, `refresh_hydro_fields_in_cached_risk()` übernahm alte Forecast-Warnfelder trotz stale Zellframe, `hydro_fetch.py` bewertete einen fehlenden Zellframe ohne Cache als frische leere Zellliste, und `_public_flood_row()` filterte `current_q_above_threshold` aus dem Public-Payload heraus.

**Fix:** Die Grenzwertprüfung läuft nun vor allen Geometrie-/Forecast-Gates und trägt gemessene Überschreitungen unabhängig von Catchment, Zellframe und Niederschlagsprognose. Deferred-Refresh ersetzt alte Forecast-Gründe, setzt veraltete Prognosewerte nur noch als `stale_*`-Diagnose fort und setzt `predicted_q_max_m3s` auf `None`. `build_deferred_public_risk()` erzeugt für `missing`, `stale`, `invalid` und `error` zentral einen Public-Payload mit frischen Hydro-Q-Werten; `invalid` und `error` bleiben getrennte Status. Das Frontend nutzt die normalisierte Warnbedingung: aktive Warnung nur bei aktueller Q-Überschreitung oder frischem bewertbarem Forecast.

**Tests:** Ergänzt wurden `tests/test_b413_hydro_measured_threshold_wins.py`, `tests/test_b413_hydro_deferred_warning_state.py`, `tests/test_b413_hydro_missing_frame_without_cache.py`, `tests/test_b413_hydro_public_threshold_field.py` und `frontend/src/utils/__tests__/hydroFloodStale.test.mjs`. Zusätzlich laufen die Hydro-Flood-, Public-Payload-, Cell-Frame-, P67-Kartenkonsistenz- und Frontend-Build-Prüfungen.

**Phasen-Status:** Phase A — Hydro-Flood meldet gemessene Überschreitungen unabhängig von der Prognosekette. Phase B (Hailo-8 U-Net) bleibt unverändert blockiert.

### B414 — Testzellen ohne ID; Identitätsprüfung nach B413 ✅ erledigt

- **Root-Cause:** `is_hydro_relevant_cell()` verwirft ID-lose Zellen; die Testzellen trugen keine ID. Das war ein Testfehler, kein Produktionsbug: `load_latest_cell_frame()` filtert solche Zellen bereits, sodass der Produktivpfad sie nie sieht.
- **Fix:** Die Testzellen tragen nun IDs, die Konstantenassertion wurde durch einen relationalen Vergleich ersetzt, und `test_b271` prüft die übergebenen Daten statt zufälliger Objektidentität. Ein zusätzlicher Regressionstest belegt für Fetches mit und ohne Zellframe, dass der öffentliche Risk-Cache geschrieben wird und im Deferred-Fall frisches Q sowie `forecast_evaluation_stale=true` enthält. Dabei wurde ein echter Randfall behoben: Beim Aktualisieren eines älteren Cache-Dokuments erzwingt der Deferred-Builder nun `payload_scope="public"`.
- **Befund, nicht behoben:** Der Test patcht `catchment_area_geometry_km2 = 1` für ein ungefähr 124 km² großes Polygon. Da die Niederschlagsformel durch diese Fläche teilt, würde jede Konstantenassertion auf `effective_catchment_precip_sum_mm` eine falsch parametrierte Testumgebung prüfen.
- **Einordnung der 25 Tracking-/Frontend-Fehler:** Die stichprobenartigen Sandbox-Läufe werden als Umgebungsartefakt oder neuer Befund dokumentiert; Tracking-Code wird in B414 nicht geändert.
- **Einordnung B412:** B412 hat den Test korrekt auf den echten Shapely-Pfad umgestellt und dadurch den Befund sichtbar gemacht. Diese Aufklärung war die vorgesehene Arbeitsteilung und kein Versäumnis.

**Phasen-Status:** Phase A — Hydro-Testsuite aussagekräftig. Phase B (Hailo-8 U-Net) unverändert blockiert.

### B415 — Integritätsprüfung heilte sich selbst; Modellhash lief pro Station ✅ erledigt

**Root-Cause:** `model_signature()` vermischte die häufige Cache-Invalidierung mit der kryptografischen Integritätsprüfung. Dadurch wurden Modell und Metadaten pro Station vollständig gehasht; zugleich ersetzte die `promoted`-Ausnahme bei einer Metadatenabweichung den erwarteten Hash im Speicher durch den tatsächlichen Hash und heilte die Prüfung selbst.

**Fix:** `model_stat_signature()` liefert ausschließlich den Stat-Key einschließlich Inode, Modell-, Metadaten- und Manifest-Zeit/Größe. `model_integrity_signature()` berechnet die drei SHA256-Werte nur bei Cache-Miss, erzwungenem Reload, Promotion oder gezielter Diagnose. Die `promoted`-Ausnahme ist entfernt, Modell- und Metadatenabweichungen besitzen getrennte Kennungen, alle acht Manifestfelder werden geprüft und nach der Deserialisierung läuft eine endliche Probeinferenz mit den vorhandenen Imputationswerten beziehungsweise Feature-Defaults. `evaluate_live_flood_risk()` lädt einen Modellkontext vor der Stationsschleife und reicht ihn weiter.

**Tests:** Die B415-Integritätstests manipulieren Modell, promotete und nicht promotete Metadaten, Manifest und Schema, prüfen unbekannte Manifestversionen, nicht endliche Probeausgaben, den gültigen ML-Pfad und das unveränderte Manifest. Der I/O-Test belegt bei 80 synthetischen Stationen höchstens drei Hashaufrufe und genau eine Deserialisierung; der zweite Lauf erzeugt null Hashaufrufe. Touch und gleich großer Verzeichnistausch prüfen Stat-Key und Inode. Die Sandbox-Nachhermessung dauerte 0,018 s bei 0 verfügbaren Stationen; eine belastbare Vorher-/Nachhermessung war ohne Raspberry-Pi-Datenbestand nicht möglich und muss deshalb bei der verbindlichen Pi-Abnahme mit dem dokumentierten Messbefehl ergänzt werden.

**Phasen-Status:** Phase A — Modellartefakte sind manipulationsfest, die Stationsschleife ist I/O-frei. Phase B (Hailo-8 U-Net) unverändert blockiert.

### B416 — Samples ohne Zellbezug: Eventerkennung und Validierung liefen ins Leere ✅ erledigt

**Root-Cause:** `record_pending_samples()` ließ Zell- und Lineage-IDs sowie den expliziten
Niederschlagszustand aus dem Pending-Payload weg. Dadurch sah die nachgelagerte
Eventerkennung keine Zellstruktur, der Split wurde stationsweise statt chronologisch,
Readiness zählte noch nicht vergebene Event-IDs und unvollständige Snapshots konnten
trainierbar erscheinen.

**Fix:** Der Produktivpfad übernimmt ausschließlich kompakte Identitätsfelder aus der
Zelldiagnose, speichert deduplizierte Zell-/Lineage-Listen, Zähler sowie getrennte
`precip_event_active`- und `precip_event_evaluable`-Flags. Die zentrale Validierung
prüft Snapshot, Schemahash, Pflichtwerte, Flags, Ziel, Station und Zeit. Die gemeinsame
Dataset-Analyse erzeugt deterministische Events, sortiert sie global chronologisch und
teilt ganze Events zeitlich. Die Schemaversion ist `b416_live_catchment_v4`; im
vorliegenden Checkout entfallen 0 Altsamples, weil keine produktive Sample-Datenbank
vorlag. In einer Pi-Installation werden alle v3-Zeilen mit
`schema_version_superseded_b415` nach `sample_failures` verschoben.

**Tests:** B416 ergänzt Validierungs-, Payload-Integrations-, Chronologie- und
Readiness-Regressionstests; Compile-, Hydro-Zielsuite, Gesamtsuite und Frontend-Build
sind Bestandteil der Abnahme.

**Phasen-Status:** Phase A — die ML-Reaktivierung bleibt blockiert und der kompatible
Datensatz beginnt mit B416 neu. Bei aktiver Gewitterlage werden voraussichtlich zwei
bis sechs Wochen benötigt, weil nur voneinander unabhängige Regenereignisse zählen.
Phase B (Hailo-8 U-Net) bleibt unverändert blockiert.

### B417 — Readiness lud den gesamten Datensatz; Training blockierte den Webserver ✅ erledigt

**Root-Cause:** Statusfragen und Datensatzarbeit nutzten denselben synchronen Pfad:
Readiness deserialisierte alle Samples und startete Migrationen; Training blockierte
den Flask-Worker. **Fix:** Readiness nutzt gecachte SQL-Aggregate, Pending-Zeilen und
Q-Historie sind begrenzt in SQLite abgefragt, und Training läuft mit sichtbarem Status
im Hintergrund unter einem nicht blockierenden Cross-Process-`flock`. Die
Admin-Endpunkte waren bereits durch den zentralen `before_request`-Präfixschutz
geschützt. `@require_role("admin")` ist Defense-in-Depth und schließt keine zuvor
offene Sicherheitslücke. Sandbox-Leermessung: 0 Samples; belastbare RAM- und
Laufzeitwerte sind auf dem Raspberry Pi mit Produktivdaten zu erheben.

**Tests:** Compile-, Lock-, SQL-, Migrations-, Maintenance-, Sampling-, Auth- und
Frontend-Prüfungen gehören zur B417-Abnahme.

**Phasen-Status:** Phase A — der Hydro-ML-Pfad ist Pi-tauglich. Phase B (Hailo-8 U-Net)
unverändert blockiert.

### B418 — Negatives Trainingsziel gegen geklemmte Inferenz; gemessener Niederschlag ohne Prognosewirkung ✅ erledigt

**Root-Cause:** Target und Featurebasis waren nicht gegen den Inferenzpfad geführt: Das Training erhielt negative Q-Delta-Targets, obwohl die Inferenz auf `>= 0` klemmt; zugleich blieb ein bereits normalisiertes `observed_precip` außerhalb der physikalischen Prognose und der kanonischen Features.

Die neue Targetdefinition lautet wörtlich: `target_future_q_max_m3s = max(Q im Lag-Fenster)`, `target_window_q_max_m3s = max(Start-Q, target_future_q_max_m3s)` und `target_q_delta_m3s = target_window_q_max_m3s - Start-Q`. `target_q_change_end_m3s = Q am Ende des Fensters - Start-Q` bleibt ein ausschließlich diagnostisches, nicht trainiertes Rezessions-Target. Die produktive Migration `b418_target_definition_v1` labelt v4-Samples aus der SQLite-`q_history` neu; ohne verfügbares Fenster bleiben sie in `sample_failures` mit `target_definition_superseded_b418_history_unavailable`. Im vorliegenden Checkout waren 0 produktive Samples neu zu labeln und 0 zu verschieben.

Ein normalisiertes Messobjekt wird nur bei `quality=high`, bekanntem positiven `measurement_window_min`, nichtnegativem Alter innerhalb des Lag-Fensters und bekannter Einzugsgebietsfläche verwendet. Die gemeinsame Rational-Methode nutzt `HYDRO_FORECAST_RUNOFF_COEFF`; Mess- und Zellvolumen werden getrennt ausgewiesen, bevor sie addiert werden. Ablehnungen sind über `observed_precip_rejection_reason`, Zeitlücke und Überlappung explizit sichtbar. Die Schemaversion ist `b418_live_catchment_v5`.

**API-Prüfung:** Im vorliegenden Repository existiert kein Adapter, der `observed_precip` aus einer dokumentierten Fremd-API erzeugt; auffindbar ist nur der interne normalisierte Objektvertrag. Daher gibt es keine belastbare externe Belegstelle für Einheit, Fenster, Bedeutung von `high` oder Mess-/Abrufzeit. `high` ist eine Projektklassifikation. Ohne explizites `measurement_window_min` wird die Messung mit `observed_precip_measurement_window_missing` abgelehnt; ein neuer Fremdrequest wurde nicht eingeführt. Dieser Provenienzbefund muss vor Anbindung einer realen Quelle geschlossen werden.

Die B418-Target-, Forcing-, Volumenbilanz- und Migrationsregressionen wurden ergänzt. **Phasen-Status:** Phase A — Trainingsziel und Inferenz sind konsistent; die Prognose kann fachlich vollständig normalisierte gemessene Niederschläge nutzen. ML-Reaktivierung bleibt von der Datensammlung abhängig. Phase B (Hailo-8 U-Net) bleibt unverändert blockiert.

### B419 — write=False lieferte interne Payloads; Debug-Export kopierte eine laufende WAL-Datenbank ✅ erledigt

**Root-Cause:** Inhalt und Vorgang waren nicht getrennt: `write=False` schaltete neben
der Persistenz unbeabsichtigt den internen Payload frei, während der Export eine sich
ändernde WAL-Datenbank wie eine gewöhnliche Datei behandelte.

**Fix:** Nur `include_debug` bestimmt nun den Payload-Inhalt; `write` bestimmt nur die
Persistenz. `diagnose_station()` beruhte nachweislich auf dem `not write`-Fehler, weil
es `cell_diagnostics` aus dem dadurch unbeabsichtigt vollständigen Stationsobjekt las,
und fordert diese Daten jetzt ausdrücklich mit `include_debug=True` an. Admin-Diagnosen
tragen `payload_scope="admin_diagnostics"` und Schema `b419_admin_diagnostics_v1`;
ein unklassifizierter Cache wird abgewiesen. Der öffentliche Allowlist-Payload entfernt
14 Modell-, Flächen- und Volumen-Zwischenwerte. Im synthetischen 50-Stations-Vergleich
sank er von 41.964 auf 16.714 Bytes (die Testzeile enthielt 10 tatsächlich gesetzte
öffentliche Felder).

Der Debug-Export erstellt mit `sqlite3.Connection.backup()` in einem temporären,
außerhalb von `train_data/hydro/ml` liegenden Verzeichnis einen konsistenten Snapshot,
exportiert Status, Migrationen und Begleitartefakte und löscht das Verzeichnis bei
Erfolg wie bei Fehler. Die Live-Datenbank sowie WAL/SHM-Dateien sind ausgeschlossen;
Backup- und Größenfehler werden ausdrücklich im Manifest vermerkt.

**Befund zum BBox-Zweig:** Der Zweig ist nicht tot: `_precip_from_cells()` setzt im
vereinfachten Geometriepfad `geometry_quality="bbox_fallback"`, während der echte
Shapely-Pfad `"shapely"` setzt. Er wurde geprüft und nicht entfernt. Bei leerer
Zellliste liefern sowohl Ergebnis als auch Feature-Snapshot die effektive,
räumlich deduplizierte `overlap_area_time_km2_min` konsistent als `0.0`.

**Phasen-Status:** Phase A — der öffentliche Payload ist kompakt und frei von internen
Daten; der Debug-Export liefert einen konsistenten Datenbankstand. Damit ist die
Hydro-Flood-Serie B412–B419 abgeschlossen. Phase B (Hailo-8 U-Net) unverändert
blockiert; sie wartet weiterhin auf ausreichende Trainingsdaten.

### B420 — Cache-Validierung, Startup-Migration und Trainingslock griffen nicht ✅ erledigt

**Root-Cause:** Alle drei Befunde stammen aus dem automatischen Codex-Review zu PR
#1049 und #1052 und waren in B414 beziehungsweise B417 bereits als Anforderungen
formuliert, aber unvollständig umgesetzt: Der Cache-Hash kannte den Zellframe-Zustand
nicht, die Startup-Migration lief ausschließlich im 03:35-Cronjob, und der
Cross-Process-Lock wurde vor der geschützten Arbeit wieder freigegeben. Damit waren
insbesondere B417 Punkt 5 („zweiter Start → 409") und Punkt 22 („Migrationen
automatisch einmalig") nicht erfüllt.

**Fix:** Der Cache-Hash enthält jetzt Zellframe-Status, -Zeitstempel und rohe
Zellanzahl, nicht aber das laufend alternde `frame_age_min`. Die idempotenten
Migrationen laufen beim Aufbau des Schedulers vor dem ersten Verify-Job; der
Materialisierer stößt sie ohne Scheduler ersatzweise an. Ein offenes `flock`-Handle
wird an den Trainingsworker übergeben und dort erst nach Training oder Fehler
freigegeben. Der Worker reicht dasselbe Handle reentrant an `train_model()` weiter.
Der atomar geschriebene JSON-Status unter `train_data/hydro/ml` ist in allen Prozessen
sichtbar; ein freier Lock bei `running=true` wird als `worker_vanished` korrigiert.

**Tests:** Regressionen decken Frame-Erholung und stabile Frame-Alterung,
idempotente und ersatzweise Startup-Migration sowie Lock-Übergabe,
prozessübergreifende Exklusivität, Worker-Abschluss und fehlgeschlagenen Threadstart
ab.

**Phasen-Status:** Phase A — die Schutzmechanismen greifen. Phase B (Hailo-8 U-Net)
unverändert blockiert.

### B421 — event_id-Spalte blieb leer; Readiness meldete dauerhaft fallback ✅ erledigt

**Root-Cause und Herkunft:** Das Codex-Review stellte fest, dass B416 zwar die
denormalisierte `event_id`-Spalte für billige SQL-Aggregate eingeführt hatte,
`materialize_pending_samples()` sie im Produktivpfad aber nie füllte. B416-
Abnahmekriterium 20 („Readiness zählt Events ohne vorhandene `event_id` korrekt") war
damit nicht erfüllt. Die ML-Reaktivierung war seit B416 strukturell blockiert — nicht
wegen fehlender Daten, sondern wegen einer leeren Spalte. Im Entwicklungs-Checkout
waren vor dem Fix 0 Labels, 0 NULL-IDs und 0 verschiedene Events vorhanden; belastbare
Vorher-/Nachher-Zahlen auf dem Pi stehen deshalb bei der Live-Abnahme aus.

**Inkrementelle Vergaberegel:** Kein Vorgänger → neues Event; Datenlücke größer als
`HYDRO_EVENT_GAP_MIN` → neues Event; Trockenphase größer/gleich
`HYDRO_EVENT_DRY_GAP_MIN` → neues Event; leere Lineage-Schnittmenge mit dem Vorgänger
bei aktivem Niederschlag in beiden Samples → neues Event; andernfalls wird die
`event_id` des Vorgängers übernommen. Die stabile ID wird aus Station,
`event_start_time` des ersten Samples und SHA-256 des sortierten Lineage-Sets gebildet;
`event_start_time` wird innerhalb des Events vom Vorgänger übernommen. Spalte und
Payload werden gemeinsam geschrieben.

**Bewusste Schichtung:** Die Spalte `event_id` ist die inkrementelle Schätzung für
billige Readiness-Aggregate und kann bei verspätet migrierten Samples vorübergehend von
der Trainingsgruppierung abweichen. `_assign_event_ids()` und
`analyze_training_dataset()` bleiben für Training und Split maßgeblich. Nach jedem
Trainingsversuch werden deren IDs in Spalte und Payload zurückgeschrieben; der um
`COUNT(DISTINCT event_id)` erweiterte Cache-Key erkennt diese Nachführung. Die unter
dem Trainingslock laufende, idempotente und nach
`HYDRO_ML_MATERIALIZE_BATCH_SIZE` gebatchte Migration
`migrate_assign_event_ids_b421` trägt bestehende NULL-Werte nach. Ist B420 beim
Upgrade noch nicht angewendet, greift sie erst beim nächsten Cronlauf.

**Phasenstand:** Phase A misst wieder; `event_count` beträgt im leeren
Entwicklungs-Checkout 0 und muss auf dem Pi nach der Migration live erhoben werden.
Phase B (Hailo-8 U-Net) bleibt unverändert blockiert.
