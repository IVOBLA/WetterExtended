
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
