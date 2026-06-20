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
