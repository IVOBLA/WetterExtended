# WetterExtended Benutzerhandbuch

**Radar-basiertes Sturmzellen-Tracking-System für Kärnten/Österreich**

**Zielgebiet:** Klagenfurt · Villach · Wolfsberg · Spittal · St. Veit

| Feld | Wert |
|---|---|
| Dokumentversion | v1.1 (Ergänzung Mai 2026) |
| Basisversion | v1.0 |
| Letzte Änderung | Mai 2026 |
| Sprache | Deutsch |
| Zielplattform | Raspberry Pi 5 B · Hailo-8 AI · 16 GB · 26 TOPS |
| Betriebssystem | Raspberry Pi OS Bookworm 64-bit (Kernel ≥ 6.6) |
| Repository | github.com/IVOBLA/WetterExtended (Branch: main) |
| Lokaler Pfad | `/home/ki-pi/wetterprojekt` |

Dieses Dokument ist das offizielle Benutzerhandbuch für das WetterExtended-System. Abschnitt 9 ff. dokumentieren alle Erweiterungen, die nach Version v1.0 eingeführt wurden.

---

## Inhaltsverzeichnis

1. [Systemübersicht](#1-systemübersicht)
2. [Voraussetzungen und Installation](#2-voraussetzungen-und-installation)
   - [2.1 install.sh — Vollinstallation (--mode=full)](#21-installsh--vollinstallation---modefull)
   - [2.2 install.sh — Upgrade (--mode=upgrade)](#22-installsh--upgrade---modeupgrade)
   - [2.3 install.sh — Optionen](#23-installsh--optionen)
3. [Betrieb und systemd-Services](#3-betrieb-und-systemd-services)
4. [Admin-Panel — Seiten und Bedienung](#4-admin-panel--seiten-und-bedienung)
   - [4.1 Dashboard](#41-dashboard-)
   - [4.2 Karte (MapView)](#42-karte-map)
   - [4.3 Live-Daten](#43-live-daten-live)
   - [4.4 Datensatz](#44-datensatz-data)
   - [4.5 Atmosphäre](#45-atmosphäre-atmosphaere-neu)
   - [4.6 Orte](#46-orte-locations)
   - [4.7 Schwellwerte](#47-schwellwerte-thresholds)
   - [4.8 Horizonte](#48-horizonte-horizons)
   - [4.9 Training](#49-training-training)
   - [4.10 Konfiguration](#410-konfiguration-config)
   - [4.11 Modell-Fortschritt](#411-modell-fortschritt-progress)
   - [4.12 Genauigkeit / Accuracy](#412-genauigkeit-accuracy)
   - [4.13 Logs](#413-logs-logs)
   - [4.14 KI-Analyse](#414-ki-analyse-ai-analysis-neu)
   - [4.15 Vollbild-Karte (/karte)](#415-vollbild-karte-karte-neu)
5. [Externe Datenquellen und APIs](#5-externe-datenquellen-und-apis)
6. [ML-Pipeline](#6-ml-pipeline)
   - [6.1 Modelle](#61-modelle)
   - [6.2 Features](#62-features-vollständige-liste)
   - [6.3 Training-Zeitplan](#63-training-zeitplan)
7. [Vorhersage-Verifikation (Closed-Loop)](#7-vorhersage-verifikation-closed-loop)
8. [KMZ-Export](#8-kmz-export)
9. [NEU: Erweiterungen nach v1.0 — Übersicht](#9-neu-erweiterungen-nach-v10--übersicht)
10. [NEU: Optical Flow (pysteps Lucas-Kanade)](#10-neu-optical-flow-pysteps-lucas-kanade)
11. [NEU: AROME icon_d2 Gitterpunkt-Wetterdaten](#11-neu-arome-icon_d2-gitterpunkt-wetterdaten)
12. [NEU: Erweiterte Geländemodell-Features (DEM)](#12-neu-erweiterte-geländemodell-features-dem)
13. [NEU: Windscherung und Hagelindikator](#13-neu-windscherung-und-hagelindikator)
14. [NEU: Atmosphären-Seite und Großwetterlage 500 hPa](#14-neu-atmosphären-seite-und-großwetterlage-500-hpa)
15. [NEU: GeoSphere TAWES und Nowcast-Daten](#15-neu-geosphere-tawes-und-nowcast-daten)
16. [NEU: E-Mail-Benachrichtigungen](#16-neu-e-mail-benachrichtigungen)
17. [NEU: Daten-Rotation (cleanup_old_data.py)](#17-neu-daten-rotation-cleanup_old_datapy)
18. [NEU: Disk-Monitoring im Dashboard](#18-neu-disk-monitoring-im-dashboard)
19. [NEU: Admin-Panel Authentifizierung (nginx)](#19-neu-admin-panel-authentifizierung-nginx)
20. [NEU: Adaptiver Loop-Intervall](#20-neu-adaptiver-loop-intervall)
21. [NEU: LOCAL_TRAINING-Flag](#21-neu-local_training-flag)
22. [NEU: API-Request-Statistik](#22-neu-api-request-statistik)
23. [NEU: KI-Analyse Chat (daily_analyzer.py)](#23-neu-ki-analyse-chat-daily_analyzerpy)
24. [NEU: Human-in-the-Loop Filter-Verfeinerung](#24-neu-human-in-the-loop-filter-verfeinerung)
25. [Hailo-8 Integration — Phasen-Roadmap](#25-hailo-8-integration--phasen-roadmap)
25. [Konfigurationsreferenz](#25-konfigurationsreferenz)
26. [Fehlerbehebung (Troubleshooting)](#26-fehlerbehebung-troubleshooting)
27. [Änderungshistorie](#27-änderungshistorie)

---

# 1 Systemübersicht

WetterExtended ist ein lokales Radar-basiertes Sturmzellen-Tracking- und Nowcasting-System für das Gebiet Kärnten/Österreich. Es verarbeitet ARSO INCA si0zm Radar-KMZ-Bilder in einem 5-Minuten-Takt, erkennt und verfolgt Niederschlagszellen mittels HSV-Farbsegmentierung und Kalman-Filter, und berechnet kurzzeitige Bewegungsvorhersagen (Nowcasting) mit mehreren Maschinellen-Lern-Modellen.

| Schicht | Komponente | Beschreibung |
|---|---|---|
| Datenbeschaffung | `radar_download.py`<br>`blitz_api.py`<br>`weather_api.py`<br>`fetch_arome_openmeteo.py`<br>`fetch_700hpa_wind_per_object_slim.py`<br>`fetch_geosphere_nowcast.py` | ARSO KMZ, Blitzortung, GeoSphere TAWES, Open-Meteo AROME icon_d2, 700 hPa Höhenwind, Nowcast-Daten |
| Verarbeitung | `object_tracking.py`<br>`optical_flow_features.py`<br>`orographic_module.py`<br>`assign_cape_from_forecast.py`<br>`cloud_height_from_eumetview.py` | HSV-Segmentierung, Kalman-Tracking, Optical Flow, DEM-Features, CAPE, Wolkenhöhe EUMETView |
| Vorhersage | `prediction.py`<br>`model_training.py`<br>`radar_convlstm.py` | LSTM + LightGBM (5 Horizonte), ConvLSTM, kinetisches Fallback |
| Persistenz | `accuracy_tracker.py`<br>`cleanup_old_data.py`<br>`runtime_config.py` | Closed-Loop-Verifikation, Daten-Rotation (90 Tage), Runtime-Override-System |
| Backend-API | `app.py` (Flask) | JSON-REST-API für Frontend, >30 Endpunkte |
| Frontend | React/Vite (15 Seiten)<br>nginx Reverse-Proxy | Admin-Panel, Leaflet-Karte, Basic-Auth über nginx |
| Infrastruktur | `install.sh`<br>`scheduler.py`<br>`sms_notifier.py`<br>`daily_analyzer.py` | Automatisiertes Setup, Cron-Jobs, SMS-Warnungen, KI-gestützte Analyse |
| KI-Beschleuniger | `hailo_inference.py` (Phase B) | Hailo-8 (26 TOPS) für U-Net Nowcasting (geplant Phase B) |

> **Hinweis:** Hailo-8 Inferenz ist in Phase A als Stub implementiert. Die vollständige Integration erfolgt in Phase B nach Anschaffung eines x86-Linux-Trainers.

## 1.1 systemd-Services

| Service | Datei | Funktion |
|---|---|---|
| `wetterprojekt.service` | `main.py` | Live-Loop (Radar → Tracking → Vorhersage → Upload) |
| `wetterprojekt-scheduler.service` | `scheduler.py` | Cron-Jobs (Training, Cleanup, Genauigkeit, KI-Analyse) |
| `wetterprojekt-admin.service` | `app.py` | Flask REST-API (Port 5000, erreichbar via nginx Port 80) |

---

# 2 Voraussetzungen und Installation

Die Installation erfolgt ausschließlich über das Skript `install.sh`. Es erkennt den Systemzustand automatisch und führt alle notwendigen Schritte aus.

## 2.1 Vollinstallation (`--mode=full`)

> **Achtung:** LÖSCHT alle Trainingsmodelle, Radar-Daten und Objekt-Historien! Das Copernicus DEM, `.env`, `runtime_overrides.json` **und `users.db`** (Benutzerkonten) bleiben erhalten.

```bash
bash install.sh --mode=full --repo git@github.com:IVOBLA/WetterExtended.git
```

Die Vollinstallation führt folgende Phasen durch:

- Prüfung OS-Version (Bookworm 64-bit), Kernel (≥ 6.6), Festplatte (min. 4 GB frei), RAM
- Git-Clone/Pull des Repositories
- System-Pakete: `python3`, `pip`, `nginx`, `apache2-utils`, `ffmpeg`, `libhdf5-dev` usw.
- Hailo-APT-Repository + `hailo-all` Treiber-Installation
- Python-venv erstellen + pip-Pakete installieren
- Copernicus DEM herunterladen (einmaliger Großdownload, ca. 800 MB)
- Node.js + npm installieren, Frontend bauen (`npm install && npm run build`)
- nginx Reverse-Proxy konfigurieren + Basic-Auth-Passwort generieren
- systemd-Services anlegen und aktivieren
- `.env`-Datei anlegen (FTP, Blitzortung, Twilio-Zugangsdaten)

## 2.2 Upgrade (`--mode=upgrade`)

> Aktualisiert nur den Source-Code. Modelle, Trainingsdaten und `.env` bleiben unverändert.

```bash
bash install.sh --mode=upgrade
```

Beim Upgrade werden aktualisiert: Python-Pakete, Frontend-Build, systemd-Unit-Dateien.

## 2.3 `install.sh` — Optionen

| Option | Standard | Beschreibung |
|---|---|---|
| `--mode=full\|upgrade` | `upgrade` | Installations-Modus (`full` = Neuinstallation; löscht Trainingsmodelle und Radardaten, **behält users.db, .env, DEM und runtime_overrides.json**) |
| `--repo URL` | — | Git-Repository-URL (SSH oder HTTPS) |
| `--version TAG` | — | Git-Tag auschecken, z.B. `v1.2.0`. Ohne Angabe wird `main` verwendet. |
| `--list-versions` | — | Alle verfügbaren Tags ausgeben und beenden |
| `--target PFAD` | `/home/ki-pi/wetterprojekt` | Zielpfad auf dem Pi |
| `--no-hailo` | — | Hailo-Installation überspringen |
| `--no-node` | — | Node.js/Frontend überspringen |
| `--no-training` | — | `LOCAL_TRAINING=false` setzen |
| `--enable-services` | — | systemd-Services nach Installation starten |
| `--local` | — | Lokale Dateien statt Git-Clone verwenden |

> **Hinweis:** Das generierte Admin-Passwort wird am Ende der Installation angezeigt und in `.admin_password` (Modus 600) gespeichert.

---

# 3 Betrieb und systemd-Services

| Aktion | Befehl |
|---|---|
| Status aller Services | `sudo systemctl status wetterprojekt wetterprojekt-scheduler wetterprojekt-admin` |
| Live-Loop starten/stoppen | `sudo systemctl start\|stop wetterprojekt.service` |
| Scheduler starten/stoppen | `sudo systemctl start\|stop wetterprojekt-scheduler.service` |
| Admin-Panel starten/stoppen | `sudo systemctl start\|stop wetterprojekt-admin.service` |
| Logs verfolgen (Live-Loop) | `journalctl -fu wetterprojekt.service` |
| Logs verfolgen (Scheduler) | `journalctl -fu wetterprojekt-scheduler.service` |
| Services nach Update neu laden | `sudo systemctl daemon-reload && sudo systemctl restart wetterprojekt wetterprojekt-scheduler wetterprojekt-admin` |

Das Admin-Panel ist erreichbar unter `http://<PI-IP>/` (Port 80, nginx). Die Authentifizierung erfolgt über einen JWT-Login (siehe Kapitel 22 — Rollenbasiertes Benutzermanagement); nicht eingeloggte Benutzer werden automatisch auf `/login` weitergeleitet. Die öffentliche Vollbild-Karte ist ohne Authentifizierung unter `http://<PI-IP>/karte` erreichbar.

---

# 4 Admin-Panel — Seiten und Bedienung

Das Admin-Panel ist eine React-Applikation (Vite + React 18 + Tailwind CSS + Leaflet + Recharts) mit 15 Seiten. Es wird über nginx auf Port 80 ausgeliefert und kommuniziert mit dem Flask-Backend (Port 5000) über eine REST-JSON-API.

## 4.1 Dashboard (`/`)

Systemstatus auf einen Blick: Anzahl aktiver Zellen, letzter Radar-Zeitstempel, Modell-Status, API-Gesundheit, Disk-Nutzung mit Farbampel (grün/gelb/rot), RAM-Auslastung.

### CPU-Auslastungsdiagramm

Das Dashboard zeigt unterhalb der Status-Cards ein Liniendiagramm der CPU-Auslastung
der letzten 24 Stunden.

| Element | Beschreibung |
|---|---|
| Ø Gesamt (blau) | Durchschnitt aller Kerne — immer sichtbar |
| Core 0–3 (farbig, gestrichelt) | Auslastung je CPU-Kern — per Checkbox "Einzelkerne anzeigen" togglebar |
| X-Achse | Uhrzeit (HH:MM, lokale Browserzeit) |
| Y-Achse | Prozent (0–100 %) |
| Takt | 5 Minuten (288 Messpunkte pro 24 h) |

**Datenquelle:** `cpu_monitor.py` — sampelt via `psutil.cpu_percent(percpu=True)` mit 1 s
Messintervall. Ergebnisse in `train_data/system/cpu_history.jsonl`.

**API-Endpoint:** `GET /api/cpu_history?hours=<1-48>` (Default: 24 h)

**Hinweis Raspberry Pi 5:** Das Geraet besitzt 4 ARM Cortex-A76 Kerne. Bei hoher Auslastung
eines einzelnen Kerns (z. B. waehrend Training oder Radar-Verarbeitung) ist dies in
den Einzelkern-Linien sichtbar.

## 4.2 Karte (`/map`)

Interaktive Leaflet-Karte mit Sturmzellen (Kontur + ID-Label), Vorhersage-Pfeilen (farbcodiert nach Horizont), Ortsdurchquerungs-Markierungen, Bewegungspfad-Historie, Hagelwarnungs-Rahmen (rot) und Stationär-Marker (⊕ amber). Farblegende unten links.


### IR-Vorläufer-Layer (🛰 IR-Vorläufer)

Zeigt konvektive Wolken-Cluster aus dem MSG IR108-Satellitenbild, die noch
**kein Radar-Echo** erzeugen — also 15–30 Minuten bevor das Gewitter im Radar erscheint.

**Aktivierung:** Checkbox „🛰 CB / IR-Vorläufer" in der Overlay-Leiste (standardmäßig aus).

Die Checkbox heißt jetzt **„CB / IR-Vorläufer"** (vorher „CB > 10.000"). Die
Erkennungsschwelle ist unverändert BT < 230 K (typisch > 10.000 m MSL);
angezeigte Wolkentop-Höhen einzelner Zellen können davon leicht abweichen.

**Darstellung:** Gestrichelter violetter Kreis. Größe proportional zur Clusterfläche.
Overshooting Tops (BT < 215 K) werden rot ausgefüllt dargestellt.

**Tooltip-Informationen:**
- BT_min [K]: Je kälter, desto höher und aktiver die Konvektion
- Trend [K/min]: Negativ = Zelle wächst (< −1.5 K/min = rasch wachsend ⚡)
- Alter [min]: Wie lange dieser IR-Cluster schon getrackt wird
- „Kein Radar-Echo — Vorläufer": Kein übereinstimmendes Radar-Objekt in 40 km
- „Overshooting Top ⚠": Cb-Turm bricht Tropopause durch → erhöhtes Hagelpotenzial

### Gewitterrisiko-Layer (🌩 Risikozonen)

Der Risikozonen-Layer überlagert die Karte mit farbigen Flächen,
die das Gewitterrisiko für jedes ~5×5 km Gebiet in Kärnten anzeigen.
Der Layer ist **unabhängig von erkannten Zellen** — er wird auch bei
reiner Blitzaktivität oder atmosphärischer Instabilität ohne Radar-Treffer aktiv.

**Aktivierung:** Checkbox „🌩 Risikozonen" in der Overlay-Leiste (**standardmäßig aktiv**).

**Hinweis zur BBOX:** Das Risikogrid berechnet sich für ganz Kärnten (lat 46.36–47.18,
lon 12.60–15.20). Die Grenzen werden aus `BBOX_KAERNTEN_EXTENDED` in `config.py` gelesen
und können über die Admin-Laufzeitkonfiguration überschrieben werden.

**Farbskala:**

| Farbe | Risikostufe | Typische Ursache |
|-------|-------------|------------------|
| 🟡 Gelb | Niedrig (1) | LI < −1 °C oder einzelne Blitze in der Nähe |
| 🟠 Orange | Mäßig (2) | Aktive Zelle in 30–60 km oder mittlere Blitzdichte |
| 🔴 Rot | Hoch (3) | Direkte Zelle + Forecast-Pfad oder LI < −3 °C + Blitze |

**Datenquellen (alle lokal, kein zusätzlicher API-Call):**
- Aktive Sturmzellen inkl. Forecast-Positionen (+10/+20/+30/+40 min)
- Blitzortung-Cache (letzte 20 Minuten)
- Atmosphärischer Snapshot: Lifted Index (LI) für Kärnten-Referenzpunkte

**Aktualisierung:** alle 60 Sekunden automatisch (API-Endpoint `/api/risk_grid`).

**Zugbahn-Korridor:**
Der Risiko-Score wird nur für Grid-Zellen erhöht, die auf einer **tatsächlich
berechneten Zugbahn** liegen (Forecast-Segment ≥ 2 km). Zellen ohne Bewegung
oder mit minimalem Drift erzeugen keinen Zugbahn-Einfluss. Der Korridor beträgt
30 km seitlich um den Pfad (lineare Gewichtung). In der Tooltip-Anzeige erscheint
„📍 In berechneter Zugbahn" nur, wenn die Zugbahn die dominierende Risikoquelle ist.


**Wolkentop im Tooltip:**
Beim Hovern über eine Risikofläche wird neben SHIP, CAPE, LI, CIN, PW und
Blitzanzahl auch die **maximale Wolkenoberkante** des Bereichs angezeigt
(in km MSL). Der Wert ist das Maximum aus:
- EUMETView IR108-Ableitung (nächster Atmosphären-Snapshot-Gitterpunkt)
- `cloud_top_height_msl` der nächstliegenden Sturmzelle (≤ 60 km)

| Anzeige | Klassifikation |
|---------|----------------|
| > 9.000 m | sehr hoch (Cb-Niveau) |
| 7.000 – 9.000 m | hoch |
| 5.000 – 7.000 m | mittel |
| < 5.000 m | tief |

Der Wert wird in der Tooltip-Anzeige in Metern (m MSL) mit Tausender-Trennpunkt dargestellt
(Beispiel: `9.846 m`). IR-Vorläufer-Tooltips zeigen die Wolkenhöhe ebenfalls in Metern.

## 4.3 Live-Daten (`/live`)

Tabelle aller aktuell erkannten Zellen mit allen ML-Features: Position, Geschwindigkeit, CAPE, Wolkenhöhe, Blitze, Optical-Flow, AROME-Werte, Hagelwahrscheinlichkeit, Windscherung.

## 4.4 Datensatz (`/data`)

Statistiken über die gesammelten Trainingsdaten: Anzahl Samples pro Horizont, Feature-Vollständigkeit, letztes Dataset-Rebuild.

## 4.5 Atmosphäre (`/atmosphaere`) [NEU]

Großwetterlage-Snapshot für Kärnten: 500-hPa-Geopotential, Steuerströmung, AROME-Gitterpunktwerte (T, Taupunkt, Windböen, Lifted Index, Gefriergrenze), stratiforme Niederschlagsumgebung. Wird alle 30 Minuten aktualisiert.
Die Titelzeile zeigt **Lokalzeit** (keine UTC-Umrechnung nötig) sowie
einen Countdown bis zur nächsten automatischen Aktualisierung. Das Intervall
(Standard: 30 min) ist über Admin-Panel → Konfiguration →
`ATMOSPHERIC_SNAPSHOT_INTERVAL_MIN` zur Laufzeit änderbar.

## 4.6 Orte (`/locations`)

Definition von Überwachungsorten mit Umkreis (km). Durchquerungsanzeige in der Farbe des jeweiligen Vorhersage-Horizonts.

## 4.7 Schwellwerte (`/thresholds`)

HSV-Farbschwellwerte für die Zellerkennung (Gewitterzellen, moderate Zellen, Minimum-Intensität). Änderungen wirken sofort auf den nächsten Live-Loop-Zyklus.

## 4.8 Horizonte (`/horizons`)

Konfiguration der 5 Vorhersage-Zeiträume (default: 10/20/30/40/60 min) und deren Pfeilfarben.

### Vorwarnzeit (Alarm-Schwelle)

| Parameter | Default | Beschreibung |
|---|---|---|
| `WARN_MAX_HORIZON_MIN` | 20 min | E-Mail/WhatsApp-Alarm wird nur gesendet wenn der nächste berechnete Eintreffzeitpunkt ≤ diesem Wert liegt |

**Verhalten:**
- Zelle ist **bereits im Ort** (Horizont 0) → Alarm **immer sofort**, unabhängig von dieser Einstellung
- Frühester Forecast-Horizont ≤ Vorwarnzeit → Alarm wird gesendet
- Frühester Forecast-Horizont > Vorwarnzeit → kein Alarm (Zelle noch zu weit entfernt)

**Beispiel:** Vorwarnzeit = 20 min, Horizonte [30, 40] treffen Ort → kein Alarm.
Sobald auch Horizont 20 (oder 10) trifft → Alarm.

Das Orts-Popup auf der Karte zeigt immer nur den **frühesten** treffenden Horizont.
Treffen mehrere Horizonte wird die Anzahl weiterer Horizonte in grau angezeigt.

## 4.9 Training (`/training`)

Manueller Trainings-Trigger für alle Modelle, Anzeige des letzten Trainingszeitstempels und des `LOCAL_TRAINING`-Status.

## 4.10 Konfiguration (`/config`)

Vollständige JSON-Konfiguration direkt editieren (fortgeschrittene Benutzer). Vorsicht: fehlerhafte JSON bricht die Konfiguration.

## 4.11 Modell-Fortschritt (`/progress`)

Lernkurven (Loss über Epochen) für LSTM und ConvLSTM als Recharts-Grafik.

## 4.12 Genauigkeit (`/accuracy`)

Closed-Loop-Verifikation: MAE, Hit-Rate und durchschnittliche Abweichung pro Horizont über einstellbaren Zeitraum.

## 4.13 Logs (`/logs`)

Anzeige der letzten N Zeilen des System-Logs, API-Fehler-Log, API-Request-Zähler pro Tag und externer Schnittstelle.

## 4.14 KI-Analyse (`/ai-analysis`) [NEU]

Tägliche automatische KI-Analyse des Systemzustands via Claude API. Zeigt priorisierte Handlungsempfehlungen (CRITICAL/HIGH/MEDIUM/LOW). Interaktiver Chat-Bereich für Fragen an die KI.

## 4.15 Vollbild-Karte (`/karte`) [NEU]

Öffentliche Seite ohne Admin-Authentifizierung. Zeigt nur die Leaflet-Karte im Vollbild — geeignet für Einbindung auf externen Displays oder Websites.

---

# 5 Externe Datenquellen und APIs

| API / Dienst | URL | Update-Intervall | TTL Cache | Bemerkung |
|---|---|---:|---:|---|
| ARSO INCA si0zm Radar | `meteo.arso.gov.si/...` | 5 Min | If-Modified-Since | KMZ, öffentlich, kein Key |
| Open-Meteo AROME icon_d2 | `api.open-meteo.com/v1/forecast` | 3 h (Modell-Run) | 30 Min | 10000 Req/Tag (Free). Bulk-Query! |
| Open-Meteo 700 hPa / 300 hPa / 500 hPa | `api.open-meteo.com/v1/forecast` | 6 h (Modell-Run) | 60 Min | Höhenwind 700+300 hPa, Geopotential 300 hPa, Großwetterlage. Bulk-Query! |
| GeoSphere CAPE | `dataset.api.hub.geosphere.at/v1/grid/forecast/nwp-v1-1h-2500m` | 3 h | 30 Min | Österreichischer WD, kein Key |
| GeoSphere TAWES | `dataset.api.hub.geosphere.at/v1/station/current/tawes-v1-10min` | 10 Min | 10 Min | Stationsdaten Kärnten (31 Stationen) |
| GeoSphere Nowcast | `dataset.api.hub.geosphere.at/v1/timeseries/forecast/nowcast-v1-15min-1km` | 15 Min | 12 Min | Niederschlag- und Böen-Nowcast |
| EUMETView MSG IR108 | `view.eumetsat.int/geoserver/...` | 15 Min | 10 Min | Satellit-WMS für Wolkenhöhe (TIFF) |
| Blitzortung | `data.blitzortung.org/Data/Protected/...` | 1 Min | 60 s | Account nötig, HTTP Basic-Auth |
| Copernicus DEM 30m | `copernicus-dem-30m.s3.amazonaws.com` | einmalig | lokal gecacht | 3 Kacheln (E013/E014/E015), ~800 MB |
| Claude API (Anthropic) | `api.anthropic.com` | täglich 06:00 | — | KI-Analyse, nur wenn aktiviert |

> **Hinweis:** Alle API-TTLs sind über `runtime_overrides.json` überschreibbar. Die Request-Zähler pro Tag und Schnittstelle sind im Admin-Panel unter Logs sichtbar.

> **Achtung:** `lightningmaps.org` wird NICHT verwendet (inoffiziell). Blitzdaten kommen ausschließlich über Blitzortung.org (HTTP Basic-Auth).

---

# 6 ML-Pipeline

## 6.1 Modelle

| Modell | Datei | Aufgabe | Horizonte |
|---|---|---|---|
| LightGBM (Punkt) | `model_training.py` | Mittelpunkt-Vorhersage (lat/lon) | 10/20/30/40/60 min |
| LightGBM (Quantile) | `model_training.py` | Unsicherheits-Ellipsen (q10/q90) | 10/20/30/40/60 min |
| LSTM | `model_training.py` | Zeitreihen-basierte Punkt-Vorhersage | 10/20/30/40/60 min |
| ConvLSTM | `radar_convlstm.py` | Pixel-basierte Radarbild-Vorhersage | 1 Horizont |
| U-Net (geplant) | `hailo_inference.py` | Vollständige Radarbild-Nowcasting | Phase B |

Alle Vorhersagen erfolgen als Regression (Zielwert = Koordinate in Grad). Liegt kein trainiertes Modell vor, wird automatisch ein kinematisches Fallback (letzte bekannte Geschwindigkeit) verwendet.

## 6.2 Features (vollständige Liste)

Das ML-Modell verwendet folgende Feature-Gruppen. Gesamtanzahl wird automatisch aus `config.py` berechnet (`ML_NUM_FEATURES`).

| Feature-Gruppe | Features | Quelle |
|---|---|---|
| Zellgeometrie & Kinematik | `x`, `y`, `vx`, `vy`, `size`, `area`, `eccentricity`, `core_ratio`, `trend` | Kalman-Tracker |
| Höhenwind 700 hPa | `wind_speed_700hPa`, `wind_dir_cos`, `wind_dir_sin` | Open-Meteo icon_global |
| Thermodynamik | `cape`, `cloud_top_height_msl` | GeoSphere AROME / EUMETView |
| Topographie (Copernicus DEM) | `dem_elevation_m`, `dem_slope_toward_cell`, `dem_barrier_ahead` | Copernicus DEM 30m |
| Blitze | `lightning_count_10km` | Blitzortung.org |
| Optical Flow [NEU] | `of_vx`, `of_vy`, `of_speed`, `of_divergence` | pysteps Lucas-Kanade |
| AROME icon_d2 Gitterpunkt [NEU] | `arome_t2m`, `arome_td2m`, `arome_ff10m`, `arome_dd_cos`, `arome_dd_sin`, `arome_li`, `arome_fl_height` | Open-Meteo icon_d2 |
| Stratiforme Umgebung [NEU] | `strat_area_px`, `strat_intensity_mean`, `strat_dbz_gradient` | HSV-Segmentierung |
| Talkanalisierung [NEU] | `valley_alignment`, `valley_distance_km`, `valley_confinement` | Orographisches Modul |
| Großwetterlage 500 hPa [NEU] | `z500_dam`, `wind_500_speed`, `wind_500_dir_cos`, `wind_500_dir_sin` | Open-Meteo icon_global |
| Orographische Risk-Scores [NEU] | `terrain_blocking_score`, `orographic_lift_score`, `stationary_risk` | Orographisches Modul |
| Windscherung [NEU] | `wind_shear_speed`, `wind_shear_dir_cos`, `wind_shear_dir_sin` | Open-Meteo (10m + 700 hPa) |
| Hagelindikator [NEU] | `hail_prob` | Heuristik (CAPE + Schichtung + Blitze) |
| GeoSphere-Nowcast [NEU] | `nowcast_rr_mm15`, `nowcast_ffx_kmh`, `nowcast_rain_rate_1h` | GeoSphere Nowcast API |
| Stationsdaten [NEU] | `RR`, `DD`, `FF`, `FFX`, `GLOW`, `P`, `RF`, `TL`, `TP` | GeoSphere TAWES (31 Stationen) |
| Zeit | `hour_sin`, `hour_cos`, `month_sin`, `month_cos` | Systemzeit |

---

# 30 NEU: IR-Sat Pre-Convection Features (Phase E)

**Module:** `ir_cell_detection.py`, `ir_cell_tracking.py`
**Datenquelle:** EUMETView MSG IR108 TIFF (bereits gecacht — kein neuer API-Call)

Das System erkennt konvektive Wolken-Cluster (BT < 230 K) aus dem gecachten
Satellitenbild und trackt sie als eigenständige Objekte. Jede Radar-Zelle
bekommt die Features der nächstgelegenen IR-Cell zugeordnet (≤ 40 km).

| Feature | Einheit | Beschreibung |
|---|---|---|
| `bt_min_k` | K | Kältestes Pixel der IR-Cell — Maß für Wolkenhöhe |
| `bt_mean_k` | K | Mittlere Brightness Temperature der IR-Cell |
| `bt_trend_k_per_min` | K/min | BT-Änderungsrate — negativ = Zelle wächst |
| `cloud_age_min` | min | Alter des IR-Tracklets seit Erstdetektierung |
| `anvil_extension_km` | km | Geschätzte Anvil-Ausdehnung |
| `overshooting_top` | 0/1 | 1.0 wenn BT < 215 K (Cb-Turm bricht Tropopause durch) |
| `ir_only_precursor` | 0/1 | 1.0 wenn IR-Cell ohne Radar-Echo (Vorläufer-Signal) |
| `wind_speed_300hPa` | km/h | Höhenwind 300 hPa — steuert Anvil-Drift |
| `wind_dir_300_cos` | — | cos(Windrichtung 300 hPa) |
| `wind_dir_300_sin` | — | sin(Windrichtung 300 hPa) |

### CB > 10.000: Farbkodierung

| Darstellung | Bedeutung |
|---|---|
| **Lila/Violett** (Füllung + Rand gestrichelt) | Konvektiver Wolkentop BT < 230 K (≈ > 9.800 m MSL) |
| **Rot** (Füllung) + Lila Rand | Overshooting Top: BT < 215 K (≈ > 12.300 m MSL) — Cb-Turm durchstößt die Tropopause, starker Hagel-Prädiktor |

Die Markergröße skaliert mit der detektierten Cluster-Fläche (min. 6 px, max. 20 px Bildschirmradius).

> **Vorlaufzeit:** Konvektive Wolken sind im IR 15–30 min früher sichtbar als
> im Radar. `bt_trend_k_per_min < -1.5` signalisiert rapide Vertiefung und
> erhöht `intensification_prob` automatisch über das ML-Modell.
> `overshooting_top = 1.0` ist ein starker Hagel-Prädiktor (ergänzt `hail_prob2`).

### IR-Vorläufer: Definiton der Erkennungsschwelle

Die Erkennung von IR-Vorläufer-Wolken basiert auf der Brightness Temperature
des MSG IR108-Satelliten. Die Schwellwerte sind in `config.py` definiert und
können zur Laufzeit über `runtime_overrides.json` überschrieben werden:

| Parameter | Wert | Physikalische Bedeutung |
|-----------|------|------------------------|
| `IR_CONVECTION_BT_THRESHOLD_K` | **230 K** | BT < 230 K → konvektiver Wolkentop erkannt (~9.800 m MSL) |
| `IR_OVERSHOOTING_TOP_BT_K` | **215 K** | BT < 215 K → Overshooting Top (Cb-Turm bricht Tropopause) |
| `IR_MIN_CELL_AREA_PX` | 30 Pixel | Mindestgröße eines IR-Clusters (~15×15 km) |

**Umrechnung BT → Höhe:**
```
h [m] ≈ (T_Oberfläche − BT_Schwelle) / LAPSE_RATE + Geländehöhe
h ≈ (290 K − 230 K) / 0,0065 K/m + 600 m ≈ 9.846 m MSL
```
Der adaptive Schwellwert in `cloud_height_from_eumetview.py`
(265/260/255 K je nach Tageszeit) dient ausschließlich der
Hintergrund-Maskierung im WMS-TIFF und **nicht** der IR-Vorläufer-Erkennung.

> **Hinweis:** `[NEU]` = nach v1.0 eingeführt. Bei Feature-Änderungen müssen Modelle neu trainiert werden.

## 6.3 Training-Zeitplan

| Job | Standard-Zeitplan | Konfigurierbar via |
|---|---|---|
| Dataset-Rebuild | stündlich | `DATASET_REBUILD_INTERVAL_MIN` |
| LightGBM/LSTM Retrain (Intervall) | alle 6 h | `retrain_interval_hours` |
| LightGBM/LSTM Retrain (Nightly) | täglich 03:00 | `retrain_cron_hour` / `retrain_cron_minute` |
| ConvLSTM Retrain | montags 02:00 | `convlstm_cron_*` |
| Genauigkeits-Evaluation | stündlich | — |
| KI-Analyse | täglich 06:00 | `AI_ANALYSIS_CONFIG.cron_hour` |
| Daten-Cleanup | täglich 04:30 | `DATA_CLEANUP_CRON_HOUR` / `DATA_CLEANUP_CRON_MINUTE` |

**Bedeutung der Einstellungen:**

| Feld | Bedeutung | Default |
|---|---|---|
| Datensatz-Rebuild (Min.) | Intervall in Minuten, in dem der ML-Datensatz aus den gesammelten Radar-Frames neu aufgebaut wird | 60 |
| Retrain-Interval (Stunden) | LightGBM/LSTM werden zusätzlich zum Nightly-Retrain alle N Stunden neu trainiert | 6 |
| Nightly Retrain Stunde/Minute | Uhrzeit für den täglichen LightGBM/LSTM-Retrain | 03:00 |
| ConvLSTM Tag | Wochentag für das wöchentliche ConvLSTM-Training (Radar-Bildfolgen-Modell) | Montag |
| ConvLSTM Stunde/Minute | Uhrzeit für den wöchentlichen ConvLSTM-Trainingslauf | 02:00 |

> **Hinweis:** Änderungen werden erst nach Neustart des `wetterprojekt-scheduler`-Dienstes aktiv:
> `sudo systemctl restart wetterprojekt-scheduler`

---

# 7 Vorhersage-Verifikation (Closed-Loop)

Das System vergleicht nach Ablauf jedes Vorhersage-Horizonts die vorhergesagte Position mit der tatsächlich beobachteten. Die Ergebnisse werden in `train_data/evaluation/` als JSONL gespeichert.

| Parameter | Wert | Bedeutung |
|---|---:|---|
| `VERIFICATION_TOLERANCE_KM` | 5 km | Treffer wenn tatsächliche Zelle ≤ 5 km von Vorhersage |
| `VERIFICATION_TIME_TOLERANCE_S` | 90 s | Zeitfenster für Frame-Suche (ARSO liefert alle 2–5 min) |
| `VERIFICATION_MAX_SEARCH_RADIUS_KM` | 25 km | Suchradius für Nearest-Neighbor-Match |

**Verifikations-Buckets (seit v1.2)**

Jeder Eintrag in der API-Antwort `/api/accuracy` enthält zusätzlich:

| Feld | Bedeutung |
|---|---|
| `verified` | Anzahl Vorhersagen, für die ein tatsächlicher Ziel-Frame **und** eine matchende Zelle gefunden wurden — fließt in `mae_km`, `rmse_km`, `mae_px`, `hit_rate` ein. |
| `missed` | Ziel-Frame ok, aber keine matchende Zelle im Suchradius. |
| `no_target_frame` | Kein Frame innerhalb `VERIFICATION_TIME_TOLERANCE_S` vorhanden — z. B. weil ARSO-Download fehlte. |
| `id_lost` | Reserviert für Zellen, deren ID im Ziel-Frame nicht mehr existierte (wird in einer späteren Erweiterung gefüllt). |

Die Hit-Rate wird nur über `verified` berechnet — `no_target_frame`-Fälle verzerren die Statistik nicht mehr.

Im Admin-Panel unter Genauigkeit ist die durchschnittliche Abweichung (MAE) und Hit-Rate pro Horizont über einen einstellbaren Zeitraum grafisch dargestellt.

---

# 8 KMZ-Export

Nach jedem Live-Loop-Zyklus wird eine `forecast.kmz`-Datei erzeugt und per FTP hochgeladen. Sie kann direkt in Google Earth, OziExplorer oder kompatible Kartensoftware importiert werden.

Die erzeugte `forecast.kmz` enthält ab v1.2 vier separat schaltbare Ordner:

| Ordner | Inhalt |
|---|---|
| **Aktuelle Zellen** | Polygon-Konturen aller im aktuellen Frame erkannten Sturmzellen, Mittelpunkt-Marker (rot) mit Zell-ID. |
| **Forecast +Hmin** (pro Horizont) | Punkt-Marker und Pfeil-Linie vom aktuellen Zellort zur prognostizierten Position, jeweils in der Horizon-Farbe aus dem Admin-Panel. Linienstärke und Strichmuster werden aus `FORECAST_ARROW_STYLE` übernommen. |
| **Unsicherheit +Hmin** (pro Horizont) | q10/q90-Ellipse um den Vorhersagepunkt — visualisiert die Streuung der ML-Quantil-Vorhersage. |
| **Betroffene Orte** | Locations, deren Radius im aktuellen Zyklus oder im Forecast getroffen wird. Marker-Farbe = Farbe des verantwortlichen Horizonts. Hover-Beschreibung enthält Treffertyp (current / slow_approach / forecast), Cell-ID, Distanz und Geschwindigkeit. |

> **Hinweis:** Die KMZ wird in jedem Live-Loop-Zyklus zweimal geschrieben — einmal nach der Forecast-Berechnung (ohne Orte) und einmal nach der Locations-Auswertung (vollständig). Die hochgeladene Variante ist immer die vollständige.

> **Historische Daten:** Die KMZ enthält ausschließlich Daten des aktuellen Zyklus. Historie wird nicht miterzeugt.

## 8.1 KMZ herunterladen

Über den Button **📥 KMZ** unten rechts auf der Karte kann die zuletzt erzeugte
`forecast.kmz` direkt heruntergeladen werden. Die Datei wird nach jedem
Live-Loop-Zyklus automatisch aktualisiert.

Alternativ steht der API-Endpunkt zur Verfügung:
GET /api/export/forecast.kmz

---

# 9 NEU: Erweiterungen nach v1.0 — Übersicht

Die folgende Tabelle fasst alle nach Version v1.0 eingeführten Erweiterungen zusammen. Die nachfolgenden Kapitel 10–23 beschreiben jede Erweiterung im Detail.

| Kapitel | Erweiterung | Datei(en) | Phase |
|---:|---|---|---|
| 10 | Optical Flow (pysteps Lucas-Kanade) | `optical_flow_features.py` | A |
| 11 | AROME icon_d2 Gitterpunkt-Wetterdaten | `fetch_arome_openmeteo.py` | A |
| 12 | Erweitertes DEM (3 Kacheln, Talkanalisierung, 500-hPa) | `orographic_module.py`, `fetch_synoptic_features.py` | A |
| 13 | Windscherung + Hagelindikator | `main.py`, `config.py` | A |
| 14 | Atmosphären-Seite + Großwetterlage 500 hPa | `Atmosphaere.jsx`, `fetch_synoptic_features.py` | A |
| 15 | GeoSphere TAWES + Nowcast-Daten | `fetch_geosphere_nowcast.py`, `fetch_tawes_gust.py` | A |
| 16 | E-Mail-Benachrichtigungen (SMTP) | `email_notifier.py`, `main.py` | A |
| 17 | Daten-Rotation / Cleanup | `cleanup_old_data.py`, `scheduler.py` | A |
| 18 | Disk-Monitoring im Dashboard | `app.py`, `Dashboard.jsx` | A |
| 19 | Admin-Panel Authentifizierung (nginx) | `install.sh` | A |
| 20 | Adaptiver Loop-Intervall | `main.py`, `config.py` | A |
| 21 | LOCAL_TRAINING-Flag | `config.py`, `scheduler.py`, `install.sh` | A |
| 22 | API-Request-Statistik | `app.py`, `Logs.jsx` | A |
| 23 | KI-Analyse Chat (daily_analyzer.py) | `daily_analyzer.py`, `AiSuggestions.jsx` | A |
| 24 | Antwortzeit (duration_ms) in API-Statistik | `debug_utils.py`, alle API-Module, `Dashboard.jsx` | B |
| 25 | KMZ-Download-Button auf Karte | `app.py`, `MapView.jsx` | B |
| 26 | Timestamp-basierte Trainingsziele (dataset_builder) | `dataset_builder.py` | B |

---

# 10 NEU: Optical Flow (pysteps Lucas-Kanade)

**Modul:** `optical_flow_features.py`  
**Bibliothek:** `pysteps`

Zwischen zwei aufeinanderfolgenden Radarbildern wird mit dem Lucas-Kanade-Algorithmus ein dichtes Optical-Flow-Feld berechnet. Jedem erkannten Sturmzell-Objekt wird der lokale Bewegungsvektor am Zell-Mittelpunkt zugewiesen. Dies ermöglicht dem ML-Modell zu erkennen, ob sich ein Niederschlagsfeld stärker oder schwächer bewegt als der Kalman-Schätzer, und ob das Feld lokal divergiert (Auseinanderfall) oder konvergiert (Intensivierung).

| Feature | Einheit | Bedeutung |
|---|---|---|
| `of_vx` | px/Frame | Flow-Vektor x am Objektzentrum (auf Original-Pixeleinheiten skaliert) |
| `of_vy` | px/Frame | Flow-Vektor y am Objektzentrum |
| `of_speed` | px/Frame | Betrag des Flow-Vektors (Betrag aus vx/vy) |
| `of_divergence` | 1/Frame | Lokale Divergenz (∂u/∂x + ∂v/∂y), positiv = divergent |
| `of_available` | 0/1 | Fallback-Flag: 0 = kein Flow verfügbar (fehlendes Bild) |

> **Hinweis:** Fällt `pysteps` aus oder ein Bild fehlt, werden alle OF-Features auf 0 gesetzt (`of_available=0`). Das Modell lernt dies als „fehlend“ und verliert keine Trainingsdaten.

---

# 11 NEU: AROME icon_d2 Gitterpunkt-Wetterdaten

**Modul:** `fetch_arome_openmeteo.py`  
**API:** Open-Meteo icon_d2 (2,2 km Gitter)

Für jede erkannte Sturmzelle werden AROME-Gitterpunkt-Wetterdaten direkt auf dem Zell-Mittelpunkt abgerufen. Um das API-Limit (10.000 Requests/Tag) nicht zu überschreiten, werden ALLE Zellen in einem einzigen Bulk-Request abgefragt (komma-separierte Koordinaten). Der Cache-TTL beträgt 30 Minuten.

| Feature | Einheit | Beschreibung |
|---|---|---|
| `arome_t2m` | °C | Temperatur 2 m über Grund |
| `arome_td2m` | °C | Taupunkt 2 m (Feuchtigkeitsindikator) |
| `arome_ff10m` | km/h | Windgeschwindigkeit 10 m |
| `arome_dd_cos` | — | cos(Windrichtung 10 m) — zyklisch kodiert |
| `arome_dd_sin` | — | sin(Windrichtung 10 m) — zyklisch kodiert |
| `arome_li` | °C | Lifted Index (negativ = konvektiv instabil) |
| `arome_fl_height` | m | Gefriergrenze über MSL |

> Der Lifted Index ist ein wichtiger Konvektions-Indikator: Werte unter -4°C signalisieren starke Gewitterneigung.

---

# 12 NEU: Erweiterte Geländemodell-Features (DEM)

**Modul:** `orographic_module.py`  
**Datenquelle:** Copernicus DEM 30m

Das Geländemodell deckt ganz Kärnten mit 3 Kacheln ab (E013N46, E014N46, E015N46). Neben den bisherigen DEM-Basis-Features wurden folgende orographische Features neu eingeführt, die für die charakteristische Gewitter-Kanalisierung in Kärntner Tälern (Drautal, Lavanttal, Gailtal) besonders relevant sind:

| Feature | Beschreibung |
|---|---|
| `dem_barrier_ahead` | Höhendifferenz 10–20 km voraus in Bewegungsrichtung (m, positiv = Barriere). Zeigt ob die Zelle auf ein Gebirge zufährt. |
| `valley_alignment` | `|cos(Winkel)|` zwischen Zellbewegung und Talachse (0–1). 1 = Zelle bewegt sich talentlang, 0 = Zelle überquert Tal. |
| `valley_distance_km` | Abstand der Zelle von der nächstgelegenen Talmitte (km). |
| `valley_confinement` | 1.0 wenn Zelle im Talquerschnitt liegt, sonst 0.0. |
| `terrain_blocking_score` | 0–1: Gelände blockiert wahrscheinlich die Zugbahn. |
| `orographic_lift_score` | 0–1: Staulage / orographische Hebung an der Zellposition. |
| `stationary_risk` | 0–1: Gesamtrisiko dass die Zelle stationär bleibt (Kombination aus Blockierung, Talkanalisierung, CAPE). |

> **Hinweis:** Das Copernicus DEM wird nur einmalig beim Full-Install heruntergeladen (~800 MB) und lokal gecacht. Es wird bei Upgrades NICHT gelöscht.

---

# 13 NEU: Windscherung und Hagelindikator

## 13.1 Windscherung

Die vertikale Windscherung wird als Differenzvektor zwischen dem 10-m-Bodenwind (AROME icon_d2) und dem 700-hPa-Höhenwind (Open-Meteo) berechnet:

| Feature | Einheit | Beschreibung |
|---|---|---|
| `wind_shear_speed` | km/h | Betrag des Scherungsvektors (10m→700hPa) |
| `wind_shear_dir_cos` | — | cos(Richtung des Scherungsvektors) |
| `wind_shear_dir_sin` | — | sin(Richtung des Scherungsvektors) |

> Hohe Windscherung (> 30 km/h über 700 m) ist ein wichtiger Indikator für organisierte Konvektion und Superzellen-Potenzial.

## 13.2 Hagelindikator (`hail_prob`)

Die Hagelwahrscheinlichkeit wird pro Zelle heuristisch aus folgenden Faktoren berechnet (kombinierte Gewichtung, Ergebnis 0.0–1.0):

- CAPE > 1000 J/kg (hohe Aufstiegsenergie)
- Lifted Index < -3°C (Instabilität der Atmosphäre)
- Blitze > 3 in 10 km (aktive Konvektion)
- Gefriergrenze < 3500 m (Hagel erreicht Boden)
- Windscherung > 20 km/h (Hagel-Umlaufstrom)
- Zellgröße und Core-Ratio (größere Kerne = höheres Potenzial)

| Parameter | Standard | Beschreibung |
|---|---:|---|
| `HAIL_WARN_THRESHOLD` | 0.45 | Auslösung Hagelwarnung wenn `hail_prob ≥ Wert` |
| `STATIONARY_RISK_MARKER_THRESHOLD` | 0.60 | Anzeige ⊕-Marker wenn `stationary_risk ≥ Wert` |
| `GUST_WARN_KMH` | 60 km/h | Sturmböenwarnung ab diesem Wert (Nowcast oder TAWES) |
| `HEAVY_RAIN_WARN_MM_PER_H` | 25 mm/h | Starkregenwarnungs-Schwellwert |

In der Leaflet-Karte erscheint bei Hagelwarnung ein roter gestrichelter Rahmen um die betroffene Zelle mit dem Prozentwert. Bei Stationärrisiko erscheint ein ⊕-Symbol in Amber-Farbe.

---

# 14 NEU: Atmosphären-Seite und Großwetterlage 500 hPa

**Seite:** `/atmosphaere`  
**Modul:** `fetch_synoptic_features.py`

Die neue Atmosphären-Seite zeigt einen aktuellen Großwetterlage-Snapshot für Kärnten. Daten werden alle 30 Minuten aktualisiert (`ATMOSPHERIC_SNAPSHOT_INTERVAL_MIN = 30`), unabhängig davon ob Sturmzellen erkannt wurden.

| Anzeige-Karte | Datenquelle | Beschreibung |
|---|---|---|
| 500-hPa-Geopotential (dam) | Open-Meteo icon_global | Steuerströmung für Großwetterlage über Mitteleuropa |
| Steuerströmungsvektor 500 hPa | Open-Meteo icon_global | Windgeschwindigkeit und -richtung auf 500 hPa |
| AROME Bodenfelder | Open-Meteo icon_d2 | T2m, Taupunkt, Windgeschwindigkeit, Böen |
| Lifted Index | Open-Meteo icon_d2 | Instabilitäts-Indikator für Konvektion |
| Gefriergrenze | Open-Meteo icon_d2 | Höhe der 0°C-Linie über MSL |
| Stratiforme Niederschlagsumgebung | HSV-Segmentierung | Fläche und mittlere Intensität des Stratiform-Echobands |

---

# 15 NEU: GeoSphere TAWES und Nowcast-Daten

## 15.1 TAWES (Stationsdaten)

**Modul:** `fetch_tawes_gust.py`  
**API:** GeoSphere TAWES v1 (`tawes-v1-10min`)

Von 31 Kärntner Wetterstationen werden alle 10 Minuten folgende Parameter abgefragt: RR (Niederschlag), DD/FF/FFX (Wind/Böen), P (Luftdruck), RF (Feuchte), TL/TP (Temperatur/Taupunkt). Dem Live-Loop wird über `max_gust_near()` der maximale gemessene Böenwert im 30-km-Umkreis jeder Zelle zugewiesen (`tawes_max_gust_kmh`).

## 15.2 GeoSphere Nowcast

**Modul:** `fetch_geosphere_nowcast.py`  
**API:** `nowcast-v1-15min-1km`

Der GeoSphere-Nowcast liefert kurzzeitige Vorhersagen für Niederschlag (mm/15min), Böen (km/h) und stündlichen Niederschlag pro Gitterpunkt. Diese werden als ML-Features eingesetzt (`nowcast_rr_mm15`, `nowcast_ffx_kmh`, `nowcast_rain_rate_1h`) und für die Böenwarnung herangezogen.

> **Hinweis:** Cache-TTL Nowcast: 12 Minuten (Intervall 15 Min). Cache-TTL TAWES: 10 Minuten (Intervall 10 Min).

---

# 16 NEU: E-Mail-Benachrichtigungen

**Modul:** `email_notifier.py`
**Protokoll:** SMTP mit STARTTLS (Standard-Bibliothek, keine Abhängigkeiten)

Bei Ortsdurchquerungen durch Sturmzellen wird automatisch eine HTML-Warnmail
an konfigurierte Empfaenger gesendet. Pro Ort koennen mehrere
E-Mail-Adressen durch ";" getrennt angegeben werden.

| Ereignis | Betreff | Inhalt |
|---|---|---|
| Neue Zelle trifft Ort | `⚡ GEWITTERWARNUNG {Ort}` | Tabelle mit Horizont, Zell-ID, Distanz, Geschwindigkeit + Link zur Karte |
| Zelle verlaesst Ort | `✅ Entwarnung {Ort}` | Kurzmeldung + Link zur Karte |

Der E-Mail-Body enthaelt immer einen direkten Link zur oeffentlichen Karte:
`http://blasolar.ddns.net:81/karte`

**Cooldown** verhindert Mail-Flut: max. 1 Warnung pro Ort / 15 Minuten,
max. 1 Entwarnung pro Ort / 5 Minuten (Reset bei Service-Neustart).

**Konfiguration in `.env`:**
```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=deine-adresse@gmail.com
SMTP_PASS=app-passwort
SMTP_FROM=WetterExtended <deine-adresse@gmail.com>
```

> **Hinweis fuer Gmail:** Unter "Google-Konto → Sicherheit" ein App-Passwort
> generieren (2FA muss aktiviert sein). Das normale Gmail-Passwort
> funktioniert NICHT fuer SMTP.

**Empfaenger-Konfiguration im Admin-Panel:**
Unter "Orte" kann pro Eintrag ein E-Mail-Feld befuellt werden.
Mehrere Adressen durch Semikolon trennen: `user1@x.at;user2@y.at`

> **Hinweis:** Ist das E-Mail-Feld fuer einen Ort leer oder SMTP nicht
> konfiguriert, wird still uebersprungen — kein Fehler, kein Loop-Abbruch.

---

# 17 NEU: WhatsApp-Benachrichtigungen via CallMeBot

**Modul:** `whatsapp_notifier.py`
**Dienst:** CallMeBot (kostenlos, kein Account / keine WhatsApp Business API nötig)

Parallel zu den E-Mail-Benachrichtigungen können für jeden überwachten Ort
WhatsApp-Nachrichten an beliebig viele Empfänger gesendet werden.

## 17.1 Einrichtung pro Empfänger (einmalig)

Jeder Empfänger muss sich einmalig bei CallMeBot registrieren:

1. WhatsApp öffnen
2. Nachricht an **+34 644 82 17 47** senden: `I allow callmebot to send me messages`
3. CallMeBot antwortet mit dem persönlichen **API-Key**

## 17.2 Konfiguration im Admin-Panel

Auf der Seite **Beobachtete Orte** (`/locations`) gibt es das neue Feld
**„WhatsApp (+Nr:APIKey)"**:

| Feld | Format | Beispiel |
|---|---|---|
| Einzelner Empfänger | `+43NR:APIKEY` | `+4369912345678:abc123` |
| Mehrere Empfänger | Semikolon-getrennt | `+4369912345678:abc123;+431234567:xyz` |

Das Feld ist optional — leer lassen deaktiviert WhatsApp für diesen Ort.
E-Mail und WhatsApp sind unabhängig voneinander konfigurierbar.

## 17.3 Nachrichtentypen

| Ereignis | Nachrichteninhalt |
|---|---|
| Gewitterwarnung | Ortsname, Zeitstempel, Zell-ID, ETA, Distanz, Geschwindigkeit |
| Entwarnung | Ortsname, Zeitstempel, Kurzmeldung |
| Hohes Gewitterrisiko (Stufe 3) | Ortsname, Ursache, Lifted Index, CAPE (falls vorhanden) |

> Nachrichten sind **Klartext** (kein HTML). Emojis werden vermieden, da nicht alle
> Android-Versionen Emojis in automatischen Nachrichten korrekt darstellen.

## 17.4 Konfiguration testen

Auf der Seite **Beobachtete Orte** (`/locations`) erscheint unter jedem
WhatsApp-Eingabefeld ein kleiner **„Test"**-Button:

1. WhatsApp-Feld des gewünschten Orts mit gültigem `+43Nr:APIKey` befüllen
2. **„Test"** klicken — der Button zeigt `...` während gesendet wird
3. Ergebnis direkt in der Zeile:
   - `✓ Gesendet: +43699...` → Konfiguration korrekt
   - `✗ Fehlermeldung` → Nummer oder API-Key prüfen

> **Hinweis:** Der Test umgeht den Cooldown. Es wird eine neutrale
> Bestätigungsnachricht gesendet (kein Gewitterbezug).
> Bei mehreren Empfängern werden alle getestet; zwischen den Sendungen
> wird die CallMeBot-Pause von 5 Sekunden eingehalten.

## 17.5 Cooldown und Rate-Limiting

| Parameter | Wert |
|---|---|
| Cooldown Warnung | 15 Minuten pro Ort |
| Cooldown Entwarnung | 5 Minuten pro Ort |
| Pause zwischen Empfängern | 5 Sekunden (CallMeBot Rate-Limit) |
| Tages-Cooldown Risiko-Stufe-3 | 1× täglich pro Ort (gemeinsam mit E-Mail) |

## 17.6 Verhalten bei Fehlern

Fehler beim WA-Versand (Timeout, CallMeBot nicht erreichbar) werden geloggt
und beeinflussen den Live-Loop **nicht**. WA-Benachrichtigungen sind immer
best-effort — das System läuft auch ohne CallMeBot-Erreichbarkeit stabil weiter.

## 17.7 Keine .env-Variable nötig

Im Gegensatz zu SMTP (E-Mail) oder Twilio (SMS) benötigt CallMeBot keine globale
Konfiguration in `.env`. Alle Verbindungsdaten (Rufnummer + API-Key) sind
**per Ort** in der `LOCATIONS_WATCHLIST` gespeichert.

---

# 17 NEU: Daten-Rotation (`cleanup_old_data.py`)

**Modul:** `cleanup_old_data.py`  
**Scheduler-Job:** täglich 04:30

Ohne Daten-Rotation würden die Trainingsdaten unbegrenzt wachsen und bei intensivem Wetterbetrieb (viele Zellen, kurze Intervalle) nach einigen Monaten die SD-Karte des Raspberry Pi füllen. Der Cleanup-Job löscht alle Dateien die älter als `DATA_RETENTION_DAYS` (default: 90 Tage) sind.

| Parameter | Standard | Beschreibung |
|---|---:|---|
| `DATA_RETENTION_DAYS` | 90 | Maximales Datenalter in Tagen |
| `DATA_CLEANUP_CRON_HOUR` | 4 | Uhrzeit des täglichen Cleanup-Jobs |
| `DATA_CLEANUP_CRON_MINUTE` | 30 | Minute des täglichen Cleanup-Jobs |

Folgende Verzeichnisse werden rotiert:

- `train_data/radar/`
- `train_data/objects/`
- `train_data/weather/`
- `train_data/wind/`
- `train_data/cape/`
- `train_data/lightning/`
- `train_data/ir/`
- `train_data/ir_cells/`
- `train_data/cloud/`
- `train_data/arome/`

Folgende Verzeichnisse werden **nicht** rotiert:

- `train_data/models/` (Modell-Versionierung)
- `train_data/evaluation/` (Genauigkeits-Historie)
- `train_data/dataset/` (aktuelles Dataset)
- `train_data/dem/` (Copernicus DEM, großer Einmal-Download)

---

# 18 NEU: Disk-Monitoring im Dashboard

**API-Endpunkt:** `GET /api/disk`  
**Frontend:** `Dashboard.jsx`

Das Dashboard zeigt eine Statusampel für die Festplattenbelegung:

| Farbe | Zustand | Auslösung |
|---|---|---|
| Grün | Normal | Belegung < 70% |
| Gelb | Warnung | Belegung 70–90% |
| Rot | Kritisch | Belegung > 90% |

Zusätzlich wird der RAM-Auslastungs-Prozentsatz angezeigt (aus `/proc/meminfo`). Bei kritischer Disk-Belegung erscheint ein farbiger Warnbanner im Dashboard-Header.

---

# 19 NEU: Admin-Panel Authentifizierung (nginx)

Das Admin-Panel ist seit dieser Version durch HTTP Basic-Auth geschützt. Die Authentifizierung erfolgt über nginx (nicht über Flask).

| Detail | Wert / Beschreibung |
|---|---|
| Benutzername | `admin` (fest) |
| Passwort | Zufällig generiert bei Erstinstallation (`openssl rand`) |
| Passwort-Speicherort | `.admin_password` im Projektverzeichnis (Modus 600) |
| htpasswd-Datei | `/etc/nginx/.htpasswd` |
| Wiederherstellung | Beim nächsten `install.sh --mode=upgrade` wird `.htpasswd` aus `.admin_password` wiederhergestellt |

Folgende Endpunkte sind **ohne Authentifizierung** erreichbar:

- `/karte` — Vollbild-Karte (nur lesende API-Endpunkte)
- `/assets/` — Frontend-Assets (werden von `/karte` benötigt)
- `/api/objects`
- `/api/forecast`
- `/api/locations`
- `/api/horizons`
- `/api/health`
- `/api/radar_image`
- `/api/radar_bounds`
- `/api/radar_timing`

> **Achtung:** Das Admin-Passwort wird bei der Erstinstallation einmalig im Terminal angezeigt. Notiere es sofort! Es wird in `.admin_password` im Projektverzeichnis gespeichert.

---

# 20 NEU: Adaptiver Loop-Intervall

**Datei:** `main.py`, `config.py`

Der Live-Loop passt seinen Schlaf-Intervall automatisch an die aktuelle Wetter-Situation an. Dies spart Rechenleistung und API-Requests in ruhigen Phasen:

| Zustand | Parameter | Standard | Beschreibung |
|---|---|---:|---|
| Zellen aktiv | `LOOP_INTERVAL_CELLS_S` | 120 s (2 min) | Kurzes Intervall für schnelle Reaktion |
| Keine Zellen | `LOOP_INTERVAL_NO_CELLS_S` | 900 s (15 min) | Langes Intervall spart Ressourcen |
| Atmosphären-Snap | `ATMOSPHERIC_SNAPSHOT_INTERVAL_MIN` | 30 min | Unabhängig von Zellen |

> **Hinweis:** Beide Intervallwerte sind über `runtime_overrides.json` ohne Service-Neustart überschreibbar.

---

# 21 NEU: LOCAL_TRAINING-Flag

**Datei:** `config.py`  
**Parameter:** `LOCAL_TRAINING` (bool, default: `True`)

Dieses Flag bereitet das System für Phase B vor: In Phase B wird ein separater x86-Linux-Rechner das Training übernehmen. Der Pi schaltet dann auf `LOCAL_TRAINING=False` und synchronisiert fertige Modelle per rsync.

| Wert | Verhalten | Phase |
|---|---|---|
| `True` (Default) | Scheduler startet alle Training-Jobs (`retrain`, `rebuild_dataset`, `convlstm`) | Phase A: Pi trainiert selbst |
| `False` | Training-Jobs werden übersprungen. Nur `accuracy_eval`, `ai_analysis` und `data_cleanup` bleiben aktiv. | Phase B: Externer Trainer |

Setzen per `install.sh` oder `runtime_overrides.json`:

```bash
bash install.sh --mode=upgrade --no-training
```

Oder in `runtime_overrides.json`:

```json
{"LOCAL_TRAINING": false}
```

---

# 22 NEU: API-Request-Statistik und Detail-Ansicht

**API-Endpunkte:** `GET /api/api_calls`, `GET /api/api_calls/last`, `GET /api/api_calls/detail`  
**Frontend:** `Dashboard.jsx`, `Logs.jsx`

Jede externe API-Anfrage (ARSO, Open-Meteo, GeoSphere, Blitzortung, EUMETView) wird in einer
lokalen JSONL-Datenbank (`api_call_counts.jsonl`) mit vollständigem Request und Response geloggt.

## 22.1 Dashboard — 24h-Statistiktabelle

Das Dashboard zeigt eine kompakte Statistiktabelle aller externen Schnittstellen der letzten 24 Stunden.

| Spalte | Beschreibung |
|---|---|
| Service | Name der externen Schnittstelle (klickbar — filtert das Detail-Panel unten) |
| Anfragen | Anzahl Requests in den letzten 24h |
| Fehler | Anzahl fehlgeschlagener Requests (rot hervorgehoben) |
| Fehlerrate | Prozentsatz fehlgeschlagener Requests |
| 🌐-Link | Direktlink zur öffentlichen Web-Oberfläche des Datenanbieters |

> **Hinweis:** Die 24h-Zähler zeigen immer den gesamten Zeitraum seit Mitternacht UTC.
> Fehler werden in Rot dargestellt. Eine Fehlerrate > 0 % ist kein Alarm, solange
> der Fallback greift (erkennbar an den API-Gesundheits-Meldungen oben im Dashboard).

## 22.2 Detail-Panel — Letzter API-Request / Response

Unterhalb der Statistiktabelle befindet sich ein separater Card „🔍 Letzter API-Request / Response".

**Service auswählen:** Entweder durch Klick auf eine Tabellenzeile oben, oder über das
Dropdown rechts im Detail-Panel-Header. Beide Steuerelemente sind synchronisiert.

Das Panel zeigt den **letzten gespeicherten Request des gewählten Services** (oder den
letzten beliebigen Request wenn kein Service ausgewählt ist).

### 22.2.1 Meta-Zeile

| Feld | Beschreibung |
|---|---|
| Service | Service-Name |
| Zeit | UTC-Zeitstempel des Requests |
| Status | HTTP-Statuscode (grün = 2xx, orange = 4xx, rot = 5xx) |
| Dauer | Antwortzeit in Millisekunden |
| 🌐 Quelle | Link zur öffentlichen Quelle (falls verfügbar) |

### 22.2.2 Request-Block

Zeigt HTTP-Methode, vollständige URL und Request-Payload (falls vorhanden).
Secrets (API-Keys, Passwörter) werden automatisch mit `***` maskiert.

### 22.2.3 Response-Block

Der Response wird je nach Content-Type unterschiedlich dargestellt:

| Typ | Darstellung |
|---|---|
| JSON (body_json) | Formatiertes, einrückbares JSON-Objekt — kein doppeltes Escaping |
| Text/XML/CSV (body_text) | Direkter Text, scrollbar |
| Binär / KMZ / TIFF (binary) | Metadaten-Box: Content-Type, Dateigröße, SHA-256, lokaler Pfad |

> **Hinweis:** Responses werden **nie gekürzt**. Die vollständige Antwort
> wird gespeichert (außer bei Binärdaten — dort werden nur Metadaten gespeichert).

### 22.2.4 Öffentliche Quellen-Links je Service

| Schnittstelle | Öffentlicher Link |
|---|---|
| GeoSphere TAWES | https://tawes.at/#knt |
| Open-Meteo | https://open-meteo.com/en/docs |
| GeoSphere CAPE/Nowcast | https://dataset.api.hub.geosphere.at/ |
| EUMETView | https://eumetview.eumetsat.int/ |
| Blitzortung | https://www.blitzortung.org/ |

## 22.3 Logs-Seite — Vollständige Request-Liste

Unter **Logs → API-Requests** können die letzten Requests gefiltert nach Service
und Zeitraum eingesehen werden (bis zu 200 Einträge). Diese Ansicht enthält auch
ältere Requests, die im Dashboard-Panel nicht mehr sichtbar sind.

---

# 23 NEU: KI-Analyse Chat (`daily_analyzer.py`)

**Modul:** `daily_analyzer.py`  
**Frontend:** `AiSuggestions.jsx`  
**API:** Claude (Anthropic)

Das System kann täglich automatisch den eigenen Zustand analysieren lassen. Dazu wird ein detaillierter Report (Systemmetriken, letzte erkannte Zellen, Quellcode-Auszüge von GitHub) an die Claude-API gesendet und strukturierte Handlungsempfehlungen zurückerhalten.

## 23.1 Automatische Analyse

Läuft täglich um 06:00 Uhr via Scheduler (`cron_hour=6`). Analysiert:

- Modell-Genauigkeits-Trends der letzten 24 Stunden
- System-Ressourcen (Disk, RAM)
- API-Fehlerquoten und Fehlerdetails
- Qualität des Trainingsdatensatzes
- **Tages-Sturmaktivität** aus `cells_log.jsonl`: Gesamtframes, aktive Frames,
  Peak-Zellzahl mit Zeitpunkt, zusammenhängende Sturm-Zeitfenster, distinct Lineages
- **Orts-Treffer-Aggregat** aus `locations_*.json`: Welche überwachten Orte wurden
  in wie vielen Frames getroffen (Kärnten-weite Gefahrenübersicht für den Tag)
- **Peak-Frames** mit vollständigen Zelldaten (CAPE, Blitzcount, Hagel-Wahrscheinlichkeit,
  Severity-Score, Windscherung) der aktivsten Momente des Tages
- **Fehler-Digest** aus dem systemd-Journal beider `wetterprojekt`-Services:
  deduplizierte Exceptions und Tracebacks der letzten 24 h (Top 10 nach Häufigkeit)
- Quellcode der wichtigsten Dateien (von GitHub)

## 23.2 Interaktiver Chat im Admin-Panel

Unter `/ai-analysis` gibt es zusätzlich einen Chat-Bereich für Fragen an die KI:

- Freie Texteingabe, z.B. „Warum sind die Vorhersagen für 30-min so ungenau?“
- Modell-Auswahl (Claude Sonnet 4, etc.)
- Toggle: Systemmetriken (letzte 24h) einbeziehen
- Toggle: Quellcode einbeziehen (langsamer, aber genauere Code-Analyse)

### Unterstützte Bild-Formate beim KI-Bild-Upload

Für den Bild-Upload an die KI-Analyse werden nur die von der Claude-API
unterstützten Formate akzeptiert: **JPEG, PNG, GIF und WebP**.
Andere Formate (z. B. SVG, HEIC, BMP, TIFF) werden beim Hinzufügen
automatisch übersprungen; eine Hinweismeldung nennt die abgelehnten Dateien.

## 23.3 Konfiguration

| Parameter | Standard | Beschreibung |
|---|---|---|
| `enabled` | `false` | Master-Schalter für automatische tägliche Analyse |
| `cron_hour` | `6` | Uhrzeit des automatischen Analyselaufs |
| `model` | `claude-sonnet-4-20250514` | Verwendetes Claude-Modell |
| `max_tokens` | `1500` | Maximale Antwortlänge in Tokens |
| `since_hours` | `24` | Datenfenster für den Report (letzte N Stunden) |
| `save_suggestions` | `true` | Vorschläge als JSON persistieren |

> **Achtung:** Für die KI-Analyse wird ein gültiger Anthropic-API-Key in der `.env` benötigt:
>
> ```env
> ANTHROPIC_API_KEY=sk-ant-...
> ```
>
> Die KI-Analyse verursacht API-Kosten pro Request.

## 23.8 Polygon-basierte Orts-Treffer mit richtungsabhängigem Wachstum

**`current`:** Abstand Ort → Zell-Polygon-Rand ≤ Ortsradius.

**`forecast`/`slow_approach`:** Das aktuelle Polygon wird zur
vorhergesagten Position verschoben und **richtungsabhängig skaliert:**

```
Vorhergesagtes Polygon bei +h min:
  scale_NS = (half_NS + rate_NS × h) / half_NS
  scale_EW = (half_EW + rate_EW × h) / half_EW  ← unabhängig!

  neuer_Punkt = forecast_Zentrum + scale × (Punkt − aktuelles_Zentrum)
```

`rate_NS` und `rate_EW` (km/min) werden per **linearer Regression** über
die gemessenen N-S- und E-W-Ausdehnungen der letzten Radar-Frames bestimmt.

Beispiel: Zelle dehnt sich nach E aus (+0.12 km/min) und zieht sich N-S
zusammen (−0.08 km/min). Bei +30 min: E-W +3.6 km breiter, N-S −2.4 km
schmaler. Diese asymmetrische Form wird für die Treffererkennung genutzt.

## 23.7 Mobile-Optimierung der Karte (/karte)

Die Vollbild-Karte (`/karte`) wurde für Mobilgeräte optimiert:

- **Touch-Targets:** Alle Checkboxen, Buttons und Labels haben mindestens 44×44px
  (Apple HIG / Material Design Mindestgröße für Touch-Bedienung)
- **Blitz-Dropdown:** Größere Darstellung (16px Schrift), verhindert automatisches
  Zoomen auf iOS beim Antippen
- **Risikozonen-Tooltip:** Schriftgröße von 11px auf 14px erhöht
- **Zell-Popups:** Schriftgröße von 11px auf 14px erhöht
- **Animations-Slider:** Höhe von 18px auf 28px erhöht — leichter bedienbar
- **Navigations-Buttons** (◀ ▶ ⏸): von 36px auf 44px erhöht

## 23.6 Vereinfachte Warn-E-Mail und 2-Frame-Bestätigung

**Warn-E-Mail (seit dieser Version):**
Die Gewitterwarnung zeigt nur noch die wichtigste Information:
_„Zelle ZJSJAGKD trifft in ~10 Minuten (ca. 13:40 Uhr)"_ — keine technische Tabelle mehr.

**2-Frame-Bestätigung bei kinematischer Vorhersage:**
Steht kein ML-Modell zur Verfügung (Forecast-Modus: kinematisch), muss der überwachte Ort
in **2 aufeinanderfolgenden Radar-Frames** (≈ 2–4 Minuten) vom Forecast-Pfad getroffen
werden, bevor eine Warnung ausgelöst wird. Dies verhindert Fehlalarme durch einzelne
unsichere Vorhersage-Ausreißer.

| Forecast-Modus | Auslösung |
|----------------|-----------|
| `ml` | Sofort beim ersten Treffer |
| `kinematic` | Erst bei 2 aufeinanderfolgenden Treffern |

> Wird der Treffer zwischen den beiden Frames unterbrochen, wird der Zähler zurückgesetzt.

## 23.5 E-Mail-Benachrichtigung für alle KI-Antworten

Ab dieser Version wird **jede KI-Antwort** automatisch per E-Mail an die konfigurierte
`report_email`-Adresse gesendet — unabhängig davon, ob die Antwort aus dem interaktiven
Chat, einer Filter-Analyse oder dem täglichen Automatik-Report stammt.

| KI-Typ | Auslöser | E-Mail-Inhalt |
|--------|---------|--------------|
| Interaktiver Chat | Senden im Chat-Fenster | Frage + vollständige Antwort |
| Filter-Analyse (KI) | „KI analysieren" in Filter-Galerie | Anzahl Vorschläge + HSV-Bereiche + Begründung |
| Tägliche Analyse | Automatisch 06:00 / manueller Trigger | Systemstatus + Handlungsempfehlungen |

> **Voraussetzung:** SMTP muss konfiguriert sein (`SMTP_HOST`, `SMTP_USER`, `SMTP_PASS` in `.env`)
> und `AI_ANALYSIS_CONFIG.report_email` muss gesetzt sein.
>
> Fehler beim E-Mail-Versand werden nur geloggt — der KI-Endpunkt gibt trotzdem immer
> die Antwort zurück (kein Fehler für den Benutzer).

## 23.4 Vollständige Konfiguration im KI-Report

Seit dieser Version sendet `build_system_report()` die komplette lokale Konfiguration
an die KI — einschließlich `runtime_overrides.json`. Dadurch kann die KI konkrete
Konfigurations-Empfehlungen machen (z.B. Schwellwerte, Intervalle, Orte).

Folgende Einstellungen werden übermittelt:

| Konfigurationsbereich | Übertragen |
|---|---|
| HSV-Bandeinstellungen (Farb-Schwellwerte) | ✅ |
| Überwachte Orte (LOCATIONS_WATCHLIST) | ✅ |
| ML-Vorhersage-Horizonte | ✅ |
| Warnungsschwellwerte (Hagel, Böen, Regen) | ✅ |
| Loop-Intervalle | ✅ |
| TAWES-Stationsliste | ✅ |
| Aktive runtime_overrides.json | ✅ |
| API-Tokens, Passwörter, Secrets | ❌ Nie (automatisch herausgefiltert) |

> **Datenschutz:** Alle Keys mit den Begriffen TOKEN, KEY, PASS, PASSWORD, SECRET,
> AUTH, CREDENTIAL oder PRIVATE werden automatisch durch `***REDACTED***` ersetzt,
> bevor der Report an die Anthropic-API gesendet wird.

---

# 24 NEU: TAWES-Zugriff konsolidiert (Single-Source-of-Truth)

**Betroffene Dateien:** `weather_api.py`, `fetch_tawes_gust.py`

Vor dieser Version gab es zwei unabhängige TAWES-API-Aufrufe:

| Modul | Stationen | Cache |
|---|---|---|
| `fetch_tawes_gust.py` | 5 Kärntner Stationen (Böen-Fokus) | 10 min TTL ✅ |
| `weather_api.py` | 31 Stationen (alle Parameter) | keiner ❌ |

`weather_api.py` wurde bei jedem Loop-Durchlauf direkt aufgerufen — ohne Cache.
Dies widersprach der Zielvorgabe, unnötige Fremdrequests zu vermeiden und die
10-Minuten-Aktualisierungsintervalle der GeoSphere-TAWES-API zu respektieren.

**Lösung:** `weather_api.py` nutzt nun `api_cache` mit TTL=600s. Der GeoSphere-TAWES-
Server wird maximal alle 10 Minuten angefragt, unabhängig von der Loop-Frequenz.

> **Hinweis:** Die beiden TAWES-Aufrufe existieren weiter parallel, da sie unterschiedliche
> Stationssets und Parameter abrufen. Die Cache-Keys sind unterschiedlich, sodass keine
> Interferenz entsteht.

---

# 24 NEU: Human-in-the-Loop Filter-Verfeinerung

**Modul:** `cell_filters.py`
**Frontend:** `MapView.jsx` (Markieren) · `CellFilters.jsx` (Galerie + KI-Analyse) · `AiSuggestions.jsx` (Shortcut)
**Speicherort:** `train_data/cell_filters/cell_filters.json` + `train_data/cell_filters/polygons/`
**API:** `/api/cell_filters/*`, `/api/analyze_cell_polygon`, `/api/thresholds/add_range`

Das System erlaubt dem Benutzer, vom Algorithmus übersehene Sturmzellen direkt auf der Karte mit einem Polygon zu markieren. Aus dem markierten Bereich extrahiert das System die HSV-Werte, schlägt einen passenden Filter vor und speichert nach Bestätigung sowohl den Filter als auch einen PNG-Ausschnitt der markierten Region. Auf Basis dieser Ausschnitte kann die Claude-API zusätzliche, breitere Filter-Bereiche vorschlagen — die Erkennung wird so iterativ verbessert.

## 24.1 Ablauf am Beispiel

1. **Karte öffnen** unter `/map` und „✏️ Zelle markieren" anklicken.
2. **Polygon zeichnen**: Klick = Punkt setzen, Doppelklick = abschließen, ESC = abbrechen. Vor dem Markieren empfiehlt sich starkes Einzoomen — die Bildqualität für das gespeicherte PNG wird damit besser.
3. **HitL-Dialog**: Das System zeigt die gemessenen HSV-Werte, eine Farbvorschau und einen vorgeschlagenen Filter. Bei Bestätigung wird der Filter aktiviert und ein PNG-Ausschnitt mit Maskenoverlay gespeichert.
4. **Filter-Galerie** (`/cell-filters`): Übersicht aller aktiven und deaktivierten Filter mit Thumbnail, HSV-Range, Quelle und Padding-Slider.
5. **KI-Analyse**: Knopf „🤖 Mit KI analysieren" sendet die letzten 5 PNGs + aktuelle Filter an Claude und erhält Vorschläge für zusätzliche HSV-Bereiche. Vorschläge werden in der Galerie zur einzelnen Annahme oder „Alle übernehmen" angezeigt.

## 24.2 Filter-Galerie

| Element | Funktion |
|---|---|
| Polygon-Thumbnail | Ausschnitt aus dem Radarbild mit gelb umrandeter Markierung |
| HSV-Range | H/S/V-Grenzen des Filters; Klick-Tooltip mit numerischen Werten |
| Quelle | „Manuell" (Polygon), „KI" (Vorschlag übernommen), „Migration" (aus initial config) |
| Aktiv-Toggle | Filter inaktiv schalten ohne zu löschen — Polygon-PNG bleibt für KI verfügbar |
| Löschen | Filter und PNG endgültig entfernen |

## 24.3 KI-Analyse — Modi und Limits

| Parameter | Standard | Beschreibung |
|---|---|---|
| `HITL_AI_MODE` | `"expand_only"` | KI darf nur **neue** breitere Bereiche vorschlagen, bestehende Filter bleiben unverändert |
| `HITL_MAX_PNGS_FOR_AI` | `5` | Maximale Anzahl Polygon-PNGs pro KI-Lauf (begrenzt API-Kosten) |
| `HITL_PADDING_PX_DEFAULT` | `50` | Standard-Padding (Pixel) um das Polygon beim PNG-Crop. Per Slider in der Filter-Galerie überschreibbar |

## 24.4 Konfiguration in `runtime_overrides.json`

| Schlüssel | Beispielwert | Wirkung |
|---|---|---|
| `HITL_PADDING_PX` | `75` | Pixel-Padding ab nächstem Polygon |

Wird vom Padding-Slider in der Filter-Galerie automatisch geschrieben — manuelles Eintragen ist nicht nötig.

## 24.5 Persistenz und Backup

Alle HitL-Daten liegen unter `train_data/cell_filters/`:

```
train_data/cell_filters/
├── cell_filters.json        Master-File (JSON, atomar geschrieben, file-locked)
├── .migrated_v2             Marker für einmalige Migration
└── polygons/                PNG-Ausschnitte mit Polygon-Overlay
    ├── f_20260521-143215_a3f9.png
    └── ...
```

Das Verzeichnis ist **gitignored** — Filter und PNGs sind benutzerspezifische Lerndaten. Für Backup das gesamte Verzeichnis sichern.

> **Wichtig — Geschützt vor `install.sh --mode=full`:**
> `train_data/cell_filters/` bleibt analog zu `.env`, `runtime_overrides.json` und den DEM-Tiles **auch bei einer Vollinstallation** unangetastet. Benutzergenerierte Lerndaten gehen nicht verloren. Wer die HitL-Daten gezielt zurücksetzen möchte, muss das Verzeichnis manuell löschen (siehe §24.6).

## 24.6 Rollback und Reset

**Einzelne Filter deaktivieren** ohne PNG zu verlieren: Aktiv-Toggle in der Galerie auf „inaktiv" stellen. Das Polygon-PNG bleibt erhalten und kann bei der nächsten KI-Analyse weiterhin als Beispiel dienen.

**HitL-Pipeline komplett deaktivieren** ohne Daten zu verlieren:

```bash
mv train_data/cell_filters/cell_filters.json    train_data/cell_filters/cell_filters.json.disabled
sudo systemctl restart wetterprojekt
```

Der Tracker fällt dann automatisch auf die Defaults aus `config.FILTER_CONFIG` zurück. Reaktivierung durch Zurück-Umbenennen.

**HitL-Daten vollständig zurücksetzen** (manueller Schritt, **nicht** von `install.sh --mode=full` ausgeführt):

```bash
sudo systemctl stop wetterprojekt
rm -rf train_data/cell_filters/
sudo systemctl start wetterprojekt
```

Beim nächsten Tracking-Frame wird die Migration aus `config.FILTER_CONFIG` neu ausgeführt.

---

# 25 Hailo-8 Integration — Phasen-Roadmap

Der Hailo-8 AI-Beschleuniger (26 TOPS, PCIe Gen3) ist physisch montiert und der Treiber (`hailo-all`) ist installiert. Die Inferenz-Integration erfolgt in zwei Phasen:

| Phase | Status | Inhalt |
|---|---|---|
| Phase A (aktuell) | In Betrieb | `hailo_inference.py` als Stub. Alle Modelle laufen auf Pi-CPU. Hailo-8 bleibt ungenutzt — Inferenzzeit ist bei 120s Loop nicht kritisch. |
| Phase B (geplant) | Ausstehend | Anschaffung x86-Linux-Trainer. U-Net Nowcasting (~2 Mio Parameter) wird trainiert, via DFC für Hailo kompiliert, auf Pi für Live-Inferenz bereitgestellt. |
| Phase C | Langfristig | Weitere Optimierungen, ggf. zusätzliche Modelle, KI-Analyse vertieft. |

Strategische Entscheidung: Statt zweier kleiner CNNs (Cell-Intensity + Cell-Motion) wird ein einzelnes U-Net für komplette Radarbild-Nowcasting eingesetzt. Bei ~2 Mio Parametern wäre dies auf der Pi-CPU nicht im 120s-Takt praktikabel, rechtfertigt aber den Hailo-8 (26 TOPS) vollständig.

> **Hinweis:** Während Phase A/B bleibt `hailo_inference.py` ein Stub der alle Aufrufe transparent auf CPU-Fallback (LightGBM/LSTM) umleitet. Die restliche System-Architektur ändert sich nicht.

---

# 25 Konfigurationsreferenz

Alle Parameter werden in `config.py` als Python-Konstanten definiert und können über `runtime_overrides.json` zur Laufzeit überschrieben werden — ohne Service-Neustart. Das Admin-Panel schreibt Änderungen automatisch in `runtime_overrides.json`.

| Parameter | Standard | Bereich |
|---|---:|---|
| `UPSCALE_FACTOR` | 3.0 | Bildverarbeitung |
| `FRAME_INTERVAL_MIN` | 2.0 | Bildverarbeitung — nominales Radar-Frame-Intervall in Minuten (siehe §27 v1.2) |
| `MAX_CONTOUR_DISTANCE` | 30 px | Tracking |
| `MAX_STATION_DISTANCE_KM` | 20 km | Tracking |
| `MIN_MOVEMENT_FOR_ARROW_KMH` | 5 km/h | Darstellung |
| `LOOP_INTERVAL_CELLS_S` | 120 s | Live-Loop |
| `LOOP_INTERVAL_NO_CELLS_S` | 900 s | Live-Loop |
| `ATMOSPHERIC_SNAPSHOT_INTERVAL_MIN` | 30 min | Live-Loop |
| `HAIL_WARN_THRESHOLD` | 0.45 | Warnungen |
| `STATIONARY_RISK_MARKER_THRESHOLD` | 0.60 | Warnungen |
| `GUST_WARN_KMH` | 60 km/h | Warnungen |
| `HEAVY_RAIN_WARN_MM_PER_H` | 25 mm/h | Warnungen |
| `MAX_CELL_SPEED_KMH` | 150 km/h | Plausibilität |
| `MAX_SPEED_CHANGE_PER_CYCLE_KMH` | 60 km/h | Plausibilität |
| `ML_SEQUENCE_LENGTH` | 6 | ML (LSTM) |
| `ML_FORECAST_HORIZONS_MIN` | `[10,20,30,40,60]` | ML |
| `DATA_RETENTION_DAYS` | 90 | Daten-Rotation |
| `VERIFICATION_TOLERANCE_KM` | 5 km | Verifikation |
| `AI_ANALYSIS_CONFIG.enabled` | `false` | KI-Analyse |
| `AI_ANALYSIS_CONFIG.cron_hour` | 6 | KI-Analyse |
| `LOCAL_TRAINING` | `true` | Multi-Rechner |
| `RISK_CELL_RANGE_KM` | 20 km | Risikozonen |
| `RISK_TRACK_RANGE_KM` | 10 km | Risikozonen |
| `RISK_BOLT_RANGE_KM` | 10 km | Risikozonen |
| `RISK_ATM_RANGE_KM` | 20 km | Risikozonen |
| `RISK_GRID_STEP_DEG` | 0.05° | Risikozonen |
| `RISK_FAST_CELL_KMH` | 30 km/h | Risikozonen |
| `RISK_STATIONARY_BOOST` | 0.8 | Risikozonen |
| `TAWES_GUST_STATION_IDS` | (alle Kärntner) | TAWES |
| `TAWES_PARAMS` | `RR,DD,FF,FFX,...` | TAWES |
| `API_CACHE_TTL_SECONDS` | `{}` (Dict) | API-Cache |
| `CONVLSTM_MODEL_PATH` | (auto) | ML |
| `SLOW_CELL_MAX_KMH` | 15 km/h | Warnungen |
| `SLOW_CELL_RADIUS_FACTOR` | 1.5 | Warnungen |

> **Hinweis:** Alle Parameter unter `runtime_overrides.json` überschreiben die `config.py`-Defaults.
> Änderungen über das Admin-Panel (`/config`) sind sofort wirksam — kein Service-Neustart nötig.
> Die Konfigurationsseite enthält eine vollständige, durchsuchbare Referenz aller 34 konfigurierbaren Keys.

---

# 26 Fehlerbehebung (Troubleshooting)

| Problem | Ursache | Lösung |
|---|---|---|
| Admin-Panel nicht erreichbar | nginx gestoppt oder Service-Fehler | `sudo systemctl status nginx`; `sudo systemctl restart nginx` |
| Keine Radar-Daten | ARSO-Server nicht erreichbar oder Timeout | API-Gesundheit unter `/logs` prüfen; Logs mit `journalctl -fu wetterprojekt.service` |
| Modelle nicht vorhanden | Erster Start, Training noch nicht gelaufen | Unter `/training` manuelles Training starten; System läuft im kinematischen Fallback |
| Disk kritisch (> 90%) | Trainingsdaten wachsen unbegrenzt | Sofortiger Cleanup: `python3 cleanup_old_data.py`; `DATA_RETENTION_DAYS` reduzieren |
| `hailo_inference.py` Fehler | Hailo-Treiber Fehler (Phase A: erwartet) | Ignorieren — CPU-Fallback ist aktiv. Phase B Hailo-Integration noch ausstehend. |
| E-Mail nicht gesendet | SMTP-Credentials fehlen oder falsch | `.env` prüfen (SMTP_HOST, SMTP_USER, SMTP_PASS); bei Gmail App-Passwort verwenden |
| /karte verlangt Login | nginx Konfiguration veraltet | `sudo nginx -t && sudo systemctl reload nginx`; oder `install.sh --mode=upgrade` |
| KI-Analyse schlägt fehl | `ANTHROPIC_API_KEY` fehlt oder abgelaufen | `.env` prüfen; KI-Analyse in `config.py` deaktivieren wenn nicht benötigt |
| Open-Meteo Limit erreicht | Zu viele Requests (> 10000/Tag) | Bulk-Query in `fetch_arome_openmeteo.py` aktiviert? TTL erhöhen in `API_CACHE_TTL_SECONDS` |
| Admin-Passwort vergessen | `/etc/nginx/.htpasswd` fehlt | `cat /home/ki-pi/wetterprojekt/.admin_password` — oder `install.sh --mode=upgrade` |
| Frontend zeigt leere Seite | Frontend-Build veraltet oder fehlt | `cd frontend && npm run build`; `sudo systemctl restart wetterprojekt-admin` |


---

# 19 NEU: Konvektive Diagnose-Indizes (SHIP, CIN, PW, Lapse Rate, 0–6-km-Scherung)

**Modul:** `compute_convective_indices.py`
**Eingangs-Erweiterung:** `fetch_openmeteo_extended.py`, `fetch_atmospheric_snapshot.py`
**API:** Open-Meteo icon_global hourly (4 neue Parameter — kein zusätzlicher HTTP-Request)

Das System berechnet jetzt sechs zusätzliche wissenschaftlich etablierte
Diagnose-Indizes für jede Sturmzelle und für den 30-Minuten-Atmosphären-Snapshot.
Alle Berechnungen sind **rein rechnerisch** auf Basis bereits abgerufener Daten —
**keine zusätzlichen externen API-Aufrufe**.

## 19.1 Neue Roh-Eingangsfelder (aus icon_global)

| Feld | Einheit | Bedeutung |
|---|---|---|
| `t500_c` | °C | Temperatur 500 hPa |
| `t700_c` | °C | Temperatur 700 hPa |
| `cin` | J/kg | Convective Inhibition (negative Werte = Deckelung) |
| `pw` | mm | Precipitable Water (Starkregenpotenzial) |

Diese 4 Parameter werden an den **bestehenden** icon_global-Pressure-Level-Request
in `fetch_openmeteo_extended.py` angehängt — derselbe HTTP-Request, mehr Parameter.

## 19.2 Abgeleitete Diagnose-Indizes (pure Python)

| Feld | Einheit | Berechnung |
|---|---|---|
| `lapse_700_500` | °C/km | `(t700_c − t500_c) / 3.0` (hypsometrische Näherung) |
| `shear_0_6km_speed` | km/h | Betrag des Differenzvektors 10m → 500 hPa |
| `shear_0_6km_dir_cos/sin` | — | Richtung des Scherungsvektors |
| `mixr` | g/kg | Mischungsverhältnis aus Td₂ₘ (Magnus-Tetens) |
| `ship_index` | dimensionslos | Significant Hail Parameter nach Stull |
| `lightning_jump` | Faktor | Rate(jetzt) / Rate(−15 min) |
| `hail_prob2` | 0.0–1.0 | SHIP-basierte Hagel-Wahrscheinlichkeit |

> **Wichtig:** `hail_prob` (alte Heuristik) bleibt unverändert. `hail_prob2` ist additiv —
> das ML-Modell bekommt beide und gewichtet sie selbst.

## 19.3 SHIP-Formel

$$\text{SHIP} = \frac{\text{CAPE} \cdot \text{MIXR} \cdot \Gamma_{700-500} \cdot (-T_{500}) \cdot \text{Shear}_{0-6km}}{44 \times 10^6}$$

Interpretation nach Stull / NOAA:

| SHIP | Bewertung |
|---:|---|
| < 1.0 | Hagel-Umgebung schwach |
| 1.0 – 1.5 | günstig für signifikanten Hagel |
| > 1.5 | häufig signifikant |
| > 4 | sehr hoch |

## 19.4 Risikozonen-Layer: Erweiterungen

Der bestehende Risikozonen-Layer (`/api/risk_grid`) wurde um zwei wichtige Funktionen erweitert:

### Forecast-Zugbahn als Linien-Korridor
Bisher: Risiko-Score pro Forecast-Position (Punkt).
Jetzt: Punkt-zu-Linien-Distanz für den gesamten Pfad zwischen aktueller Position
und allen Forecast-Horizonten. Grid-Zellen entlang der Zugbahn (< 30 km zum Pfad)
bekommen einen zusätzlichen Risiko-Beitrag, gewichtet nach Zell-Intensität.

### Hover-Tooltip mit Diagnose-Werten
Beim Hovern über farbige Risikozonen erscheint ein Tooltip mit:
- Risiko-Stufe (Niedrig / Mäßig / Hoch)
- Dominierende Quelle (Aktive Zelle / Zugbahn / Blitze / Instabilität)
- Aktuelle SHIP, CAPE, LI, CIN, PW, Lapse Rate
- Markierung „⚠ In berechneter Zugbahn" bei Zugbahn-Treffer
- Blitzanzahl < 10 km

Der Tooltip wird **unterdrückt**, wenn unter dem Grid-Rechteck bereits eine
markierte Sturmzelle liegt — sonst Konflikt mit dem Zellen-Popup.

## 19.5 ML-Pipeline — Auswirkung

Folgende 11 neuen Features wurden zu `ML_CELL_FEATURES` ergänzt:

`t500_c`, `t700_c`, `cin`, `pw`, `lapse_700_500`, `shear_0_6km_speed`,
`shear_0_6km_dir_cos`, `shear_0_6km_dir_sin`, `ship_index`, `lightning_jump`,
`hail_prob2`

> **Modelle müssen nach Deployment neu trainiert werden.** Beim ersten Cron-Slot
> nach dem Update (03:00) wird das Training automatisch ausgelöst. Manueller
> Trigger via Admin-Panel → Training → „Jetzt trainieren".

## 19.6 Was NICHT geändert wurde

- Keine neue externe API-Schnittstelle
- Keine neuen HTTP-Requests pro Live-Loop-Zyklus
- `hail_prob`, `HAIL_WARN_THRESHOLD`, alle bestehenden Warnschwellen unverändert
- Blitzortung-Quelle bleibt Blitzortung.org (kein Wechsel auf ALDIS)
- Alle bestehenden Backend- und Frontend-Komponenten unverändert ausser den 4
  betroffenen Dateien (`fetch_openmeteo_extended.py`, `fetch_atmospheric_snapshot.py`,
  `config.py`, `main.py`, `app.py`, `MapView.jsx`, `MapFullscreen.jsx`)

---

# 28 Binary-Artefakte und Modell-Distribution

ML-Modelle und Hailo-HEF-Dateien sind **Binaries** und werden **nicht** über Git gepusht.

| Artefakt-Typ | Erweiterung | Distribution |
|---|---|---|
| Keras-Modell (LSTM) | `.keras`, `.h5` | GitHub Releases / manueller `scp` |
| LightGBM-Modell | `.txt.lgb` | GitHub Releases / manueller `scp` |
| Scikit-learn Scaler | `.joblib`, `.pkl` | GitHub Releases / manueller `scp` |
| ONNX-Export | `.onnx` | GitHub Releases (Phase B) |
| Hailo HEF | `.hef` | Separater Download, `models/hailo/` via rsync |
| NumPy-Dataset | `.npz` | Lokal generiert (via Training) |

> Ohne vorhandene Modelle startet das System im kinetischen Fallback-Modus. Modelle werden beim ersten Training-Lauf automatisch erstellt.

## 28.1 Vollständige `.env`-Konfigurationsreferenz

| Variable | Pflicht | Funktion |
|---|---|---|
| `FTP_SERVER`, `FTP_USER`, `FTP_PASS`, `FTP_PATH` | Empfohlen | FTP-Upload des Radar-Overlays |
| `BLITZ_USERNAME`, `BLITZ_PASSWORD` | Optional | Blitzortung.org Echtzeit-Blitzdaten |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`, `TWILIO_TO` | Optional | SMS-Sturmwarnungen |
| `ANTHROPIC_API_KEY` | Optional | KI-Analyse-Chat im Admin-Panel |
| `GITHUB_TOKEN` | Ja (privates Repo) | KI-Analyse lädt Quellcode von GitHub |
| `WETTER_DEBUG` | Optional | `1` = Debug-Logs + Bilder (erhöht I/O) |

> `GITHUB_TOKEN` steht **ausschließlich** in `.env`. In `config.py` wird er via `os.environ.get("GITHUB_TOKEN", "")` gelesen.

---


# 32 NEU: Atmosphärisches 36-Punkt-Raster (ATM_SNAPSHOT_LOCATIONS)

**Modul:** `fetch_atmospheric_snapshot.py`
**Konfiguration:** `ATM_SNAPSHOT_LOCATIONS` in `config.py`

## 32.1 Motivation

Das bisherige System verwendete die 6 Orte aus `LOCATIONS_WATCHLIST` (Klagenfurt,
Villach, Wolfsberg, Spittal, St. Veit, Feldkirchen) auch als atmosphärische
Referenzpunkte. Bei `ATM_RANGE = 20 km` blieben damit ca. 30 % des Kärnten-Grids
ohne LI/CIN-Bewertung (Randlagen: westliches Gailtal, Lavanttal-Ost, Nordkärnten).

## 32.2 Neue Konstante ATM_SNAPSHOT_LOCATIONS

`ATM_SNAPSHOT_LOCATIONS` in `config.py` ist vom Alarmierungs-System (`LOCATIONS_WATCHLIST`)
vollständig getrennt. Die 36 Punkte werden **ausschließlich** für das atmosphärische
Risk-Grid verwendet — kein `radius_km`, keine Ortsdurchquerungsalarme.

## 32.3 Gitter-Design (9 × 4)

| Zone | Breite | Längen (9 Spalten) |
|---|---|---|
| Süd-Kärnten / Karawanken | 46.40° N | 12.65 / 12.96 / 13.28 / 13.59 / 13.90 / 14.21 / 14.53 / 14.84 / 15.15 |
| Zentral-Süd | 46.65° N | (gleiche Längen) |
| Zentral-Nord | 46.91° N | (gleiche Längen) |
| Nord-Kärnten | 47.16° N | (gleiche Längen) |

Abstand Ost-West: ~24 km · Abstand Nord-Süd: ~28 km
→ Worst-Case-Distanz (Rechteck-Mitte) = √(12² + 14²) ≈ 18,4 km ≤ ATM_RANGE 20 km.
   Damit ist JEDER Grid-Punkt im gesamten BBOX_KAERNTEN_EXTENDED (46.36–47.18 N,
   12.60–15.20 E) lückenlos innerhalb von 20 km eines Snapshot-Punkts abgedeckt —
   inklusive Karawanken-Südrand und Nockberge-Nordrand.

## 32.4 Batching

`_bulk_get_batched()` splittet die 36 Locations automatisch in 5 Batches à 8 und
macht 5 × 3 = **15 API-Calls pro Snapshot-Zyklus** (3 Modelle: icon_d2, icon_global, GFS).
Bei 48 Zyklen/Tag: **720 Requests/Tag** — 7,2 % des Open-Meteo-Limits von 10.000/Tag.

## 32.5 Laufzeit-Überschreibung

Der Schlüssel `ATM_SNAPSHOT_LOCATIONS` ist über `runtime_overrides.json` überschreibbar:

```json
{
  "ATM_SNAPSHOT_LOCATIONS": [
    {"name": "MeinPunkt", "lat": 46.80, "lon": 14.00},
    ...
  ]
}
```

---

# 31 NEU: API-Resilienz — Stale-While-Error-Cache & Verbindungspool

**Module:**
- `http_retry.py` (Connection-Pool + urllib3-Retry)
- `api_cache.py` (Funktion `cache_get_stale()`)
- `fetch_openmeteo_extended.py`, `fetch_atmospheric_snapshot.py`, `fetch_arome_openmeteo.py` (Stale-Fallback aktiv)

## 31.1 Connection-Pool für externe APIs

Alle externen GET-Requests (Open-Meteo, GeoSphere, EUMETView, Blitzortung,
ARSO) gehen jetzt durch eine gemeinsame `requests.Session` mit `HTTPAdapter`
und urllib3-`Retry`. Vorteile gegenüber einzelnen `requests.get`-Aufrufen:

- TCP-/TLS-Verbindungen werden zwischen Aufrufen wiederverwendet (Keepalive)
  — spart bei jedem Frame mehrere TLS-Handshakes
- Bei Server-Fehlern (502/503/504/429) wiederholt urllib3 automatisch INNERHALB
  des Pools mit exponentiellem Backoff und respektiert `Retry-After`-Header
- Bei Connection-Errors (TCP-Reset, SSL-EOF) wird die kaputte Verbindung
  aus dem Pool entfernt und beim nächsten Versuch eine neue aufgebaut —
  löst die zuvor sichtbaren `SSLZeroReturnError`-Phasen

Connect-Timeout (TLS-Handshake): 8 s. Read-Timeout: konfigurierbar je Modul,
mindestens 30 s. Bulk-Requests gegen Open-Meteo (AROME + Atmosphere) nutzen
jetzt durchgehend 25 s Read-Timeout.

## 31.2 Stale-While-Error-Cache

Wenn ein externer Service nach allen Retries unerreichbar bleibt, fällt das
System nicht mehr auf Default-Werte (0.0) zurück, sondern liest den **letzten
erfolgreichen Cache-Eintrag** aus den letzten 24 Stunden. ML-Features bleiben
damit auch in 502-Phasen plausibel.

| Service | Stale-Cache aktiv |
|---|---|
| Open-Meteo Extended (15min, Pressure, LPI, GFS) | ✅ |
| Open-Meteo AROME (icon_d2 + icon_eu LI) | ✅ |
| Open-Meteo Atmosphäre-Bulk | ✅ (via _bulk_get) |

Das Admin-Panel zeigt unter **Logs → API-Cache Status** ob bei einem Service
ein STALE-Eintrag verwendet wurde (Spalte „Status": STALE-FALLBACK).

## 31.3 Lifted Index aus icon_eu

Der ML-Feature `arome_li` (Lifted Index, Konvektions-Instabilitätsindikator)
wird jetzt aus dem **icon_eu**-Modell geholt statt aus icon_d2 — das DWD-
ICON-D2-Modell stellt diesen Parameter über die Open-Meteo-API gar nicht
bereit (siehe https://open-meteo.com/en/docs/dwd-api). Der Wert ist jetzt
**erstmals real verfügbar** und kann das Modell tatsächlich informieren
(negative Werte = instabil, < −4 °C = Gewitter-Risiko hoch).

## 31.4 Bulk-Batching > 8 Locations

`fetch_atmospheric_snapshot._bulk_get_batched()` splittet Open-Meteo-Bulk-
Anfragen in Batches à maximal 8 Locations, sobald die Watchlist mehr Orte
enthält. Open-Meteo's Server-Antwortzeit steigt überproportional mit der
Anzahl Locations — Batching hält jede einzelne Antwort unter dem 25-s-
Read-Timeout.

Aktuell sind 7 Orte konfiguriert (Klagenfurt, Villach, Wolfsberg, Spittal,
St. Veit, Feldkirchen, plus konfigurierbar via Admin-Panel) — Batching greift
erst bei Erweiterung. Rückwärtskompatibel.


# 27 Änderungshistorie

| Version | Datum | Änderungen |
|---|---|---|
| v2.4 | Juni 2026 | **Bild-Upload-Formatfilter:** Der KI-Bild-Upload akzeptiert nur noch JPEG, PNG, GIF und WebP. Nicht unterstützte Formate wie SVG, HEIC, BMP oder TIFF werden übersprungen und mit Dateinamen gemeldet. |
| v2.3 | Juni 2026 | **IR-Layer-Label präzisiert:** Legende und Checkbox verwenden jetzt „CB / IR-Vorläufer" statt „CB > 10.000". Der Tooltip stellt klar, dass BT < 230 K eine Erkennungsschwelle (typisch > 10.000 m MSL) ist und angezeigte Wolkentop-Höhen einzelner Zellen abweichen können. |
| v2.2 | Mai 2026 | **Atmosphärisches Raster verdichtet (24 → 36 Punkte):** `ATM_SNAPSHOT_LOCATIONS` auf 9×4-Gitter erweitert (~24 km O-W / ~28 km N-S). Deckt jetzt den vollständigen `BBOX_KAERNTEN_EXTENDED` inkl. Karawanken-Südrand und Nockberge-Nordrand lückenlos ab — Worst-Case-Distanz 18,4 km ≤ ATM_RANGE 20 km. 5 Batches, 720 Req/Tag (7,2 % Limit). |
| v2.1 | Mai 2026 | **Atmosphärisches 24-Punkt-Raster:** `ATM_SNAPSHOT_LOCATIONS` in `config.py` — 8×3-Gitter (~27 km Abstand) für lückenlose Kärnten-Abdeckung. `_bulk_get_batched()` in `fetch_atmospheric_snapshot.py` splittet Requests automatisch in Batches à 8 Locations. Getrennt von `LOCATIONS_WATCHLIST` (Alarmierung unverändert). |
| v2.0 | Mai 2026 | **Trainings-Schedule Hilftexte:** Jedes Einstellungsfeld im Trainings-Schedule erhält einen erläuternden Hilfetext direkt unter dem Eingabefeld (Datensatz-Rebuild, Retrain-Interval, Nightly Retrain, ConvLSTM Zeitplan). **Live-Karte UX:** KMZ-Download-Button aus der Live-Karte entfernt (KMZ wird weiterhin automatisch per FTP hochgeladen). Risikozonen-Statusmeldungen („Keine Risikozonen im aktuellen Zeitraum" / „Risikozonen nicht verfügbar") werden jetzt kompakt in der Timing-Bar neben „✓ Keine aktiven Schwergewitter-Zellen" angezeigt statt als separate Banner. |
| v1.11 | Mai 2026 | **Risikozonen-Radien kalibriert:** Einfluss-Radien des Risk-Grids auf meteorologisch realistische Werte reduziert (CELL_RANGE 60→30 km, TRACK_RANGE 30→20 km, BOLT_RANGE 30→20 km, ATM_RANGE 45→30 km, IR-Vorläufer 40→25 km, in_track-Schwelle 15→10 km). Alle Radien über Runtime-Overrides konfigurierbar (`RISK_CELL_RANGE_KM`, `RISK_TRACK_RANGE_KM`, `RISK_BOLT_RANGE_KM`, `RISK_ATM_RANGE_KM`). **Config-Hilfe:** Die Konfigurationsseite (`/config`) zeigt jetzt eine vollständige, durchsuchbare Parameter-Referenz mit allen 34 konfigurierbaren Runtime-Keys, Typen, Defaults, Beschreibungen und Beispiel-JSON. |
| v1.10 | Mai 2026 | **IR-Vorläufer Tooltip — Trendanzeige:** Der IR-Vorläufer-Tooltip (🛰 CB > 10.000) zeigt den Trend jetzt als qualitatives Label: `↑ Intensiviert ⚡` (BT-Trend < −1,5 K/min), `↓ Löst sich auf` (BT-Trend > +0,5 K/min) oder `→ Stabil`. Der numerische K/min-Wert und das technische Label „Kein Radar-Echo — Vorläufer" wurden entfernt. **Zell-Navigation aus Live-Daten:** In der `/live`-Ansicht öffnet ein Klick auf die Zell-ID ein neues Fenster mit `/map`, das sofort auf diese Zelle zoomt (URL-Parameter `lat`, `lon`, `zoom`, `cell`). **Zusammenführungs- und Teilungs-Badge:** Zellen mit `lineage == merged` erhalten in der Tabelle ein oranges ⊕-Badge, Zellen mit `lineage == split` ein violettes ⊗-Badge. Im Detail-Panel werden bei Merged-Zellen zusätzlich die Parent-IDs angezeigt. |
| v1.9 | Mai 2026 | **Risk-Grid-Fix:** `/api/risk_grid` ist jetzt 200-stabil — `BBOX_KAERNTEN_EXTENDED` wird korrekt importiert und als Dict (`north/south/east/west`) und als List/Tuple verarbeitet. Die Kärnten-BBOX wird immer korrekt verwendet statt auf Fallback-Werte zu fallen. **IR-Vorläufer-Bewertung:** IR-Tracks werden einmalig vor der Grid-Schleife geladen (nicht mehr ~1000× pro API-Call). Der IR-Score-Beitrag wird jetzt korrekt VOR der Risk-Klassifikation addiert, sodass reine IR-Vorläuferzellen tatsächlich Risk-1-Zellen erzeugen können. **Vollbild-Karte Fehleranzeige:** `/karte` (MapFullscreen) zeigt jetzt wie die Admin-Karte eine sichtbare Fehlermeldung wenn das Risk-Grid nicht geladen werden kann. |
| v1.8 | Mai 2026 | **3-Stage Kalman-Matching:** Zell-Tracking nutzt jetzt Kalman-vorhergesagte Polygonpositionen (Stage 1: IoU gegen verschobenes Polygon; Stage 2: Zentroid-Distanz; Stage 3: klassischer Overlap). Zellen behalten ihre ID auch bei schneller Bewegung oder Formänderung. **Richtungspfeile** werden für alle Zellen gezeigt (langsame mit 35% Opazität statt ausgeblendet). **Download-Buttons** (⬇ Logs .txt, ⬇ Objects .json) in der Logs-Seite. |
| v1.9 | Juni 2026 | P27 — EWMA-Geschwindigkeitsgewichtung: Kinematischer Forecast nutzt jetzt alle verfügbaren History-Frames (bis `TRACK_HISTORY_LEN = 6`) mit exponentieller Gewichtung (`KINEMATIC_EWMA_ALPHA = 0.6`). Neuere Frames dominieren — schnelle Reaktion auf Kursänderungen, gleichzeitige Dämpfung von Einzelausreißern. Beide Parameter runtime-überschreibbar über Admin-Panel. |
| v1.0 | 2025 | Erstveröffentlichung: HSV-Segmentierung, Kalman-Tracking, LSTM + LightGBM, React Admin-Panel (10 Seiten), KMZ-Export, `install.sh`, Scheduler, Closed-Loop-Verifikation |
| v1.1 | Mai 2026 | Phase-A-Erweiterungen: Optical Flow (pysteps), AROME icon_d2 Gitterpunkt, Erweitertes DEM (3 Kacheln, Talkanalisierung), Windscherung, Hagelindikator, Stationärrisiko, GeoSphere TAWES + Nowcast, SMS (Twilio), Daten-Rotation (90 Tage), Disk-Monitoring, nginx Basic-Auth, Adaptiver Loop-Intervall, `LOCAL_TRAINING`-Flag, API-Request-Statistik, KI-Analyse Chat (Claude API), Atmosphären-Seite, Vollbild-Karte `/karte`, 15 Admin-Panel-Seiten, Bugfixes: `parse_timestamp`, `radar_download` Timeout/Retry, `blitz_api` HTTP-Auth, `SAVE_PATHS` Zentralisierung, `runtime_config` File-Lock |
| v1.2 | Mai 2026 | Produktreife-Welle 1: Neuer Konfigurationsparameter `FRAME_INTERVAL_MIN` (nominales Radar-Frame-Intervall in Minuten, default 2.0) — wird in `prediction.py` für die korrekte Umrechnung von Horizon-Minuten in Frames verwendet. Accuracy-Tracker liefert vier neue Felder (`verified`, `missed`, `no_target_frame`, `id_lost`) pro Horizont für transparente Verifikations-Statistik. KMZ-Export enthält jetzt vier Layer: „Aktuelle Zellen" (Konturen + Mittelpunkte), „Forecast +Hmin" pro Horizont, „Unsicherheit +Hmin" (q10/q90) und „Betroffene Orte" (Locations in Forecast-Farbe). Modell-Promotion benötigt mindestens 50 Validierungs-Samples und strikte MAE-Verbesserung (Toleranz nur bei >500 Samples).
| v1.3 | Mai 2026 | Produktreife-Welle 2: POST/PATCH/DELETE-Endpunkte werden durch einen konfigurierbaren Admin-Token (`ADMIN_API_TOKEN` in `.env`) geschützt — das Frontend holt den Token einmalig vom gesicherten Endpoint `/api/admin_token`. Alle externen API-Clients (`blitz_api`, `fetch_arome_openmeteo`, `fetch_geosphere_nowcast`, `cloud_height_from_eumetview`, `fetch_700hpa_wind_per_object_slim`) nutzen jetzt einen einheitlichen Retry-Wrapper mit exponentiellem Backoff (max. 3 Versuche, 2/5/10 s). `install.sh` erzeugt nach der Python-Installation eine `requirements.lock`-Datei (exakter Paket-Stand via `pip freeze`) und verwendet `npm ci` wenn `package-lock.json` vorhanden ist. Systemd-Services nutzen `Type=notify` + `WatchdogSec=60`; ein Heartbeat-Thread (`watchdog_heartbeat.py`) sendet alle 25 s `WATCHDOG=1` — ausbleibende Pings lösen automatischen Service-Neustart aus. Das systemd-Journal wird auf 200 MB begrenzt (Drop-In `/etc/systemd/journald.conf.d/wetterprojekt.conf`). Wöchentliches Backup-Script (`backup_wetterprojekt.sh`) sichert Modelle, `.env` und `runtime_overrides.json` in `~/wetterprojekt-backup/` (automatisch via Scheduler, sonntags 02:00, Retention 14 Tage). Admin-API ist nicht mehr direkt im LAN erreichbar — Flask bindet ausschließlich an `127.0.0.1`; Override via Env-Var `ADMIN_BIND_HOST`. |
| v1.4 | Mai 2026 | Produktreife-Welle 3: Vier neue Lineage-Features in `ML_CELL_FEATURES`: `active_frames_norm` (Lebensdauer der Zelle, normalisiert 0..1), `total_active_frames_norm` (kumulierte Aktivdauer seit `first_seen`), `is_merged` (1.0 bei Zell-Fusion), `is_split` (1.0 bei Zell-Teilung) — das Modell lernt damit den Einfluss von Zellentstehungstyp und -reife auf die Zugbahn. Automatische Model-Drift-Erkennung (`drift_detector.py`): nach jedem Accuracy-Eval-Job wird der gleitende MAE-Trend der letzten 24 h gegen den 7-Tage-Baseline verglichen; bei Verschlechterung > 2 km sendet das System einen E-Mail-Alarm und persistiert den Status in `drift_status.json` (abrufbar via `GET /api/drift`). React-Admin-Panel erhält eine Error-Boundary (lesbarer Fehlerhinweis statt weißer Seite bei JS-Fehlern) sowie einen Offline-Indikator-Banner. Der letzte Tag der Trainingsdaten wird als echter Holdout-Datensatz zurückgehalten — Holdout-MAE pro Horizont wird in `training_meta.json` dokumentiert (ehrliche Test-Metriken ohne Data-Leakage zwischen Training und Validation). |
| v1.5 | Mai 2026 | Produktreife-Welle 4 (P0-Findings): No-cell-Frames werden jetzt immer als leere `[]`-Objektdatei gespeichert — API, KMZ und Karte zeigen bei erkannungsfreien Frames korrekt „keine Zellen" statt veralteter Daten. Dataset-Builder und Trainingsläufe nutzen die im Admin-Panel konfigurierten Forecast-Horizonte (`runtime_config`) statt der statischen `config.py`-Werte; eine neue `_check_model_compatibility()`-Funktion verhindert Einsatz von Modellen mit abweichenden Horizonten oder Feature-Dimensionen (kinematischer Fallback). Cold-Start-Promotion wird erst ab `MIN_SAMPLES_FOR_PROMOTION` Validierungssamples zugelassen — kein Einsetzen eines zu schwach validierten Modells ohne Referenzmodell mehr. Accuracy-Metriken enthalten jetzt `coverage_rate` (Anteil verifizierbarer Forecasts), das zusammen mit der Hit-Rate die echte Aussagekraft der Metriken bewertet. Startup-Warnung wenn `ADMIN_API_TOKEN` fehlt; optionaler Hard-Stop via `ADMIN_REQUIRE_TOKEN=1`. `pytest.ini` steuert pytest auf `tests/` ein und verhindert das Einsammeln von Root-Skripten. Kinematischer Forecast nutzt echte Zeitdifferenzen aus History-Timestamps (`x/y` im History-Eintrag, px/min statt px/Frame). |
| v1.6 | Mai 2026 | Produktreife-Welle 5 (P0-Review-Findings): No-cell-Zustand vollständig propagiert — bei erkannungsfreien Frames werden jetzt auch `locations_{ts}.json` (leere Liste) und `forecast.kmz` (leeres KMZ) aktualisiert, und Auto-Entwarnung für bisher betroffene Orte wird ausgelöst. Training (`train_lgbm`, `train_lstm`, `evaluate_on_recent`) und LGBM-Modellladen (`load_lgbm_models`) nutzen konsequent runtime-konfigurierbare Forecast-Horizonte — Admin-Änderungen über das Panel wirken jetzt durchgängig bis ins Training. Modell-Promotion prüft vor dem Aktivieren Horizont- und Feature-Kompatibilität (`_check_model_compatibility`) sowie Gültigkeit des Holdout-MAE. `ADMIN_REQUIRE_TOKEN=1` wird bei jeder Installation automatisch in `.env` geschrieben (fail-closed Standard); `/api/admin_token` lehnt Direktzugriffe ohne nginx-Proxy-Header ab. Neue `tests/test_units.py` mit 6 Unit-Tests für Einheitenkonsistenz (Kalman/Velocity, Forecast-Pixel-Rechnung, Lineage-Normierung, Feature-Dimension). `install.sh` generiert `package-lock.json` einmalig mit `npm install --package-lock-only` für reproduzierbare Frontend-Builds. |
| v1.7 | Mai 2026 | Produktreife-Welle 6 (P1-Punkte): Forecast-Pfadprüfung in `annotate_locations` prüft jetzt zusätzlich die Zwischensegmente h[n]→h[n+1] — Orte die der Forecast-Pfad zwischen zwei Horizonten schneidet werden zuverlässig erkannt (wichtig bei Kursänderungen der Zelle). `runtime_config.rollback()` setzt `runtime_overrides.json` auf den Stand vor dem letzten `patch()`-Aufruf zurück; Admin-Endpoint `POST /api/config/rollback` stellt diesen Mechanismus im Panel bereit. `/api/training` POST validiert Range-Checks für `RETRAIN_INTERVAL_HOURS` (1–168) und `DATASET_REBUILD_INTERVAL_MIN` (5–1440). Neue `api_health_check.py` prüft täglich um 05:15 die Erreichbarkeit aller 5 externen APIs (ARSO, Open-Meteo, GeoSphere, EUMETView, Blitzortung) mit Latenz-Messung und Spec-Prüfung; Status im Admin-Panel via `GET /api/api_health`, manueller Trigger via `POST /api/api_health/run`. |
| v1.8 | Mai 2026 | CPU-Monitoring: `cpu_monitor.py` sampelt alle 5 Min CPU-Auslastung aller Kerne via psutil. Dashboard zeigt 24h-Liniendiagramm (Ø Gesamt + Einzelkerne togglebar). Neuer Scheduler-Job `cpu_monitor` (IntervalTrigger 5 Min). Neuer API-Endpoint `GET /api/cpu_history`. Pfad `SAVE_PATHS["system"]` in `config.py` ergaenzt. |

---

**WetterExtended Benutzerhandbuch v1.1**  
**Stand:** Mai 2026  
**Repository:** github.com/IVOBLA/WetterExtended


---

# 24 NEU: Vollständiges API-Request/Response-Logging

**Modul:** `debug_utils.py` (Funktion `log_api_call`, `log_http_response`)  
**Frontend:** `Dashboard.jsx`  
**API:** `GET /api/api_calls/last`

Jeder externe HTTP-Request wird nun vollständig protokolliert — ohne Kürzung.

## 24.1 Log-Format

Jeder Eintrag in `api_call_counts.jsonl` enthält:

| Feld | Beschreibung |
|---|---|
| `ts` | UTC-Zeitstempel (ISO 8601) |
| `service` | Name des externen Dienstes |
| `method` | HTTP-Methode (GET/POST/…) |
| `url` | Vollständige URL (Secrets maskiert) |
| `status` | HTTP-Statuscode |
| `duration_ms` | Antwortzeit in Millisekunden |
| `request.payload` | Request-Payload (vollständig, maskiert) |
| `response.body_json` | JSON-Antwort als Objekt (nie als String) |
| `response.body_text` | Text-/XML-Antwort (vollständig) |
| `response.binary` | `true` bei KMZ/TIFF/Bilddaten |
| `response.content_length` | Dateigröße in Bytes (bei Binär) |
| `response.sha256` | SHA-256-Prüfsumme (bei Binär) |
| `response.saved_to` | Lokaler Speicherpfad (bei Binär) |
| `response.truncated` | Immer `false` — keine Kürzung mehr |

## 24.2 Dashboard-Panel

Das Dashboard zeigt ausschließlich ein **„Letzter API-Request / Response"**-Panel:

- **Service-Dropdown** oben rechts: zeigt alle Services der letzten 24h zur Auswahl
- **Ohne Auswahl:** letzter Request egal welcher Service
- **Mit Auswahl:** letzter Request des gewählten Services
- **JSON-Body:** formatiert als einrückbares Objekt (kein doppeltes Escaping)
- **Text-Body:** direkter Text (XML, CSV, …)
- **Binärantworten:** Metadaten-Box mit Dateigröße, SHA-256 und lokalem Pfad

Die frühere 24h-Statistiktabelle (Anfragezähler je Service) wurde aus dem Dashboard
entfernt. Diese Daten sind weiterhin unter **Logs → API-Requests** verfügbar.

## 24.3 Unterstützte Datenquellen

| Service | Log-Typ |
|---|---|
| ARSO Radar (KMZ) | Binär + Metadaten (SHA-256, Pfad) |
| Blitzortung | JSON-Body vollständig |
| EUMETView WMS (TIFF) | Binär + Metadaten |
| Open-Meteo AROME/Pressure/LPI/GFS | JSON-Body vollständig |
| GeoSphere CAPE/Nowcast | JSON-Body vollständig |
| Atmosphärischer Snapshot | JSON-Body vollständig |

---

# 25 NEU: Intensitätszonen im Admin-Panel konfigurierbar

**Modul:** `object_tracking.py`  
**API:** `GET /api/intensity_bands`, `POST /api/intensity_bands`

Die Farbzonen innerhalb erkannter Sturmzellen (orange, rot, violett) können
jetzt über das Admin-Panel geändert werden — ohne Code-Anpassung.

## 25.1 Format

Jedes Band besteht aus vier Feldern:

```json
[
  ["label", [H_lower, S_lower, V_lower], [H_upper, S_upper, V_upper], "#hexfarbe"],
  ...
]
```

Wertebereiche: H 0–179, S 0–255, V 0–255 (OpenCV HSV).

## 25.2 Default-Konfiguration

| Label | HSV-Lower | HSV-Upper | Farbe |
|---|---|---|---|
| orange | [10, 100, 80] | [27, 255, 255] | #ff8800 |
| rot | [0, 100, 80] | [10, 255, 255] | #cc0000 |
| rot_wrap | [165, 100, 80] | [179, 255, 255] | #cc0000 |
| violett | [125, 100, 80] | [155, 255, 255] | #9900cc |

Änderungen werden sofort beim nächsten Radarbild-Zyklus wirksam —
kein Neustart notwendig.

---

# 26 NEU: Forecast-Horizonte zur Laufzeit anpassbar

**Modul:** `prediction.py`  
**API:** `GET /api/horizons`, `POST /api/horizons`

Die fünf Forecast-Horizonte (Standard: 10, 20, 30, 40, 60 Minuten) werden nun
zur Laufzeit aus `runtime_config` gelesen. Eine Änderung über das Admin-Panel
wirkt sich sofort auf neue Vorhersagen aus — bestehende Modelle müssen für
die neuen Horizonte ggf. neu trainiert werden (Warnung erscheint in den Logs
wenn Modell-Ausgabedimension nicht passt).

---

# 27 NEU: Forecast-Modus Anzeige (ML vs. Fallback)

**API:** `GET /api/forecast_stats?hours=<n>`  
**Frontend:** Dashboard (Card „Forecast-Modus")

Das Dashboard zeigt jetzt ob das System ML-basierte Vorhersagen oder den
kinematischen Fallback verwendet.

| Anzeige | Bedeutung |
|---|---|
| 🤖 ML | LightGBM-Modelle vorhanden und aktiv |
| 📐 Fallback | Keine Modelle oder Sequenz zu kurz — kinematische Extrapolation |

Der Prozentwert (z.B. „ML 82% / Fallback 18% (24h)") zeigt den Anteil je Modus
über alle erkannten Zellen der letzten 24 Stunden.

---

# 28 NEU: DEM-Kacheln Statusanzeige

**API:** `GET /api/dem_status`  
**Frontend:** Dashboard (Card „DEM-Kacheln")

Das Dashboard zeigt ob alle 8 Copernicus-GLO-30-Kacheln für Kärnten vorhanden sind.

| Anzeige | Bedeutung |
|---|---|
| 8 / 8 | Alle Kacheln vorhanden, Mosaic geladen |
| x / 8 | x Kacheln fehlen — DEM-Features liefern 0.0 für fehlende Bereiche |
| Kacheln laden… | Kacheln vorhanden, Mosaic noch nicht in RAM |

Die DEM-Kacheln werden beim ersten Start automatisch heruntergeladen (~1,4 GB).
Der Download läuft im Hintergrund und blockiert den Tracking-Loop nicht.

---

# 29 NEU: Cache-Status Übersicht

**API:** `GET /api/cache_status`  
**Frontend:** Logs-Seite (Abschnitt „API-Cache Status")

Zeigt für alle externen Schnittstellen:

| Spalte | Beschreibung |
|---|---|
| Namespace | Cache-Schlüssel des Services |
| Status | FRESH (TTL nicht abgelaufen), STALE (abgelaufen), MISSING (noch kein Request) |
| Alter | Wie alt ist der Cache-Eintrag |
| TTL | Konfiguriertes Ablaufintervall |
| Nächster Abruf in | Verbleibende Zeit bis nächster HTTP-Request nötig |
| Letzter Abruf | UTC-Zeitstempel des letzten echten HTTP-Requests |

Damit ist laut Zieldefinition erfüllt: unnötige Fremdrequests werden sichtbar
reduziert und deren Aktualisierungsintervalle sind dokumentiert.

Standard-TTL-Werte:

| Service | TTL | Begründung |
|---|---|---|
| Blitzortung | 60 s | Aktualisiert jede Minute |
| GeoSphere TAWES | 600 s | 10-Minuten-Messintervall |
| EUMETView WMS | 900 s | MSG Full Earth Scan alle 15 Min |
| Open-Meteo AROME (icon_d2) | 1800 s | Modell-Run alle 3 h, Werte stündlich |
| GeoSphere CAPE | 1800 s | Wie AROME |
| Open-Meteo Extended | 900 s | 15-Min-Puffer |
| Open-Meteo Synoptic | 3600 s | 500-hPa-Werte ändern sich selten |

---

# 30 Automatisierter End-to-End Test

**Datei:** `tests/test_locations_e2e.py`

Führt folgende Prüfungen aus:

1. `annotate_locations()`: Zelle im Ort-Radius → `hit_type='current'`
2. `annotate_locations()`: Zelle außerhalb → keine hits
3. `annotate_locations()`: Zelle erreicht Ort in 30 Minuten → Forecast-Hit
4. `pixel_to_geo()`: gibt keine (0,0)-Koordinaten für Kärnten-Bildpixel zurück
5. `/api/objects` (wenn Flask läuft): `forecast_mode` und `forecast_lat_10` vorhanden
6. `forecast.kmz` (wenn vorhanden): enthält gültige KML-Datei

Ausführung:
```bash
cd ~/wetterprojekt
python3 tests/test_locations_e2e.py
```


---

# 22 NEU: Rollenbasiertes Benutzermanagement

**Dateien:** `auth.py`, `frontend/src/context/AuthContext.jsx`,
`frontend/src/pages/UserManagement.jsx`, `frontend/src/pages/Login.jsx`

Das Admin-Panel ist ab dieser Version durch ein vollständiges JWT-basiertes
Benutzermanagement gesichert. Die frühere nginx Basic-Auth und der
`ADMIN_API_TOKEN`-Mechanismus wurden vollständig ersetzt.

## 22.1 Rollen

| Rolle | Beschreibung |
|---|---|
| `superadmin` | Alle Rechte + Benutzerverwaltung (`/users`) |
| `admin` | Alle Konfigurationen ändern, kein User-Management |
| `operator` | Training starten, Radar-Refresh — keine Konfiguration |
| `viewer` | Nur lesender Zugriff auf alle Daten |

## 22.2 Login

Das Admin-Panel leitet nicht eingeloggte Benutzer automatisch auf `/login` weiter.
Das Passwort des initialen `admin`-Benutzers (superadmin) steht in
`.admin_password` im Projektverzeichnis.

| Endpoint | Methode | Beschreibung |
|---|---|---|
| `/api/auth/login` | POST | Login: gibt JWT Access Token zurück |
| `/api/auth/logout` | POST | Logout: invalidiert Refresh-Cookie |
| `/api/auth/refresh` | POST | Access Token erneuern via HttpOnly-Cookie |
| `/api/auth/me` | GET | Aktuellen User abfragen |

## 22.3 Token-Strategie

- **Access Token:** JWT, 1 Stunde Laufzeit, lebt nur im Browser-Memory (kein localStorage)
- **Refresh Token:** JWT, 7 Tage, HttpOnly-Cookie — wird bei jedem Refresh rotiert
- **Auto-Refresh:** 5 Minuten vor Ablauf des Access Tokens automatisch erneuert
- **Blacklist:** Invalidierte Refresh-Tokens werden in `users.db` gespeichert

## 22.4 Benutzerverwaltung

Die Seite **👥 Benutzer** im Admin-Panel (nur für `superadmin` sichtbar) ermöglicht:

- Neue Benutzer anlegen (mit Rolle)
- Rolle eines bestehenden Benutzers ändern
- Benutzer deaktivieren / reaktivieren (kein echtes Löschen — Audit-Trail bleibt)
- Passwort zurücksetzen

## 22.5 Datenbank

`users.db` (SQLite, WAL-Modus) liegt im Projektverzeichnis.

- **`--mode=upgrade`:** `users.db` wird NICHT angefasst — alle Benutzer bleiben erhalten
- **`--mode=full`:** `users.db` bleibt erhalten — alle Benutzer, Rollen und Passwörter bleiben bestehen.
  `init_db()` läuft beim App-Start und legt fehlende Tabellen nach (idempotent).
  Nur wenn `users.db` manuell gelöscht wird, legt `init_db()` einen neuen Superadmin an
  (Passwort aus `.admin_password`).

## 22.6 `.env`-Variablen

| Variable | Beschreibung |
|---|---|
| `JWT_SECRET` | Zufälliger Secret für JWT-Signierung (wird bei install.sh generiert). Wenn nicht gesetzt: zufälliger Wert pro App-Start (Sessions werden nach Neustart ungültig). |

> **Hinweis:** `ADMIN_API_TOKEN` und `ADMIN_REQUIRE_TOKEN` werden nicht mehr verwendet
> und können aus `.env` entfernt werden.

---

# 31 NEU: Erweiterte konvektive ML-Features

**Modul:** `compute_extra_features.py`
**Datenquelle:** rein rechnerisch aus bereits abgerufenen Werten — **kein zusätzlicher API-Call**.

Sieben physikalisch motivierte **Approximations-Features** wurden ergänzt. Sie laufen in der
Live-Pipeline nach den konvektiven Diagnose-Indizes und stehen LightGBM/LSTM zur Verfügung.

| Feature | Einheit | Bedeutung |
|---|---|---|
| `dcape` | J/kg | Downdraft-CAPE-Proxy (trockene Mittelschicht + steile Lapse-Rate → starke Fallwinde) |
| `shear_0_1km_speed` | km/h | Low-Level-Scherung 10 m → 850 hPa |
| `shear_0_3km_speed` | km/h | Scherung 10 m → 700 hPa |
| `srh_0_3km` | m²/s² | Storm-Relative-Helicity-Proxy (Rotationspotenzial) |
| `cape_trend_30min` | J/kg | CAPE-Trend der Zelle über ~30 min (Intensivierung) |
| `li_trend_30min` | °C | Lifted-Index-Trend der Zelle über ~30 min |
| `vil_proxy` | — | Vertikal-integrierter-Flüssigwasser-Proxy (Hagel-/Schwere-Indikator) |

> **Hinweis:** Es handelt sich um Approximationen aus vorhandenen Größen, keine NWP-Direktwerte.
> Trend-Features nutzen einen prozess-lokalen Ringpuffer (40-min-Fenster) und liefern erst nach
> ~20 min Laufzeit von Null verschiedene Werte. Bei Feature-Änderung müssen Modelle neu trainiert werden.

---

# 32 NEU: Schwere-Vorhersage — Trainingsdatensatz

**Modul:** `severity_dataset.py`
**Ausgabe:** `train_data/dataset/tabular_severity.parquet`

Baut die Trainingsbasis für die hazard-spezifische Schwere-Vorhersage (Regen, Böen).
Die Zielwerte sind **real beobachtete** Werte +20 min an der Zellposition — gewonnen aus
GeoSphere-Nowcast und TAWES-Stationsdaten (kein zusätzlicher API-Call, nutzt die bereits
gespeicherten Objekt-/Wetterdateien).

| Zielwert | Einheit | Quelle (Maximum der verfügbaren) |
|---|---|---|
| `rain_mm_h` | mm/h | Nowcast-Regenrate, 15-min-Summe×4, TAWES-RR×6 |
| `gust_kmh` | km/h | Nowcast-Böen, TAWES-FFX, 10-m-Böen |

> Hagel hat keine Bodenwahrheit und wird **nicht** trainiert (physikalischer Index in der
> Vorhersage). Mindestens 30 Samples sind nötig, sonst wird keine Datei geschrieben.

---

# 33 NEU: Schwere-Vorhersage — Modelltraining

**Modul:** `severity_training.py`
**Modelle:** `train_data/models/current/lgbm_severity_rain.txt`, `lgbm_severity_gust.txt`
**Metriken:** `severity_metrics.json` (Holdout-MAE)

Zwei LightGBM-Regressoren sagen die erwartete Niederschlagsmenge (mm/h) und Spitzenböe (km/h)
für eine Zelle +20 min voraus. Training läuft im bestehenden Retrain-Job (nur bei
`LOCAL_TRAINING=True`), mit zeitbasiertem Holdout (letzte 20 % als Test). Die mittlere
Abweichung je Ziel ist nach Prompt 5 im Admin-Panel unter Genauigkeit sichtbar.

---

# 34 NEU: Schwere-Vorhersage — Anzeige

**Module:** `severity_predict.py` (Pipeline), Karten-Popup (`MapView.jsx`, `MapFullscreen.jsx`)

Jede Sturmzelle erhält ein `severity`-Objekt, das im Karten-Popup angezeigt wird:

| Anzeige | Bedeutung |
|---|---|
| Schwere 1–4 | Gesamtstufe aus Regen + Böen + Hagel (4 = sehr schwer) |
| 🌧 mm/h | Erwartete Niederschlagsmenge (+20 min, LightGBM) |
| 💨 km/h | Erwartete Spitzenböe (+20 min, LightGBM) |
| 🧊 klein/groß | Hagel-Kategorie (physikalischer Index: SHIP, Gefriergrenze, Overshooting, VIL) |

> Regen und Böen sind ML-Vorhersagen mit echten Beobachtungs-Targets (verifizierbar, siehe
> Genauigkeits-Seite). Hagel ist ein physikalischer Index ohne ML, da keine Bodenwahrheit vorliegt.
> `mode: fallback` bedeutet: noch kein trainiertes Modell — Nowcast-Persistenz wird verwendet.


---

# 35 NEU: Schwere-Verifikation (Closed-Loop)

**Modul:** `severity_verification.py`
**API:** `GET /api/severity_accuracy?hours=<1-168>` (Default 24 h)

Vergleicht die vorhergesagten Regen-/Böen-Werte mit den +20 min später beobachteten Werten
(Nowcast/TAWES) und liefert die mittlere Abweichung:

| Feld | Bedeutung |
|---|---|
| `samples` | Anzahl verifizierter Zell-Vorhersagen |
| `mae_rain_mm_h` | mittlere absolute Abweichung Niederschlag (mm/h) |
| `mae_gust_kmh` | mittlere absolute Abweichung Böen (km/h) |

Die Verifikation läuft stündlich im Accuracy-Job mit. Die grafische Darstellung im Admin-Panel
(Genauigkeits-Seite) folgt in einem separaten Schritt.

---

# 36 NEU: Zell-Prognose-Animation auf der Karte

**Modul:** `MapView.jsx` (Komponente `ForecastGhostLayer`)

Über der Karte gibt es einen Schalter **🔮 Zell-Prognose** und einen Schieberegler **+N min**
(0–60 min). Bei aktiviertem Schalter wird die Zell-Kontur entlang des vorhergesagten Pfades
verschoben und als **gestricheltes, halbtransparentes violettes Polygon** dargestellt.

| Eigenschaft | Bedeutung |
|---|---|
| Position | linear interpolierte Forecast-Position der Zelle bei +N min |
| Stil | gestrichelt, violett — **klar als Prognose**, keine Messung |
| Deckkraft | nimmt mit zunehmendem Vorlauf ab (Unsicherheit steigt) |

Die Berechnung erfolgt rein im Browser aus `contour_geo` und den Forecast-Positionen —
**kein zusätzlicher Server-/API-Aufruf**.

---

# 37 NEU: 12-Stunden-Ausblick — Datenbasis

**Modul:** `fetch_outlook_series.py`
**Ausgabe:** `train_data/forecast/atmosphere_timeseries.json`
**Scheduler-Job:** `outlook_series` (alle 30 min, mit Frische-Guard)

Holt für die 36 Kärnten-Rasterpunkte die stündliche Vorhersage-Zeitreihe (+0…+12 h) der
konvektionsrelevanten Felder (CAPE, Lifted Index, CIN, Precipitable Water, 10-m-/700-hPa-Wind,
Böen, Gefriergrenze, T500/T700). Diese Zeitreihe ist die Eingangsgröße für den
Konvektions-Ausblick.

> **API-Schonung:** Ein Frische-Guard verhindert einen Netz-Request, solange die Datei jünger als
> `OUTLOOK_SERIES_TTL_MIN` (Default 30) ist. Pro Lauf max. 5 Batch-Requests → ≈ 240 Req/Tag.
> Bei Parameter-Fehlern wird automatisch auf einen Minimalsatz zurückgefallen.

---

# 38 NEU: 12-Stunden-Konvektions-Ausblick

**Modul:** `convective_outlook.py`
**API:** `GET /api/outlook` (optional `?hour=N`)
**Ausgabe:** `train_data/forecast/outlook_12h.json`
**Scheduler-Job:** `outlook_compute` (alle 30 min, nur lokale Dateien)

Der Ausblick beantwortet **wo und wann** in den nächsten 12 Stunden Risikozonen entstehen und
**wie schwer** sie ausfallen könnten. Pro Stunde (+1…+12 h) entsteht ein Risiko-Raster (1–3) mit
Schwere-Proxys je ~5×5-km-Zelle:

| Feld | Bedeutung |
|---|---|
| `risk` | 1 = niedrig (gelb), 2 = mäßig (orange), 3 = hoch (rot) |
| `severity.rain_mm_h` | erwartete Niederschlagsrate (Proxy aus PW × CAPE) |
| `severity.gust_kmh` | erwartete Böe (Proxy aus Böen-Feld + Lapse-Rate) |
| `severity.hail_index` | SHIP-ähnlicher Hagel-Index; `hail_cat` = kein/klein/gross |
| `info.dominant` | dominante Ursache (Hagel/Regen/Böe/Instabilität) |

> **Methode:** zutatenbasierte Heuristik (CAPE/LI/CIN/Scherung/Gefriergrenze) mit Tagesgang-Gewichtung,
> moduliert durch einen **klimatologischen Attraktor-Prior** aus der eigenen Zell-Historie
> (Frequenzkarte je Grobraster × Monat). Damit lernt das System, an welchen Orten zu welcher
> Jahreszeit Gewitter bevorzugt auftreten (Berge/Täler) — ohne externen API-Call.
> Liegt keine Historie vor, wird die reine Heuristik verwendet (Fallback).

---

# 39 NEU: Ausblick-Seite (`/ausblick`)

Neue Frontend-Seite mit interaktiver Leaflet-Karte und **Zeit-Slider (+1…+12 h)** für den
Konvektions-Ausblick. Pro gewählter Stunde werden die Risiko-Rasterflächen (gelb/orange/rot)
angezeigt; der Hover-Tooltip nennt Risikostufe, dominante Ursache, erwarteten Regen (mm/h),
Böen (km/h), Hagel-Kategorie/Index sowie CAPE, LI und SHIP. Eine Farblegende erläutert die Stufen.

Erreichbar über den Menüpunkt „🔭 12-h-Ausblick". Datenquelle: `GET /api/outlook` (siehe Abschnitt 38).


---

## 12h-Prognose-Karte und Outlook-Risikozonen

Die Karte zeigt in der 12h-Prognose-Ansicht atmosphärische Risikozonen basierend auf
CAPE (Konvektiv Verfügbare Potentielle Energie) und Windgeschwindigkeit.

### 12h-Outlook Risikozonen

In der 12h-Prognose-Ansicht werden **Risikozonen** als farbige **Rasterflächen (~5×5 km)**
dargestellt — identisch mit dem Risiko-Raster auf der Hauptkarte. Nur Flächen mit messbarer
Konvektionswahrscheinlichkeit (Risiko ≥ 1) werden angezeigt. Gebiete ohne Konvektionspotenzial
bleiben transparent.

**Farbskala:**
| Farbe | Risiko | Bedeutung |
|-------|--------|-----------|
| Gelb | Niedrig | Schwaches Konvektionspotenzial |
| Orange | Mäßig | Mäßiges Konvektionspotenzial |
| Rot | Hoch | Erhöhtes Konvektionspotenzial (Hagel, Sturmböen möglich) |

Hover-Tooltip je Rasterfläche: Risikostufe, dominante Ursache (Hagel/Regen/Böen/Instabilität),
erwartete Niederschlagsrate (mm/h), Böen (km/h), Hagel-Kategorie/Index sowie CAPE, LI und SHIP.

**Datenquelle:** `train_data/forecast/outlook_12h.json` (alle 30 Minuten aktualisiert,
kombinierter CAPE+LI+Scherung+Gefriergrenze-Score je ~5×5-km-Zelle, +1 bis +12 Stunden).

---

# 33 NEU: EWMA-Geschwindigkeitsgewichtung kinematischer Forecast (P27)

**Module:** `prediction.py`, `object_tracking.py`
**Konfiguration:** `TRACK_HISTORY_LEN`, `KINEMATIC_EWMA_ALPHA` in `config.py` / runtime

## 33.1 Motivation

Bisher verwendete `_append_kinematic()` ein **gleichgewichtiges Mittel der letzten
3 Frames**. Bei Kursänderungen floss die alte Richtung gleichwertig ein — der
kinematische Forecast hinkte der tatsächlichen Zugbahn hinterher.

## 33.2 EWMA-Gewichtungsformel

Alle History-Frames (bis `TRACK_HISTORY_LEN`) fließen ein, aber mit exponentiell
abnehmendem Gewicht für ältere Einträge:

```
w[i] = α × (1−α)^(n−1−i)    normiert auf Summe 1
(Index 0 = ältestes Intervall, Index n−1 = neuestes)
```

Beispiel **α = 0.6**, 3 Frames (2 Intervalle):

| Intervall | Alter | Rohgewicht | Normiert |
|---|---|---|---|
| h[0]→h[1] | 4 min alt | 0.24 | 28,6 % |
| h[1]→h[2] | 2 min alt | 0.60 | 71,4 % |

Das neueste Intervall dominiert mit 71 % statt 50 % beim einfachen Mittel.

## 33.3 History-Buffer

`TRACK_HISTORY_LEN` wurde von **3 auf 6** erhöht. Mehr Datenpunkte stehen sowohl
für den EWMA-Forecast als auch für ML-Sequenz-Features zur Verfügung. Der
LSTM-Input (`ML_SEQUENCE_LENGTH`) bleibt unverändert.

## 33.4 Konfiguration

| Parameter | Default | Beschreibung |
|---|---|---|
| `TRACK_HISTORY_LEN` | `6` | Anzahl gespeicherter Frames pro Zelle (min. 2) |
| `KINEMATIC_EWMA_ALPHA` | `0.6` | EWMA-Faktor: 0.01=gleichgewichtet, 0.99=nur neuester Frame |

Beide Parameter sind im Admin-Panel (Konfigurationsseite → Erweitert / Sonstiges)
oder direkt in `runtime_overrides.json` änderbar.

## 33.5 kinematic_source-Label

Das Feld `kinematic_source` im Objekt-JSON zeigt die Berechnungsbasis an:

| Wert | Bedeutung |
|---|---|
| `ewma_6f_a0.6` | EWMA aus 6 Frames, alpha=0.6 (Normalfall nach Einlaufphase) |
| `ewma_3f_a0.6` | EWMA aus 3 Frames (Zelle noch jung) |
| `ewma_novts_4f` | EWMA aus 4 Frames ohne Timestamps (vx/vy-Fallback) |
| `history_6_fallback` | Einfaches Mittel (Exception-Fallback) |
| `kalman_only` | Weniger als 2 Frames verfügbar (neue Zelle) |
