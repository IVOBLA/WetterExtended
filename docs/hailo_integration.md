# HAILO_INTEGRATION.md
# WetterExtended — Hailo-Integration, Phasen-Roadmap & Multi-Rechner-Architektur

**Dokumentversion:** 4.0 (vollständige Übergabe)
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
- Welche Rolle der Linux-Rechner hat (Trainer, siehe §8)
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

### 2.2 Was NICHT vorhanden ist
- Kein zweiter Raspberry Pi (auch keiner geplant)
- Kein x86-Linux-Rechner — wird in **Phase B** angeschafft

### 2.3 Geplante Rollenverteilung

| Rechner | Rolle | Phase | Hauptaufgaben |
|---------|-------|-------|---------------|
| **Raspberry Pi 5 + Hailo-8** | Edge | A + B + C | Live-Loop, Inferenz, Datensammlung, Admin-Panel |
| **x86-Linux-Rechner** | **Trainer (only)** | B + C | Modell-Training, ONNX-Export, DFC-Build, kein Live-Loop |

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

| Phase | Inhalt | Dauer | Hardware-Bedarf |
|-------|--------|-------|----------------|
| **A — Stabilität** | Bugfixes, Cleanup, Auth, Trainer-Architektur vorbereiten | 4–6 Wochen | Nur Pi 5 |
| **B — Hailo + U-Net** | Linux-Rechner anschaffen, DFC-Pipeline, U-Net, Hailo-Integration | 6–8 Wochen | Pi 5 + Linux-Rechner |
| **C — Skalierung** | Optimierungen, eventuell weitere Modelle, KI-Analyse vertiefen | bei Bedarf | Pi 5 + Linux-Rechner |

### Pre-Conditions
- Phase B startet erst NACH vollständiger Phase A
- Linux-Rechner-Anschaffung am Übergang A → B
- Phase A bereitet alle Hooks für Linux-Rechner schon vor (z. B. `LOCAL_TRAINING`-Flag)

---

## 5. Phase A — Stabilität (priorisierte Tasks)

### 5.1 Task-Liste

Reihenfolge: A1 → A2 → A3 → A4 → A5 → A6 → A8 → A7 → A9 → A10

| # | Task | Datei(en) | Status | Aufwand |
|---|------|-----------|--------|---------|
| A1 | Bugfix `parse_timestamp` | `assign_cape_from_forecast.py` | offen | Trivial (5 min) |
| A2 | `radar_download.py`: Timeout + log_api_failure + Retry | `radar_download.py` | offen | Klein (30 min) |
| A3 | `blitz_api.py`: HTTP-Basic-Auth statt URL-Credentials | `blitz_api.py` | offen | Klein (20 min) |
| A4 | Daten-Cleanup-Job (Rotation >90 Tage) | `scheduler.py`, `cleanup_old_data.py` (neu), `config.py` | offen | Klein (1 h) |
| A5 | Speicher-/Disk-Monitoring im Admin-Panel | `app.py`, `frontend/src/pages/Dashboard.jsx` | offen | Klein (1 h) |
| A6 | nginx Basic-Auth für Admin-Panel | `install.sh`, nginx-Snippet | offen | Klein (45 min) |
| A7 | Open-Meteo Bulk-Query (alle Zellen 1 Request) | `fetch_arome_openmeteo.py`, `fetch_700hpa_wind_per_object_slim.py` | offen | Mittel (2 h) |
| A8 | `LOCAL_TRAINING`-Flag einbauen (Trainer-Vorbereitung) | `config.py`, `scheduler.py`, `install.sh`, `app.py`, `Training.jsx` | offen | Mittel (1,5 h) |
| A9 | File-Locking bei JSON-Schreibvorgängen | `runtime_config.py` | offen | Klein (45 min) |
| A10 | ConvLSTM hardcoded MODEL_PATH prüfen + fixen | `radar_convlstm.py` | offen | Klein (20 min) |

### 5.2 Task-Details

#### A1 — `parse_timestamp` Bugfix
**Datei:** `assign_cape_from_forecast.py`
**Bug:** Schleife über `formats`-Tupel, aber Body verwendet immer das
hardgecodete Format statt der Schleifen-Variable `fmt`. Andere Formate
werden nie versucht.

```python
# Aktueller Code (FALSCH):
for fmt in formats:
    try:
        return datetime.strptime(timestamp_str, "%Y-%m-%d_%H-%M-%S").replace(...)
    except ValueError:
        continue
```

**Fix:** `fmt` aus der Schleife verwenden, ISO-Format mit Zeitzone
gesondert behandeln (timezone-aware vs naive).

#### A2 — `radar_download.py` Hardening
**Datei:** `radar_download.py`
**Probleme:**
- Kein Timeout am `requests.get()` (nur am HEAD)
- Kein User-Agent
- Kein Retry bei transienten Fehlern
- Kein `log_api_failure()` → ARSO-Ausfälle nicht im `/api/api_health` sichtbar

**Fix:**
- Timeout 30 s am GET
- User-Agent setzen
- 3 Retries mit exponentiellem Backoff
- `log_api_failure("ARSO-Radar", KMZ_URL, reason, fallback_used=False)` bei Fehler

#### A3 — `blitz_api.py` Auth-Header
**Datei:** `blitz_api.py`
**Bug:** Username/Passwort eingebettet in URL:
```python
url = f"https://{USERNAME}:{PASSWORD}@data.blitzortung.org/..."
```
Erscheint dadurch in Logs, Server-Logs, Caches.

**Fix:**
```python
url = "https://data.blitzortung.org/Data/Protected/last_strikes.php?..."
response = requests.get(url, auth=(USERNAME, PASSWORD), timeout=10)
```
Zusätzlich: `log_api_failure` bei Fehlern.

#### A4 — Daten-Cleanup-Job

**Neue Datei:** `cleanup_old_data.py`
**Modifikation:** `scheduler.py`, `config.py`

**Konfig in `config.py`:**
```python
# Datenrotation: alle Dateien älter als N Tage werden gelöscht
DATA_RETENTION_DAYS = 90
DATA_CLEANUP_CRON_HOUR = 4
DATA_CLEANUP_CRON_MINUTE = 30
# Welche Verzeichnisse rotieren werden (vollständig konfigurierbar):
DATA_CLEANUP_PATHS = [
    "train_data/radar/",
    "train_data/objects/",
    "train_data/weather/",
    "train_data/wind/",
    "train_data/cape/",
    "train_data/lightning/",
    "train_data/ir/",
    "train_data/ir_cells/",
    "train_data/cloud/",
    "train_data/arome/",
]
# Diese werden NICHT rotiert:
# - train_data/models/        (versioniert, separate cleanup_old_versions)
# - train_data/evaluation/    (Historie, klein, behalten)
# - train_data/dataset/       (aktuelles Trainings-Dataset, klein)
```

**`cleanup_old_data.py`** läuft täglich um 04:30 (nach Nightly-Retrain um 03:00).
Löscht Dateien älter als `DATA_RETENTION_DAYS`, loggt Anzahl gelöschter
Dateien + freigegebenen Speicher in `train_data/evaluation/cleanup_log.jsonl`.

**Scheduler-Job in `scheduler.py`:**
```python
sched.add_job(
    run_cleanup_job,
    trigger=CronTrigger(
        hour=runtime_config.get("DATA_CLEANUP_CRON_HOUR", 4),
        minute=runtime_config.get("DATA_CLEANUP_CRON_MINUTE", 30),
    ),
    id="data_cleanup", max_instances=1, coalesce=True,
)
```

#### A5 — Disk-Monitoring

**Modifikation:** `app.py`, `frontend/src/pages/Dashboard.jsx`

**Neuer API-Endpoint in `app.py`:**
```python
@app.route("/api/disk")
def api_disk():
    import shutil
    total, used, free = shutil.disk_usage("/")
    pct = (used / total) * 100 if total else 0
    return jsonify({
        "total_gb": round(total / 1e9, 1),
        "used_gb":  round(used  / 1e9, 1),
        "free_gb":  round(free  / 1e9, 1),
        "used_pct": round(pct, 1),
        "warning":  pct > 80,
        "critical": pct > 90,
    })
```

**`Dashboard.jsx`** zeigt Disk-Usage als Status-Karte mit
Farbcodierung (grün < 70%, gelb 70–90%, rot > 90%).

#### A6 — nginx Basic-Auth

**Modifikation:** `install.sh` Phase 8 (nginx-Setup)

```bash
# Generiert Zufallspasswort und htpasswd-Datei beim ersten Setup
ADMIN_PASS=$(openssl rand -base64 12)
sudo apt-get install -y apache2-utils
echo "$ADMIN_PASS" | sudo htpasswd -ic /etc/nginx/.htpasswd admin

# nginx-Config-Snippet:
sudo tee /etc/nginx/sites-available/wetterprojekt > /dev/null <<NGINX_CONF
server {
    listen 80;
    server_name _;

    auth_basic           "Wetterprojekt Admin";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
NGINX_CONF
```

Passwort wird einmalig am Ende der Installation angezeigt und in
`/home/ki-pi/wetterprojekt/.admin_password` gespeichert (Modus 600).

#### A7 — Open-Meteo Bulk-Query

**Dateien:** `fetch_arome_openmeteo.py`, `fetch_700hpa_wind_per_object_slim.py`

**Aktuell:** Pro Zelle ein eigener Request mit 0,3 s Sleep. Bei 20 Zellen
pro Frame, 30 Frames pro Stunde → bis zu 600 API-Calls/h. Open-Meteo
Free-Tier ist 10000/Tag → bei aktivem Wetter knapp.

**Fix:** Open-Meteo unterstützt komma-separierte Koordinaten:
```python
lats = ",".join(str(o["lat"]) for o in objects if o.get("lat") is not None)
lons = ",".join(str(o["lon"]) for o in objects if o.get("lon") is not None)
url = f"{OPEN_METEO_URL}?latitude={lats}&longitude={lons}&hourly=..."
# Response enthält Array von Locations in gleicher Reihenfolge
```

#### A8 — `LOCAL_TRAINING`-Flag

**Zweck:** Vorbereitung dafür dass in Phase B ein Linux-Rechner das Training
übernimmt. Der Pi schaltet dann auf `LOCAL_TRAINING=False`. In Phase A wird
nur das Flag eingebaut — Default bleibt `True`, der Pi trainiert weiter wie bisher.

**`config.py` — am Ende hinzufügen:**
```python
# -------------------------------------------------------
# Multi-Rechner-Vorbereitung
# -------------------------------------------------------
# Steuert ob auf diesem Rechner Modell-Training stattfindet.
# True  = Scheduler startet retrain_*, rebuild_dataset, convlstm_weekly Jobs
# False = Diese Jobs werden übersprungen, Modelle kommen extern (rsync vom Trainer)
# Kann per runtime_overrides.json oder install.sh --no-training überschrieben werden.
LOCAL_TRAINING: bool = True
```

**`scheduler.py` — Guard-Block in `create_scheduler()`:**
```python
def create_scheduler() -> BlockingScheduler:
    from config import LOCAL_TRAINING
    local_training = runtime_config.get("LOCAL_TRAINING", LOCAL_TRAINING)

    sched = BlockingScheduler(timezone="Europe/Vienna")

    if not local_training:
        debug_log("[SCHEDULER] LOCAL_TRAINING=False — Training-Jobs übersprungen.")
        debug_log("[SCHEDULER] Aktive Jobs: accuracy_eval, ai_analysis, data_cleanup")
    else:
        debug_log("[SCHEDULER] LOCAL_TRAINING=True — alle Jobs aktiv.")

    # KI-Analyse + Accuracy-Eval immer aktiv (siehe bisheriger Code)
    # ...

    # Training-Jobs nur wenn lokal trainiert wird:
    if local_training:
        sched.add_job(run_rebuild_dataset_job, ...)
        sched.add_job(lambda: run_retrain_job("retrain_interval"), ...)
        sched.add_job(lambda: run_retrain_job("retrain_nightly"), ...)
        sched.add_job(run_convlstm_weekly_job, ...)

    # Data-Cleanup immer aktiv
    sched.add_job(run_cleanup_job, ...)

    return sched
```

**`install.sh` — neues Flag:**
```bash
LOCAL_TRAINING_FLAG=true     # Default

case "$1" in
    --no-training)  LOCAL_TRAINING_FLAG=false; shift ;;
    ...
esac

# In Phase 6b: Flag in runtime_overrides.json schreiben falls nicht Default
if [[ "$LOCAL_TRAINING_FLAG" == "false" ]]; then
    "$VENV/bin/python3" - <<PYEOF
import json, os
path = "$TARGET/runtime_overrides.json"
data = {}
if os.path.exists(path):
    with open(path) as f:
        try: data = json.load(f)
        except: data = {}
data["LOCAL_TRAINING"] = False
with open(path, "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
print("[INSTALL] LOCAL_TRAINING=False gesetzt")
PYEOF
fi
```

**`app.py` — Endpoint erweitern:**
`/api/config` gibt `LOCAL_TRAINING` zurück (ist es eh schon, da `all_effective`).
Neuer einfacher Endpoint für UI:
```python
@app.route("/api/local_training")
def api_local_training():
    return jsonify({
        "local_training": runtime_config.get("LOCAL_TRAINING", True),
    })
```

**`Training.jsx` — Banner wenn deaktiviert:**
```jsx
const [localTraining, setLocalTraining] = useState(true)

useEffect(() => {
  api.get('/api/local_training')
    .then(d => setLocalTraining(d.local_training !== false))
    .catch(() => {})
}, [])

// Im JSX vor erstem Card:
{!localTraining && (
  <div className="bg-yellow-100 border border-yellow-400 text-yellow-900 p-3 rounded mb-4">
    <strong>Lokales Training deaktiviert</strong> — Modelle werden extern
    auf dem Trainer-Rechner berechnet und per rsync synchronisiert.
  </div>
)}
```

#### A9 — File-Locking

**Datei:** `runtime_config.py`
**Bug:** `runtime_overrides.json` wird atomic geschrieben (gut), aber bei
gleichzeitigem Lesen während Schreibens kann ein anderer Prozess
inkonsistente Daten lesen.

**Fix:** `fcntl.flock()` beim Lesen und Schreiben.

#### A10 — ConvLSTM MODEL_PATH

**Datei:** `radar_convlstm.py`
**Zu prüfen:** Wird `MODEL_PATH` aus `SAVE_PATHS["models"]` und
`runtime_config` gelesen, oder hardcoded?

**Fix falls hardcoded:**
```python
from config import SAVE_PATHS
MODEL_PATH = os.path.join(SAVE_PATHS["models"], "current", "convlstm.keras")
```

### 5.3 Definition of Done pro Task

1. Code-Änderung steht im Repo (manuell committed nach Test)
2. Mindestens 1 Test-Aufruf zeigt dass es funktioniert
3. Falls UI-Änderung: visuell verifiziert
4. Falls Scheduler-Job: in einem Lauf erfolgreich ausgeführt
5. Keine bestehende Funktion bricht (smoke-test Live-Loop)

---

## 6. Phase B — Hailo + U-Net + Linux-Trainer

### 6.1 Voraussetzungen
- Phase A vollständig abgeschlossen
- Linux-Rechner mit Ubuntu 22.04 + Docker beschafft
- Hailo Developer Zone Account angelegt (kostenlos)
- Mindestens 4 Wochen Radar-Trainingsdaten auf Pi gesammelt (~50000 Frames)

### 6.2 Schritte

| # | Schritt | Wo | Dauer |
|---|---------|-----|-------|
| B1 | Linux-Rechner aufsetzen (Ubuntu, Docker, Hailo DFC) | Linux-PC | 1 Tag |
| B2 | Repo auf Linux-Rechner klonen, venv, requirements | Linux-PC | 2 h |
| B3 | `LOCAL_TRAINING=False` auf Pi setzen | Pi | 5 min |
| B4 | `LOCAL_LIVE_LOOP` ist nicht nötig — der `wetterprojekt.service` wird auf Linux gar nicht erst aktiviert | Linux | manuell |
| B5 | `hailo_inference.py` produktionsreif einspielen (Code §11) | Pi | 30 min |
| B6 | `tools/sync_*.sh` Skripte schreiben (Datenfluss Pi ↔ Linux) | Pi + Linux | 1 Tag |
| B7 | Sync-cron auf beiden Rechnern einrichten | Pi + Linux | 1 h |
| B8 | U-Net-Architektur in `unet_nowcast.py` (neu) implementieren | Linux | 2 Tage |
| B9 | Erstes U-Net-Training auf Linux | Linux | 1–2 Tage |
| B10 | ONNX-Export | Linux | 1 h |
| B11 | DFC-Build (HEF) auf Linux mit Docker | Linux | 1 Tag |
| B12 | HEF zum Pi syncen | automatisch via Sync | 5 min |
| B13 | Test-Inferenz auf Pi mit echtem Hailo | Pi | 1 Tag |
| B14 | Integration in `prediction.py` als Ergänzung | Pi | 1 Woche |
| B15 | Closed-Loop-Verifikation U-Net vs LSTM/LGBM | Pi | 2 Wochen |

### 6.3 Datenfluss (Phase B aktiv)

```
┌────────────────────────────┐         ┌─────────────────────────────┐
│   Raspberry Pi 5 (Edge)    │         │  Linux-PC (Trainer-only)    │
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
│                            │         │ ● Kein main.py (kein        │
│                            │         │   wetterprojekt.service)    │
│                            │         │                             │
│  train_data/      ────► rsync ─────►  train_data/                  │
│  (Pi → Linux, alle 30 min)            │                             │
│                            │         │                             │
│  models/current/   ◄──── rsync ─────  models/current/              │
│  models/hailo/     ◄──── rsync ─────  models/hailo/                │
│  (Linux → Pi, nach jedem Training)    │                             │
└────────────────────────────┘         └─────────────────────────────┘
```

### 6.4 Sync-Skripte

**Auf Pi: `tools/sync_train_data_to_trainer.sh`** (cron alle 30 min)
```bash
#!/usr/bin/env bash
# Synchronisiert Trainingsdaten vom Pi zum Linux-Trainer.
# Verwendung: ./tools/sync_train_data_to_trainer.sh
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
# Synchronisiert frisch trainierte Modelle vom Linux-Trainer zum Pi.
set -euo pipefail

PI_HOST="${PI_HOST:?Bitte PI_HOST in .env setzen}"
PI_USER="${PI_USER:-ki-pi}"
PI_PATH="${PI_PATH:-/home/ki-pi/wetterprojekt}"

# Keras + LGBM-Modelle
rsync -avz --delete \
  /home/horst/wetterprojekt/train_data/models/current/ \
  "${PI_USER}@${PI_HOST}:${PI_PATH}/train_data/models/current/"

# HEF-Dateien
rsync -avz --delete \
  --include="*.hef" --include="*.meta.json" --exclude="*" \
  /home/horst/wetterprojekt/models/hailo/ \
  "${PI_USER}@${PI_HOST}:${PI_PATH}/models/hailo/"

# Hailo-Modelle auf Pi neuladen
ssh "${PI_USER}@${PI_HOST}" \
  "curl -s -u admin:\$(cat ${PI_PATH}/.admin_password) -X POST http://localhost:5000/api/hailo/reload"
```

### 6.5 SSH-Key-Setup (Phase B Anfang)
- SSH-Key zwischen Pi und Linux einrichten (passwortlos für rsync)
- TRAINER_HOST/PI_HOST in jeweiliger `.env` setzen
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
  7. rsync zum Pi
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
        "output_name":  "conv2d_24",   # ggf. nach Architektur anpassen
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

## 10. Verzeichnis-Konventionen

### 10.1 Auf dem Pi

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
│   ├── hailo/                      # für Linux-Trainer (laufen dort)
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
│   ├── radar/, objects/, weather/, ...
│   ├── models/                     # versioniert
│   │   ├── current → v_2026-...
│   │   └── v_2026-05-15T03-00-00Z/
│   ├── onnx/                       # ONNX-Exports
│   └── calib/                      # INT8-Calibration-Daten
├── data/                           # Live-Cache (gitignored)
└── logs/                           # gitignored
```

### 10.2 Auf dem Linux-Trainer

Identisches Layout. `train_data/` wird durch rsync vom Pi gefüllt, `models/`
wird auf Linux geschrieben und durch rsync zum Pi gesynct.
Auf Linux **kein** `wetterprojekt.service` (kein Live-Loop), aber
`wetterprojekt-scheduler.service` aktiv (für Training-Jobs).
Optional: `wetterprojekt-admin.service` für eigenen Admin-Zugriff.

### 10.3 Binaries die NICHT ins Git gehören

- `*.hef` — Hailo-Modelle
- `*.keras`, `*.h5` — Keras-Modelle (außer Bootstrap)
- `*.txt` in `train_data/models/` — LGBM-Modelle (kompiliert)
- `*.joblib` — Scaler
- `*.npz` — Datasets, Calibration-Daten
- `*.onnx` — ONNX-Exports
- `*.png`, `*.kmz`, `*.gif` — generierte Bilder
- `*.parquet` — Tabular Datasets
- alles in `data/`, `logs/`, `train_data/`

### 10.4 `.gitignore` (Empfehlung für beide Rechner)

```
venv/
__pycache__/
*.pyc
.env
.admin_password
runtime_overrides.json
node_modules/
frontend/dist/

# Daten und Modelle
data/
logs/
train_data/
models/hailo/*.hef
models/hailo/*.meta.json
!models/hailo/.gitkeep

# Generierte Outputs
*.kmz
*.gif
plots/
```

---

## 11. `hailo_inference.py` (produktionsreifer Wrapper für Phase B)

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


def _log_latency(model_name: str, latency_ms: float, used_hailo: bool) -> None:
    from datetime import datetime as _dt
    rec = {
        "ts_utc":     _dt.utcnow().isoformat(timespec="seconds") + "Z",
        "model":      model_name,
        "latency_ms": round(latency_ms, 3),
        "hailo":      used_hailo,
    }
    try:
        os.makedirs(os.path.dirname(_LATENCY_FILE), exist_ok=True)
        with open(_LATENCY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


_LOCK = threading.RLock()
_vdevice = None
_network_group_cache: dict = {}
_hef_cache: dict = {}
_hailo_available: Optional[bool] = None


def _try_import_hailo():
    try:
        import hailo_platform as hp
        return True, hp
    except Exception as exc:
        debug_log(f"[HAILO] Import-Fehler: {exc}")
        return False, None


def _ensure_vdevice():
    global _vdevice, _hailo_available
    with _LOCK:
        if _hailo_available is False:
            return False, None, None
        if _vdevice is not None:
            ok, hp = _try_import_hailo()
            return ok, _vdevice, hp
        ok, hp = _try_import_hailo()
        if not ok:
            _hailo_available = False
            debug_log("[HAILO] hailo_platform nicht installiert — CPU-Fallback aktiv.")
            return False, None, None
        try:
            _vdevice = hp.VDevice()
            _hailo_available = True
            debug_log("[HAILO] VDevice initialisiert ✅")
            return True, _vdevice, hp
        except Exception as exc:
            _hailo_available = False
            debug_log(f"[HAILO] VDevice-Init fehlgeschlagen: {exc}")
            log_api_failure("Hailo-8", "VDevice.__init__", str(exc), fallback_used=True)
            return False, None, None


def _load_network_group(model_name: str):
    global _hef_cache, _network_group_cache
    with _LOCK:
        if model_name in _network_group_cache:
            return _network_group_cache[model_name]

        ok, vdevice, hp = _ensure_vdevice()
        if not ok:
            return None

        spec = _MODEL_SPECS.get(model_name)
        if spec is None:
            debug_log(f"[HAILO] Unbekanntes Modell: {model_name}")
            return None

        hef_path = spec["hef"]
        if not os.path.exists(hef_path):
            debug_log(f"[HAILO] HEF nicht gefunden: {hef_path}")
            return None

        try:
            hef = hp.HEF(hef_path)
            _hef_cache[model_name] = hef
            configure_params = hp.ConfigureParams.create_from_hef(
                hef=hef, interface=hp.HailoStreamInterface.PCIe,
            )
            network_groups = vdevice.configure(hef, configure_params)
            if not network_groups:
                return None
            ng = network_groups[0]
            _network_group_cache[model_name] = ng
            debug_log(f"[HAILO] Modell geladen: {model_name} ✅")
            return ng
        except Exception as exc:
            debug_log(f"[HAILO] Laden fehlgeschlagen ({model_name}): {exc}")
            log_api_failure("Hailo-8", hef_path, str(exc), fallback_used=True)
            return None


def _infer(model_name: str, input_array: np.ndarray) -> Optional[np.ndarray]:
    ok, _, hp = _ensure_vdevice()
    if not ok:
        return None
    ng = _load_network_group(model_name)
    if ng is None:
        return None
    try:
        input_stream_info  = ng.get_input_stream_infos()[0]
        output_stream_info = ng.get_output_stream_infos()[0]
        input_name  = input_stream_info.name
        output_name = output_stream_info.name

        input_vstreams_params = hp.InputVStreamParams.make(
            ng, quantized=False, format_type=hp.FormatType.FLOAT32,
        )
        output_vstreams_params = hp.OutputVStreamParams.make(
            ng, quantized=False, format_type=hp.FormatType.FLOAT32,
        )

        with hp.InferVStreams(ng, input_vstreams_params, output_vstreams_params) as pipeline:
            with ng.activate(ng.create_params()):
                result = pipeline.infer({input_name: input_array.astype(np.float32)})
                return result[output_name]
    except Exception as exc:
        debug_log(f"[HAILO] Inferenz-Fehler ({model_name}): {exc}")
        log_api_failure("Hailo-8", model_name, str(exc), fallback_used=True)
        with _LOCK:
            _network_group_cache.pop(model_name, None)
        return None


# ---------------------------------------------------------------------------
# Öffentliche API
# ---------------------------------------------------------------------------

def get_unet_nowcast(frame_stack: np.ndarray) -> Optional[np.ndarray]:
    """
    Radar-Nowcasting mit U-Net.
    frame_stack: (256, 256, 4) — 4 letzte Radar-Frames als Single-Channel
    return:      (256, 256, 5) — 5 Horizonte oder None bei Fallback
    """
    if frame_stack is None or frame_stack.shape != (256, 256, 4):
        debug_log(f"[HAILO] Ungültige Input-Shape: {frame_stack.shape if frame_stack is not None else None}")
        return None

    arr = frame_stack[np.newaxis, ...].astype(np.float32)

    t0 = time.perf_counter()
    result = _infer("unet_nowcast", arr)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    if result is None:
        _log_latency("unet_nowcast", elapsed_ms, used_hailo=False)
        return None

    _log_latency("unet_nowcast", elapsed_ms, used_hailo=True)
    debug_log(f"[HAILO] unet_nowcast: latency={elapsed_ms:.1f}ms")
    return result[0]   # (256, 256, 5)


def get_backend_status() -> dict:
    """Vollständiger Hailo-Status für Admin-Panel."""
    ok, _, _ = _ensure_vdevice()
    loaded = list(_network_group_cache.keys())

    models_info = {}
    for name, spec in _MODEL_SPECS.items():
        meta = {}
        if os.path.exists(spec["meta"]):
            try:
                with open(spec["meta"], encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                pass
        models_info[name] = {
            "hef_exists":           os.path.exists(spec["hef"]),
            "loaded":               name in loaded,
            "version":              meta.get("version"),
            "compiled_at_utc":      meta.get("compiled_at_utc"),
            "validation_accuracy":  meta.get("validation_accuracy"),
            "training_samples":     meta.get("training_samples"),
            "description":          spec["description"],
        }

    hailort_version = None
    if ok:
        try:
            import subprocess
            hailort_version = subprocess.check_output(
                ["hailortcli", "--version"], text=True, timeout=5,
                stderr=subprocess.DEVNULL,
            ).strip().splitlines()[0]
        except Exception:
            hailort_version = "unbekannt"

    return {
        "available":       ok,
        "hailort_version": hailort_version,
        "vdevice_active":  _vdevice is not None,
        "loaded_models":   loaded,
        "models":          models_info,
    }


def reload_models() -> dict:
    """Leert Modell-Cache — beim nächsten Aufruf wird neu geladen."""
    global _network_group_cache, _hef_cache
    with _LOCK:
        _network_group_cache.clear()
        _hef_cache.clear()
    debug_log("[HAILO] Modell-Cache geleert — Reload beim nächsten Inferenz-Aufruf.")
    return {"ok": True}


def latency_summary(last_n: int = 100) -> dict:
    """Latenz-Statistik der letzten N Aufrufe."""
    if not os.path.exists(_LATENCY_FILE):
        return {}
    entries = []
    try:
        with open(_LATENCY_FILE, encoding="utf-8") as f:
            lines = f.readlines()[-last_n:]
        for line in lines:
            try:
                entries.append(json.loads(line.strip()))
            except Exception:
                continue
    except Exception:
        return {}

    result = {}
    for model_name in _MODEL_SPECS:
        rows = [e for e in entries if e.get("model") == model_name]
        if not rows:
            continue
        latencies = [e["latency_ms"] for e in rows]
        hailo_rows = [e for e in rows if e.get("hailo")]
        result[model_name] = {
            "count":          len(rows),
            "hailo_count":    len(hailo_rows),
            "fallback_count": len(rows) - len(hailo_rows),
            "avg_ms":         round(sum(latencies) / len(latencies), 2),
            "min_ms":         round(min(latencies), 2),
            "max_ms":         round(max(latencies), 2),
        }
    return result


if __name__ == "__main__":
    print("=== Hailo-8 Smoke Test ===")
    status = get_backend_status()
    print(f"Hailo verfügbar : {status['available']}")
    print(f"HailoRT          : {status['hailort_version']}")
    for m, info in status["models"].items():
        print(f"  {m}: hef={info['hef_exists']} loaded={info['loaded']} v={info['version']}")

    if status['available']:
        dummy = np.random.rand(256, 256, 4).astype(np.float32)
        res = get_unet_nowcast(dummy)
        print(f"Inferenz-Test: shape={res.shape if res is not None else 'FALLBACK'}")
```

---

## 12. Externe APIs — kritische Constraints

| API | URL | Limit | Bemerkung |
|-----|-----|-------|-----------|
| ARSO Radar | `https://meteo.arso.gov.si/uploads/probase/www/nowcast/inca/inca_si0zm_latest.kmz` | keine offizielle Quote | öffentlich, kein Key |
| Open-Meteo icon_d2 | `https://api.open-meteo.com/v1/forecast?models=icon_d2` | 10000/Tag (free) | **A7: Bulk-Query nötig** |
| Open-Meteo 700hPa | `https://api.open-meteo.com/v1/forecast` | gleiche Quote | A7 betrifft auch dies |
| GeoSphere CAPE | `https://dataset.api.hub.geosphere.at/v1/grid/forecast/nwp-v1-1h-2500m` | keine offizielle Quote | öffentlich, kein Key |
| EUMETView WMS | `https://view.eumetsat.int/geoserver/...` | keine offizielle Quote | langsam, manchmal Ausfälle |
| Copernicus DEM | `https://copernicus-dem-30m.s3.amazonaws.com` | keine | nur Erstdownload nötig |
| lightningmaps.org | siehe `config.py` | inoffiziell | **NICHT für Produktion** — bessere Quelle suchen |
| Blitzortung | `https://data.blitzortung.org/Data/Protected/...` | Account nötig | **A3: HTTP-Basic-Auth** |
| Anthropic API | `https://api.anthropic.com` | abhängig vom Plan | nur wenn `AI_ANALYSIS_CONFIG['enabled']` |

---

## 13. Aktueller Repo-Stand (zur Verifikation in neuer Session)

### 13.1 Was funktioniert
- HSV-Segmentierung + Kalman-Tracking (`object_tracking.py`)
- LSTM, LightGBM-Punkt + Quantile (`model_training.py`)
- ConvLSTM-Modell (`radar_convlstm.py`)
- 5 Forecast-Horizonte (10/20/30/40/60 min)
- Closed-Loop-Verifikation (`accuracy_tracker.py`)
- KI-Analyse via Anthropic API (`daily_analyzer.py`)
- React/Vite Admin-Panel mit 11 Seiten
- KMZ-Export mit Pfeilen + Unsicherheits-Ellipsen
- `install.sh` mit `--mode=full|upgrade`, Hailo-apt-Install
- Scheduler mit `rebuild_dataset`, `retrain_interval`, `retrain_nightly`, `convlstm_weekly`, `accuracy_eval`, `ai_analysis`

### 13.2 Was noch nicht funktioniert / fehlt
- Hailo-Inferenz nicht wirklich implementiert (`hailo_inference.py` ist Stub — wird in Phase B durch §11 ersetzt)
- Admin-Panel ohne Authentifizierung (Phase A: A6)
- Trainingsdaten wachsen unbegrenzt (Phase A: A4)
- Mehrere bekannte Bugs (siehe §14)
- `LOCAL_TRAINING`-Flag nicht vorhanden (Phase A: A8)

### 13.3 Bestehende systemd-Services auf Pi
- `wetterprojekt.service` — main.py Live-Loop
- `wetterprojekt-scheduler.service` — scheduler.py
- `wetterprojekt-admin.service` — app.py Flask + nginx

---

## 14. Bekannte Bugs (Phase-A-Quelle)

| # | Datei | Bug | Bestätigt | Task |
|---|-------|-----|-----------|------|
| B1 | `assign_cape_from_forecast.py` | `parse_timestamp`: `fmt` nicht benutzt | ja | A1 |
| B2 | `radar_download.py` | Kein Timeout am GET, kein log_api_failure | ja | A2 |
| B3 | `blitz_api.py` | Username/Passwort in URL → in Logs | ja | A3 |
| B4 | Systemweit | Trainingsdaten wachsen unbegrenzt | ja | A4 |
| B5 | `app.py` | Keine Authentifizierung | ja | A6 |
| B6 | `fetch_arome_openmeteo.py` | 1 API-Call pro Zelle statt Bulk | ja | A7 |
| B7 | `runtime_config.py` | Atomic-Write ok, kein File-Lock | wahrscheinlich | A9 |
| B8 | `radar_convlstm.py` | MODEL_PATH ggf. hardcoded | zu prüfen | A10 |
| B9 | `fetch_700hpa_wind_per_object_slim.py` | Kein `log_api_failure` | ja | A7 (Teil) |
| B10 | `dem_feature.py` | Kachel hardcoded | ja | Phase C |
| B11 | `cloud_height_from_eumetview.py` | `print` statt `debug_log`, keine log_api_failure | ja | Phase C |
| B12 | `lightning` config | `lightningmaps.org` ist inoffiziell | ja | Phase C |

---

## 15. Konventionen für Prompts und Code

### 15.1 Sprache
- Antworten auf Deutsch
- Code-Kommentare auf Deutsch (außer wenn API-Pattern es nahelegt)
- Variable-Namen auf Englisch

### 15.2 Code-Lieferung
- Code im Chat zeigen, nicht in Artifacts
- Bei Datei-Änderung klar angeben:
  - **"vollständige Datei ersetzen"** ODER
  - **"Abschnitt X durch Y ersetzen"** mit exakten Such-/Ersatz-Strings
- Bei mehreren Änderungen in einer Datei: jede einzeln dokumentieren
- Verifikations-Befehl mitliefern

### 15.3 Atomare Prompts

Jeder Code-Prompt enthält:
1. Dateiname exakt
2. Was die Änderung bewirkt (auf Deutsch)
3. Falls partial: exakter Such-String + exakter Ersatz-String
4. Falls neu: vollständiger Datei-Inhalt
5. Verifikations-Befehl
6. Bekannte Risiken / Voraussetzungen

### 15.4 Was zu vermeiden ist
- Keine Mock-Modelle, keine Beispiel-Code-Skizzen
- Keine Vermutungen über Imports oder Pfade — projekt-spezifisch prüfen
- Keine Stub-Implementierungen mit `TODO`-Kommentaren
- Keine Massenänderungen über mehrere Dateien gleichzeitig — pro Prompt eine Datei

### 15.5 Verifikation
- Vor jedem Lieferungsschritt: `project_knowledge_search` aufrufen
- Bei Behauptungen über bestehenden Code: zitierte Suchergebnisse als Evidenz
- Bei Reviews: Tabelle "Behauptung vs. Realität"

---

## 16. Risiken

| Risiko | WSK | Auswirkung | Mitigation |
|--------|-----|------------|------------|
| Hailo DFC kompiliert U-Net-Layer nicht | mittel | Build schlägt fehl | Nur DFC-getestete Layer verwenden |
| INT8-Quantization verschlechtert U-Net | mittel | Qualität bricht ein | INT16-Modus als Fallback testen |
| rsync schlägt fehl → Pi mit altem Modell | niedrig | Sub-optimale Vorhersage | Modell-Versionierung greift, alte Version bleibt aktiv |
| Linux-Trainer fällt aus | mittel | Kein Modell-Update | Pi-CPU-Training als Fallback (Phase A: `LOCAL_TRAINING` zurück auf True) |
| Hailo-Treiber-Update bricht API | niedrig | Inferenz fällt auf CPU | CPU-Fallback in `hailo_inference.py` |
| Calibration-Daten zu klein | hoch | Schlechte Quantization | Mindestens 200 reale Patches |
| SD-Karte voll bevor A4 deployed | hoch | Pi crasht | A4 sehr früh in Reihenfolge |

---

## 17. Quick-Start für neue Chat-Session

```
Nutzer in neuer Session:
  "Lies HAILO_INTEGRATION.md und mach weiter mit Task AX"

Claude:
  1. Sucht im Project-Knowledge nach HAILO_INTEGRATION.md
  2. Sucht aktuellen Stand der betroffenen Dateien
  3. Liefert atomaren Prompt für Task AX gemäß §15
  4. Wartet auf Bestätigung
  5. Liefert nächsten Task
```

---

## 18. Glossar

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
| Trainer-Rechner | Hier: x86-Linux-PC mit Training und DFC-Build |
| Closed-Loop-Verifikation | Vergleich Vorhersage vs. tatsächliche Beobachtung nach Eintritt |
| MAE | Mean Absolute Error — durchschnittlicher absoluter Fehler |
| ARSO | Slovenian Environment Agency — liefert Radar-KMZ |
| GeoSphere | Geosphere Austria — österreichischer Wetterdienst, liefert CAPE |
| EUMETView | EUMETSAT WMS-Service für Satellitendaten |
| LOCAL_TRAINING | Flag in config.py: True = lokales Training, False = Modelle kommen extern |

---

**ENDE DOKUMENT**

Bei Unklarheiten oder Konflikten zwischen diesem Dokument und Anweisungen in
einer neuen Chat-Session gilt dieses Dokument als verbindlich, sofern der
Nutzer es nicht explizit ändert.
