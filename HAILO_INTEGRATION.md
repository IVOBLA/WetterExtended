# HAILO_INTEGRATION.md

Die gültige Hailo-Integrationsdokumentation liegt unter:

docs/HAILO_INTEGRATION.md

Diese Root-Datei ist nur ein Verweis, damit Tools den Einstieg finden.

## IR-Zeitlogik für Karten-Popups

Die produktive IR-Quelle bleibt ausschließlich EUMETView MSG FES IR108 (`msg_fes:ir108`; `EUMETVIEW_SCAN_MODE="FES"`, kein RSS-/MTG-Fallback). Die in `/karte` und `/map` angezeigten IR-Zeitangaben sind fachliche Satelliten-/WMS-Bildzeitpunkte aus der Time-Dimension des verwendeten IR108-Bildes. Downloadzeitpunkt, Pipeline-Laufzeit und Dateisystem-`mtime` sind keine fachlichen Ortungszeiten und dürfen nur als technischer Fallback bzw. zur Latenzdiagnose verwendet werden.

FES liefert typischerweise einen ca. 15-minütigen Bildtakt. Beim TIFF wird eine Sidecar-Metadatei `ir108_YYYYMMDDHHMMSS.json` geschrieben, die `observation_timestamp`, `wms_timestamp`, `downloaded_at_utc` und optional `availability_latency_min` enthält. Öffentliche IR-Vorläufer werden zusätzlich über Freshness-Limits auf Basis dieses Beobachtungszeitpunkts gefiltert, damit zu alte oder nicht mehr erkannte IR-Objekte aus der Karte verschwinden.
