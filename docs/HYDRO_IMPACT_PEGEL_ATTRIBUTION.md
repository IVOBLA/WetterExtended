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
