# HAILO_INTEGRATION.md
# WetterExtended — Hailo-Integration, Phasen-Roadmap & Multi-Rechner-Architektur

**Dokumentversion:** 5.0 (Phase A vollständig abgeschlossen)
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
| **B — Hailo + U-Net** | Linux-Rechner anschaffen, Training auslagern, DFC-Pipeline, U-Net, Hailo-Integration | 6–8 Wochen | Pi 5 + Linux-Rechner | ⏳ Offen (wartet auf Linux-Rechner) |
| **C — Skalierung** | Optimierungen, weitere Modelle, KI-Analyse vertiefen, Bugfixes B10–B12 | bei Bedarf | Pi 5 + Linux-Rechner | ⏳ Offen |

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

### 11.3 Binaries die NICHT ins Git gehören

- `*.hef` — Hailo-Modelle
- `*.keras`, `*.h5` — Keras-Modelle (außer Bootstrap)
- `*.txt` in `train_data/models/` — LGBM-Modelle
- `*.joblib` — Scaler
- `*.npz` — Datasets, Calibration-Daten
- `*.onnx` — ONNX-Exports
- `*.png`, `*.kmz`, `*.gif` — generierte Bilder
- `*.parquet` — Tabular Datasets
- alles in `data/`, `logs/`, `train_data/`

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

### 14.2 Was noch nicht funktioniert / fehlt
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
