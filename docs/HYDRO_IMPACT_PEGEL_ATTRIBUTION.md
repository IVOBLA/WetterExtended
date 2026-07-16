# Hydro-Impact / Pegel-Attribution

Hydro-Impact beschreibt einen **plausiblen hydrologischen Zusammenhang** zwischen einer radarerkannten Niederschlagszelle und einer späteren Pegel- oder Abflussreaktion. Das Modul liefert bewusst **keine harte Kausalitätsaussage**, keine amtliche Hochwasserwarnung und keinen Ersatz für geprüfte amtliche Endwerte. Live-Hydro-Werte sind Rohdaten beziehungsweise Live-Indikatoren und können nachträglich korrigiert, qualitätsgesichert oder verworfen werden.

## Warum „nächster Pegel“ fachlich falsch ist

Eine rein räumliche Nähe zum Pegel ist für Hydro-Impact unzulässig. Niederschlag neben einem Gewässer, in einem anderen Teileinzugsgebiet oder unterhalb der Messstelle kann den Pegel oberhalb oder an der Messstelle nicht belastbar erklären. Der „nächste Pegel“ kann deshalb hydrologisch irrelevant sein, während ein weiter entfernter Pegel im selben oberliegenden Fließsystem fachlich plausibler ist.

Zulässig ist nur diese Kombination:

1. Die Niederschlagszelle schneidet das lokal bekannte **oberliegende Einzugsgebiet** der Station.
2. Die Prüfung verwendet einen hydrologischen **Zeitversatz** zwischen Niederschlagsereignis und möglicher Pegel-/Abflussreaktion.
3. Mindestfläche, Zellanteil, Dauer, relevante Intensität und Verifikationsschwellen werden konservativ erfüllt.

Ohne oberliegende Topologie und Zeitversatz wird kein Hydro-Impact erzeugt.

## Statische Hydrologie und `impact_eligible`

Statische Hydrologie liegt lokal unter `train_data/hydro/static/generated/`. Produktive Hydro-Impacts werden ausschließlich für Stationen erzeugt, deren statischer Index `impact_eligible=true` meldet. Dieses Flag bedeutet aktuell konservativ: `upstream_catchment_ids` sind in den lokalen statischen Daten explizit vorhanden, gegen vorhandene Basin-Geometrien validiert und daraus wurde ein geometrisch vereinigtes oberliegendes Einzugsgebiet (`station_catchment`) erzeugt. Eine automatische gerichtete Fließtopologie aus dem Gewässernetz wird derzeit noch nicht berechnet.

`impact_eligible=false` bedeutet nicht, dass eine Station fachlich unwichtig ist. Es bedeutet nur, dass WetterExtended für diese Station keinen belastbaren automatischen Hydro-Impact ableiten darf. Typische Gründe sind fehlende oder unvollständige Upstream-Topologie, fehlende Geometrien, ungültige Geometrien oder nicht erfüllte Mindestanforderungen an die statische Zuordnung. Die Station kann weiterhin angezeigt oder diagnostisch ausgewertet werden, erzeugt aber keinen produktiven Impact.

## Warum `station_basin` allein nicht genügt

Das Stations-Basin beschreibt nur das direkte Basin oder die lokale Einordnung der Messstelle. Es ist nicht automatisch identisch mit dem gesamten oberliegenden Einzugsgebiet, das einen Pegel speisen kann. Eine Zelle kann oberhalb im hydrologisch relevanten Zuflussgebiet liegen, ohne im Stations-Basin zu liegen; umgekehrt kann eine lokale Basin-Geometrie ohne vollständige Upstream-Kette eine falsche Sicherheit erzeugen. Deshalb reicht `station_basin` allein nicht als Entscheidungsgrundlage.

## Warum Flowline-Snapping nur Diagnose ist

Flowline-Snapping kann zeigen, zu welcher Gewässerlinie eine Station oder ein Punkt geometrisch nahe liegt. Diese Nähe beweist aber keine vollständige Fließverbindung, keine Lage oberhalb der Station und keine passende Reisezeit. Snapping wird deshalb nur als Diagnosemetadatum (`snapped_flowline_id`, `snap_distance_m`) verwendet und darf keine produktive Pegel-Attribution begründen. Solange keine echte gerichtete Fließtopologie verfügbar ist, bleiben `flow_distance_available=false` und `flow_distance_km=null`.

## Statusfelder für spätere Topologie

Der statische Index trennt bewusst zwischen heutiger konservativer Logik und einer später ergänzbaren echten Fließtopologie:

* `topology_source`: derzeit `conservative_declared_upstream_catchments`, wenn validierte `upstream_catchment_ids` die Catchment-Union tragen; sonst `none`.
* `upstream_source_quality`: beschreibt, ob die Upstream-IDs gültig, unauflösbar oder fehlend sind.
* `flow_distance_available`: bleibt `false`, bis eine belastbare gerichtete Fließwegdistanz berechnet wird.
* `flow_distance_km`: bleibt `null`, solange `flow_distance_available=false` ist.

## Warum das System konservativ lieber keinen Impact erzeugt

Wenn die Upstream-Topologie fehlt, kann WetterExtended nicht sicher unterscheiden, ob Niederschlag tatsächlich oberhalb einer Station, neben dem relevanten Gewässer oder unterhalb der Messstelle gefallen ist. Ein erzeugter Impact würde dann eine fachliche Genauigkeit vortäuschen, die die lokalen Daten nicht hergeben. Das System entscheidet daher konservativ: lieber kein Hydro-Impact als eine scheinbar präzise, aber hydrologisch nicht abgesicherte Zuordnung.

## Live-Daten, Cache und fehlende Daten

Live-Hydro-Daten für Kärnten werden mit TTL/Cache unter `train_data/hydro/live/` verwendet. Diese Werte sind Live-Indikatoren und keine geprüften amtlichen Endwerte. Bei fehlenden statischen Daten, fehlender Geometrie oder fehlender Shapely/GEOS-Unterstützung erzeugt WetterExtended keinen produktiven Hydro-Impact und setzt Gründe wie `hydro_static_missing` oder `hydro_geometry_unavailable`. Bei Live-Problemen können `cache_used` oder `live_error` erscheinen; daraus wird keine neue fachliche Zuordnung abgeleitet. Karte, API und KMZ bleiben stabil und zeigen Hydro optional oder leer an.

## Statuswerte

* `pending`: Das zulässige Zeitfenster läuft noch oder die Verifikation steht aus; es gibt noch keine abschließende Bewertung.
* `confirmed`: Die beobachtete Pegel-/Abflussänderung passt plausibel zum geprüften Zeitfenster und den Schwellen. Das ist nur ein plausibler Zusammenhang, keine bewiesene Ursache.
* `rejected`: Im geprüften Zeitfenster ist aus den verfügbaren Rohdaten kein belastbarer Zusammenhang ableitbar. Das beweist nicht, dass es gar keinen Effekt gab.
* `ambiguous`: Die Lage ist uneindeutig, zum Beispiel wegen Messlücken, konkurrierender Zellen im selben oberliegenden Einzugsgebiet, unklarer Reaktion oder unzureichender Datenqualität.

Verifikationszustände werden in `train_data/hydro/impact/hydro_impact_state.json` persistiert. Beim Laden offener Kandidaten werden alle `hydro_impact_YYYY-MM-DD.jsonl` gelesen, nach `event_id` dedupliziert und bereits `confirmed`, `rejected` oder `ambiguous` verifizierte Events ausgeschlossen. Alte JSONL-Zeilen bleiben auditierbar, wirken aber nicht dauerhaft als konkurrierende Pending-Zellen.

## Admin-Konfiguration

Konfigurierbar sind insbesondere:

* `HYDRO_ENABLED`
* `HYDRO_API_TTL_SECONDS`
* `HYDRO_MIN_OVERLAP_AREA_KM2`
* `HYDRO_MIN_OVERLAP_RATIO_CELL`
* `HYDRO_MIN_DURATION_MIN`
* `HYDRO_RELEVANT_INTENSITIES`
* `HYDRO_DEFAULT_LAG_MIN`
* `HYDRO_LAG_WINDOW_MIN`
* `HYDRO_VERIFY_MIN_DELTA_Q_M3S`
* `HYDRO_VERIFY_MIN_DELTA_W_CM`
* `HYDRO_VERIFY_MIN_RELATIVE_DELTA_PCT`
* `HYDRO_VERIFY_MAX_GAP_MIN`
* `HYDRO_STATION_OVERRIDES`

Stations-Overrides dürfen die Laufzeitkonfiguration steuern, ersetzen aber nicht die statische Anforderung an `impact_eligible=true`.

## API, Anzeige und Fehlerprotokoll

Die Hydro-GET-API verwendet ein einheitliches Envelope-Format `ok/status/data`. Frontend-Layer müssen GeoJSON defensiv als `response.data || response` lesen; fehlende oder kaputte FeatureCollections ergeben leere Layer. Linien zwischen Zelle und Pegel werden nur dargestellt, wenn sowohl Zell- als auch Stationskoordinaten vorhanden sind.

Hydro-Netzwerkfehler ohne HTTP-Response werden unter `train_data/external_responses/hydro/` mit `status_code=0`, Fehlertyp, Fehlermeldung sowie Cache-/Fallback-Markierung protokolliert und erscheinen damit im Debug-Export.

## Auto-Installation der statischen Hydro-Basis

Im Full-Installationsmodus erzeugt `install.sh` die statische Hydro-Basis über `hydro_static_import.py --auto`. Die Daten stammen aus offiziellen freien INSPIRE-/Kärnten-Quellen, werden lokal gecached und nach EPSG:4326 GeoJSON konvertiert. Produktiver Hydro-Impact bleibt konservativ: `impact_eligible=true` wird nur gesetzt, wenn eine belastbare Upstream-Topologie aus expliziten Upstream-Catchments oder nachvollziehbaren Downstream-/GGN-Attributen vorliegt. Fehlt diese Topologie, meldet der Status `upstream_topology_missing` und Distanz-/Snapping-Informationen dienen nur der Diagnose.

## Hydro-Flood-ML-Erweiterung

Neben der bestehenden heuristischen Hydro-Impact- und `q_forecast_m3s`-Logik gibt es einen strikt getrennten Hydro-Flood-Risk-Pfad. Die bestehende Logik wird nicht ersetzt: `compute_cell_catchment_overlap`, `evaluate_hydro_impact`, `score_hydro_impact` und die Rational-Methoden-Schätzung bleiben als Attribution bzw. transparenter Fallback erhalten.

Das neue Ziel ist ausschließlich die Hochwassergefahr (`flood_expected`) aus aktuellem Durchfluss `current_q_m3s`, dem stationsspezifischen Admin-Grenzwert `mark_q_m3s` (`Q ≥ ...`) und Niederschlag im oberliegenden Einzugsgebiet. Es wird kein zweiter Grenzwert eingeführt. Wenn `mark_q_m3s` fehlt, wird nur der bereits vorhandene globale `HYDRO_MAP_MARK_Q_M3S` als Fallback verwendet; fehlt auch dieser, liefert die Bewertung `missing_station_q_threshold` und setzt `flood_expected` nicht künstlich auf wahr.

Hydro-Flood-ML lernt fachlich die spätere Änderung von `q_m3s` nach Niederschlag im Einzugsgebiet. Interne Label-Zuordnung verwendet nur die bestehenden Lag-/Verifikationswerte (`HYDRO_LAG_WINDOW_MIN`, `HYDRO_DEFAULT_LAG_MIN`, `HYDRO_VERIFY_MAX_GAP_MIN`, `HYDRO_VERIFY_MIN_DELTA_Q_M3S`). Es gibt keine öffentliche Hydro-Zeitforecast-Liste und keine `w_cm`-Prognose.

Niederschlag wird priorisiert: gesicherte/observed Werte zuerst, dann Nowcast/Radar/Zellableitung, zuletzt Proxy. Ein Proxy darf beobachtete Werte nie überschreiben. Jede Bewertung dokumentiert Quelle, Qualität, Alter und Proxy/Observed-Status.

Der Zellforecast bleibt unabhängig: Hydro liest aktuelle erkannte Zellen nur read-only zur Einzugsgebietszuordnung und schreibt keine Hydro-, `q_`, `w_`- oder `hq`-Features in `ML_CELL_FEATURES`.

## B408: Hydro-Flood-Q-Prognose aus Catchment-Niederschlag

Der Flood-Risk-Pfad lädt die lokalen Einzugsgebiete zentral aus `train_data/hydro/static/generated/station_catchments.geojson` und indexiert sie nach `station_id`. Die öffentliche Stations-GeoJSON-API bleibt eine Punkt-Ausgabe; interne Catchment-Polygone werden nicht über Kartenpayloads transportiert.

Der produktive Datenfluss ist:

`Zellobjekte → produktive Zellzugbahn (forecast_lat_<H>/forecast_lon_<H>/forecast_mode_<H>) → zeitabhängige Zellpolygone → Catchment-Schnitt → räumlich deduplizierte Niederschlagswirkung → Dauer-/Routingberechnung → Q-Prognose in m³/s → Stationsgrenzwert`.

Die deterministische Wirkung pro Zeitschritt nutzt `delta_q_raw = C * i_mm_h * A_km2 / 3.6`. Mehrere Zellen werden im selben Zeitraster gemeinsam aggregiert; überlappende Flächen werden nach numerischer Intensität sortiert und nur einmal mit der stärksten belastbaren Rate gezählt. Das Routing erfolgt kausal mit `alpha = 1 - exp(-dt_min / tau_min)` und setzt immer auf dem aktuellen `current_q_m3s` auf. Fehlende Grenzwerte verhindern nur `flood_expected`, nicht die Niederschlagsanalyse.

Runtime-Parameter: `HYDRO_FORECAST_SAMPLE_STEP_MIN`, `HYDRO_FALLBACK_ROUTING_TAU_MIN`, `HYDRO_FORECAST_RUNOFF_COEFF`, `HYDRO_FORECAST_ROUTING_ATTENUATION`, `HYDRO_MIN_OVERLAP_AREA_KM2` und `HYDRO_MIN_OVERLAP_RATIO_CELL`.
