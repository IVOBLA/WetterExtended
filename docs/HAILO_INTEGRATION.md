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
| **B — Hailo + U-Net** | Linux-Rechner anschaffen, Training auslagern, DFC-Pipeline, U-Net, Hailo-Integration | 6–8 Wochen | Pi 5 + Linux-Rechner | ⏳ Offen (wartet auf Linux-Rechner) |
| **C — Skalierung** | Optimierungen, weitere Modelle, KI-Analyse vertiefen, Bugfixes B10–B12 | bei Bedarf | Pi 5 + Linux-Rechner | ⏳ Offen |
| **E — IR-Sat Pre-Convection Tracking** | Hohe Wolken (BT < 230 K) aus EUMETView IR108 als eigenständige Objekte detektieren, tracken und vorhersagen. Pseudo-Zellen erweitern Risk-Grid und KMZ. 300-hPa-Steuerstrom als neue Höhenwind-Schicht. Neue ML-Features (`bt_min_k`, `bt_trend_k_per_min`, `overshooting_top`, `ir_only_precursor`, …) für Radar-Zellen. | 3–4 Wochen | Nur Pi 5 (Inferenz) + Linux-Trainer (Modelle) | ⏳ Offen — Detail siehe §16 |

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
- HSV-Segmentierung + Kalman-Tracking (`object_tracking.py`)
- **Human-in-the-Loop Filter-Verfeinerung** (`cell_filters.py` + Filter-Galerie):
  Benutzer-Polygon → HSV-Extraktion → PNG-Speicherung → KI-Vorschläge via Anthropic API
- LSTM, LightGBM-Punkt + Quantile (`model_training.py`)
- ConvLSTM-Modell (`radar_convlstm.py`) — MODEL_PATH via SAVE_PATHS + runtime_config
- 5 Forecast-Horizonte (10/20/30/40/60 min)
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
- Atmosphären-Snapshot für Kärnten-Referenzpunkte (`fetch_atmospheric_snapshot.py`)
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
  Flächen ohne Rand (gelb/orange/rot), Toggle standardmäßig aus

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
| K10 | Hazard-spezifische Module (Wind/Rain/Tornado getrennt) | 🔜 Phase D |
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

### Neue Fach-Features in Phase C (geplant und umgesetzt)

| Feature | Beschreibung | Status |
|---|---|---|
| **Human-in-the-Loop Filter (HitL)** | Vom Benutzer markierte Zellen erweitern HSV-Filter; gespeicherte Polygon-PNGs dienen als Trainings-Quelle für ein künftiges U-Net auf dem Hailo-8 | ✅ **eingespielt** (Mai 2026) |
| HitL als U-Net-Trainings-Pipeline | Polygon-PNGs (mit Maske) als labels für ein semantisches Segmentierungs-Modell — Hailo-8 erzielt > 100 FPS bei 256×256 px | ⏳ geplant |
| **Dashboard API-Request Detail** | Klick auf Service-Zeile im Dashboard öffnet Panel mit letzten Requests (Timestamp, HTTP-Status, URL). Schnittstellen mit öffentlichem Browser-Zugang zeigen direkten Link (z.B. https://tawes.at/#knt) | ✅ **eingespielt** (Mai 2026) |
| **TAWES Cache-Konsolidierung** | `weather_api.py` nutzt jetzt `api_cache` mit TTL=600s — entspricht 10-min TAWES-Aktualisierungsintervall. Kein unnötiger Doppel-Request mehr neben `fetch_tawes_gust.py` | ✅ **eingespielt** (Mai 2026) |
| **KI-Analyse sendet vollst. Konfig** | `build_system_report()` überträgt alle effektiven Config-Werte + `runtime_overrides.json` an die KI. Secrets (TOKEN, KEY, PASS, ...) werden automatisch durch `***REDACTED***` ersetzt. KI kann nun Konfigurations-Empfehlungen machen | ✅ **eingespielt** (Mai 2026) |

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

## 17. Risiken

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

## 18. Quick-Start für neue Chat-Session

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

## 19. Glossar

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
| E5 | `ML_CELL_FEATURES` um 9 neue Features erweitert: `bt_min_k`, `bt_mean_k`, `bt_trend_k_per_min`, `cloud_age_min`, `anvil_extension_km`, `overshooting_top`, `ir_only_precursor`, `wind_speed_300hPa`, `wind_dir_300_cos`, `wind_dir_300_sin` | `config.py`, `dataset_builder.py`, `prediction.py` | ⏳ offen |
| E6 | `model_training.py`: Eigenes LightGBM-Trajektorien-Modell für IR-Cells (5 Horizonte, 300-hPa-Steuerstrom). Holdout-Validierung, Promotion-Logik analog Radar | `model_training.py`, `prediction.py` | ⏳ offen |
| E7 | `/api/risk_grid` um Quelle `ir_cell` erweitern (eigene Farb-Variante: schraffiert). `/api/objects?include_ir=1` liefert auch Pseudo-Zellen | `app.py` | ⏳ offen |
| E8 | Intensification-Prediction: `ir_to_radar_prob_<horizon>` — Wahrscheinlichkeit, dass IR-Zelle in 15/30/45 min ein Radar-Echo erzeugt. LightGBM-Binary-Classifier | `model_training.py`, `prediction.py` | ⏳ offen |
| E9 | KMZ-Export erweitern: getrennte Folder, gestrichelter Style für IR-Cells, `forecast.kmz` enthält beide Object-Typen | `kmz_export.py` (oder bestehender Export-Pfad) | ⏳ offen |
| E10 | Atmosphäre-Seite + MapView/MapFullscreen-Legende ergänzen. Toggle „🛰 IR-Vorläuferzellen anzeigen" (default aus). Benutzerhandbuch um Abschnitt 30 „IR-Sat Pre-Convection Tracking" ergänzt | `frontend/src/pages/Atmosphaere.jsx`, `frontend/src/pages/MapView.jsx`, `frontend/src/pages/MapFullscreen.jsx`, `docs/WetterExtended_Benutzerhandbuch.md` | ⏳ offen |

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

