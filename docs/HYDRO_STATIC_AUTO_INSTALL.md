# Hydro-Static Auto-Installation

`install.sh --mode full` startet automatisch `python3 hydro_static_import.py --auto`. Dabei werden keine kostenpflichtigen APIs und keine Paid-Tiers verwendet.

## Offizielle freie Quellen

* Live-Pegel Kärnten: `https://info.ktn.gv.at/asp/hydro/daten/json/hdkaernten_abfluss_lite.json`
* INSPIRE Drainage Basins: `https://inspire.lfrz.gv.at/000801/ds/AT_DRAINAGEBASIN_GML.zip`
* INSPIRE Watercourse Links: `https://inspire.lfrz.gv.at/000801/ds/AT_WATERCOURSELINK_GML.zip`
* INSPIRE Watercourses als Fallback: `https://inspire.lfrz.gv.at/000801/ds/AT_WATERCOURSE_GML.zip`

## Cache und erzeugte Dateien

Downloads werden unter `train_data/hydro/static/source/_downloads/` gecached und erst nach Ablauf der TTL oder bei 0-Byte-Dateien erneut geladen. Erzeugt werden `hydro_stations.geojson`, `basins.geojson`, `flowlines.geojson`, `station_network_index.json`, `hydro_stations.geojson` im generated-Verzeichnis, `station_catchments.geojson` und `hydro_static_status.json`.

## Topologie und Hydro-Impact

Hydro-Impact wird nur für Stationen mit `impact_eligible=true` aktiv. Dafür müssen explizite oder aus Downstream-/GGN-Attributen ableitbare oberliegende Einzugsgebiete vorhanden sein. Nächster-Pegel- oder reine Distanzlogik bleibt Diagnose und aktiviert keinen produktiven Impact.

## Status prüfen

```bash
python3 hydro_static_import.py --status
curl http://localhost:5000/api/hydro/status
```

## Bewusst neu herunterladen

Zum Erzwingen eines erneuten Downloads den betroffenen Cache im Verzeichnis `train_data/hydro/static/source/_downloads/` löschen oder auf 0 Byte setzen und anschließend `python3 hydro_static_import.py --download-all` bzw. `--auto` ausführen.
