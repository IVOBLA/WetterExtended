# Hydro-Impact / Pegel-Attribution

Die Hydro-Attribution ist **nicht radiusbasiert**: Entfernung zum Pegel ist fachlich falsch, weil Niederschlag neben oder unterhalb einer Station keine belastbare Pegelreaktion oberhalb erklären kann. Verwendet wird ausschließlich ein lokal bereitgestelltes **oberliegendes Einzugsgebiet** der Station.

Eine Zelle kann nur als **plausibler Zusammenhang** gespeichert werden, wenn ihr Polygon das oberliegende Einzugsgebiet schneidet und ein hydrologischer **Zeitversatz** angewendet wird. Die Ausgabe ist keine Kausalitätsbehauptung und **keine amtliche Hochwasserwarnung**.

## Daten

* Statische Hydrologie lokal unter `train_data/hydro/static/generated/`.
* Live-Hydro Kärnten mit TTL/Cache unter `train_data/hydro/live/`.
* Live-Werte sind Rohdaten/Live-Indikatoren, keine geprüften amtlichen Endwerte.

## Status

* `pending`: Zeitfenster läuft oder Verifikation steht aus.
* `confirmed`: Pegel-/Abflussreaktion passt plausibel ins Zeitfenster.
* `rejected`: keine relevante Reaktion im Zeitfenster.
* `ambiguous`: Messlücke, mehrere Zellen im selben Einzugsgebiet oder unklare Reaktion.

Fehlende Daten werden konservativ behandelt: `hydro_static_missing`, `cache_used` oder `live_error` führen nicht zu einer fachlichen Zuordnung. Admin-Konfigurationen wie `HYDRO_ENABLED`, TTL, Schnittflächen-/Ratio-Schwellen und Stations-Overrides wirken zur Laufzeit. Karte, API und KMZ zeigen Hydro optional und bleiben bei fehlenden Daten stabil.

## Produktionsreife Attributionsregeln

Hydro-Impact wird ausschließlich für Stationen erzeugt, deren statischer Index `impact_eligible=true` meldet. Dieses Flag darf nur gesetzt werden, wenn lokale Upstream-Topologie (`upstream_catchment_ids`) vorhanden ist und daraus ein geometrisch vereinigtes oberliegendes Einzugsgebiet (`station_catchment`) erzeugt wurde. Das Stations-Basin allein und Flowline-Snapping sind nur Diagnosehinweise; sie begründen keine fachliche Zuordnung.

Ohne Shapely/GEOS wird keine produktive Hydro-Attribution erzeugt (`hydro_geometry_unavailable`). Ein Bounding-Box-Fallback darf nur Diagnosezwecken dienen. Verifikationsergebnisse bleiben vorsichtig: `confirmed` bedeutet „plausibler hydrologischer Zusammenhang“, `rejected` bedeutet „kein belastbarer Zusammenhang ableitbar“, `ambiguous` steht u. a. für Messlücken oder konkurrierende Zellen, `pending` für ein noch laufendes Zeitfenster.

Konfigurierbar sind u. a. `HYDRO_ENABLED`, `HYDRO_API_TTL_SECONDS`, `HYDRO_MIN_OVERLAP_AREA_KM2`, `HYDRO_MIN_OVERLAP_RATIO_CELL`, `HYDRO_MIN_DURATION_MIN`, `HYDRO_RELEVANT_INTENSITIES`, `HYDRO_DEFAULT_LAG_MIN`, `HYDRO_LAG_WINDOW_MIN`, `HYDRO_VERIFY_MIN_DELTA_Q_M3S`, `HYDRO_VERIFY_MIN_DELTA_W_CM`, `HYDRO_VERIFY_MIN_RELATIVE_DELTA_PCT`, `HYDRO_VERIFY_MAX_GAP_MIN` und `HYDRO_STATION_OVERRIDES`.
