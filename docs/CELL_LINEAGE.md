# Zell-Lineage (1L.1)

1L.1 führt eine stabile fachliche Zell-ID für CB-IR-Vorläufer ein. Ziel ist, eine physikalische Gewitterzelle bereits in der IR-Phase eindeutig zu benennen, bevor später Radar- oder Regenobjekte diese ID übernehmen können.

## IDs

- `ir_track_id`: technische ID des IR-Trackers, identisch zur bestehenden `ir_id` (`ir_17` usw.). Sie bleibt ein interner Tracker-Schlüssel.
- `radar_track_id`: technische ID einer Radar-/Regenzelle. In 1L.1 wird nur das Feld vorbereitet; Radarobjekte werden noch nicht aktiv umgestellt.
- `cell_id`: fachliche ID der physikalischen Zelle. Neue CB-IR-Vorläufer erhalten sofort eine stabile ID im Format `WX-YYYYMMDD-NNNN`.

## Umfang von 1L.1

1L.1 vergibt ausschließlich stabile `cell_id` Werte für CB-IR-Vorläufertracks und persistiert die Zuordnung. Das bestehende IR↔Radar-Matching und die Kartenlogik bleiben unverändert.

1L.1 macht ausdrücklich noch kein Score-Matching zwischen IR und Radar. Die spätere Radarübernahme der `cell_id` wird in 1L.2 implementiert.

## Persistenz

Die Lineage-Daten liegen lokal und offline unter:

- `train_data/cell_lineage/cell_lineage_state.json`
- `train_data/cell_lineage/cell_lineage_events.jsonl`

Der State enthält Tageszähler, `ir_track_id -> cell_id`, vorbereitete `radar_track_id -> cell_id` Mappings und die bekannten Zell-Metadaten. Neue IDs erzeugen ein JSONL-Event `ir_cell_id_created`.

## ID-Format

`cell_id` nutzt das Format:

```text
WX-YYYYMMDD-NNNN
```

Beispiel: `WX-20260618-0001`. Der Zähler ist pro Datum persistent und wird nicht zufällig erzeugt.

## Deduplizierung

In 1L.1 bleibt das bestehende Feld `display_as_precursor` maßgeblich für die Darstellung und Deduplizierung von IR-Vorläufern. In 1L.2/1L.3 wird die Radar-Deduplizierung mit `cell_id` erweitert.

## 1L.2 Score-Matching IR↔Radar

Die frühere Zuordnung „nächster IR-Track innerhalb von 40 km" reicht meteorologisch nicht aus: zwei CB-IR-Vorläufer können in demselben Suchradius liegen, Radar-Kerne können unterschiedlich stark sein und eine wachsende Wolke kann sich zwischen IR- und Radarzeitpunkt bereits sichtbar verlagert haben. 1L.2 behält deshalb 40 km als maximales Suchfenster, entscheidet aber über einen deterministischen Score.

Verwendete Score-Komponenten:

- **Räumliche Nähe** zwischen Radar-Schwerpunkt und aktuellem IR-Schwerpunkt.
- **Vorhergesagte IR-Position** aus `vx_deg_min`/`vy_deg_min`, sofern verfügbar.
- **Zeitliche Plausibilität** mit Lookback-Fenster und Freshness-Bonus.
- **Bewegungsrichtung** bei vorhandenen IR- und Radar-Vektoren.
- **Wachstums-/Konvektionssignale** wie BT-Abkühlung, Cloud-Top-Anstieg, Flächenwachstum und Overshooting-Top.
- **Meteorologisches Potenzial** aus bereits vorhandenen Feldern (`cape`, `li`/`arome_li`, `cin`, `lapse_700_500`, `ship_index`, `lightning_count`).

Das Matching lädt keine externen Daten nach und erzeugt keine neuen Requests. Es verwendet ausschließlich bereits an Radarobjekten, IR-Tracks oder im vorhandenen Weather-Kontext vorliegende Werte.

Wenn eine Radarzelle zu einer CB-IR-Vorläuferzelle passt, übernimmt das Radarobjekt die fachliche `cell_id` des IR-Tracks. Der IR-Track wird als `radar_confirmed` markiert, `display_as_precursor` wird deaktiviert und `ir_only_precursor` auf `0.0` gesetzt. Dadurch wird eine bereits bestätigte IR-Wolke nicht zusätzlich als Vorläufer angezeigt. Persistiert wird die Bestätigung in `cell_lineage_state.json` (`radar_to_cell`) und als `ir_to_radar_confirmation` in `cell_lineage_events.jsonl`.

## 1L.3 Deduplizierung in API/Karte/KMZ

1L.3 macht `cell_id` zur bevorzugten fachlichen ID für die sichtbare Darstellung einer physikalischen Zelle in API, Karte und KMZ. Technische IDs wie Radar-`id` und `ir_track_id` bleiben weiterhin im Payload und in KMZ-Daten erhalten, damit Debugging und Rückverfolgung möglich bleiben.

Sobald eine Radar-/Regenzelle eine IR-Vorläuferzelle bestätigt, ist das Radarobjekt die primäre Darstellung. Die gematchte IR-Wolke wird nicht mehr separat als IR-Vorläufer angezeigt, wenn beide dieselbe `cell_id` tragen oder der IR-Track als `radar_confirmed` bzw. `display_as_precursor=false` markiert ist. IR-Vorläufer ohne Radar-Match bleiben sichtbar, sofern `ir_only_precursor == 1.0` gilt.

Die IR-Informationen gehen bei der Deduplizierung nicht verloren: BT-Minimum, BT-Trend, Wolkenhöhe, Höhen-Trend, Flächenwachstum, Overshooting-Top, Wolkenalter und Lineage-Match-Daten werden am passenden Radarobjekt mitgeführt. Das Frontend enthält zusätzlich eine Guardrail gegen doppelte IR-Darstellung, die Hauptentscheidung liegt aber im Backend. Der KMZ-Export unterdrückt duplicate IR-Vorläufer mit bereits vorhandener Radar-`cell_id` und schreibt die wichtigsten IR-Werte an die Radarzelle.

Es wird keine neue Kartenebene eingeführt. Die bestehende CB-/IR-Vorläuferdarstellung bleibt für nicht gematchte IR-Zellen erhalten.

Noch nicht Bestandteil von 1L.2:

- vollständige Split-/Merge-Auflösung mit Parent-/Child-Lineage,
- finale Karten-/API-Deduplizierung ausschließlich über `cell_id`,
- ML-Lead-Time-Labels für spätere Trainingsdaten.

## 1L.4 ML-Lead-Time-Labels

1L.4 erzeugt aus der vorhandenen Zell-Lineage offline Trainingslabels für die spätere ML-Nutzung. Damit bleibt die sichtbare Kartenlogik unverändert: Es gibt keinen neuen Kartenlayer, keine neuen Fremdrequests und kein neues Modell in diesem Schritt.

### Positive Labels

Ein positives Label entsteht, wenn ein CB-IR-Vorläufer später per IR↔Radar-Match als Radar-/Regen-/Gewitterzelle bestätigt wird. Das Label enthält unter anderem:

- `became_radar_cell=1`
- `ended_without_radar=0`
- `cell_id`, `ir_track_id`, `radar_track_id`
- `ir_first_seen`, `radar_first_confirmed`
- `lead_time_min` als Minuten zwischen IR-Erstsichtung und Radarbestätigung
- vorhandene IR-, Wachstums-, MetPot- und Radar-Featurefelder, soweit im Track/State vorhanden

### Negative Labels

Ein negatives Label entsteht, wenn ein IR-Vorläufer alt genug ist, nicht mehr frisch gesehen wurde und ohne Radarbestätigung endet. Das Label enthält unter anderem:

- `became_radar_cell=0`
- `ended_without_radar=1`
- `negative_reason="expired_without_radar"`
- `lead_time_min=null`

Die Sicherheitswartezeit verhindert, dass kurz verschwundene Zellen vorschnell negativ gelabelt werden.

### Datei und spätere Nutzung

Die Labels werden append-only als JSONL geschrieben:

```text
train_data/cell_lineage/ir_lead_time_labels.jsonl
```

Die Datei dient später als Grundlage für Modelle, die zum Beispiel die Wahrscheinlichkeit einer Radarbestätigung nach 10/20/30 Minuten, hoher Wolkentops über 8/10/12 km oder nachfolgendem Starkregen/Blitz abschätzen. 1L.4 trainiert noch kein neues ML-Modell und mischt die Labels nicht automatisch in bestehende LSTM-Datasets.

## B213 Split-/Merge-Lineage

B213 dokumentiert Split- und Merge-Vorgänge zusätzlich auf fachlicher `cell_id`-Ebene, weil die bestehende Radar-Tracking-Lineage technische Track-IDs (`lineage`, `parents`, `children`, `lineage_end`) verwendet. Diese technischen IDs bleiben unverändert erhalten; B213 verknüpft sie nur mit den stabilen fachlichen Zell-IDs, damit Lebensdauer, physikalische Zellanzahl, Lead-Time-Labels und Forecast-Verification später sauber auswertbar sind.

Das Radar-Tracking erzeugt weiterhin die eigentliche Bewegungs- und Objekt-Lineage. B213 ersetzt diese Logik nicht, sondern liest die bereits vorhandenen Felder aus und schreibt ergänzende Beziehungen nach `train_data/cell_lineage/cell_lineage_state.json` sowie Events nach `train_data/cell_lineage/cell_lineage_events.jsonl`.

### Merge

Bei einem Merge behält das zusammengeführte Radarobjekt eine primäre `cell_id`. Wenn bereits eine `cell_id` am Objekt vorhanden ist, wird sie nicht überschrieben. Andernfalls wird die primäre Parent-Zelle nach `core_ratio`, dann Fläche und schließlich Eingabereihenfolge ausgewählt. Weitere Parent-Zellen werden als `alias_cell_ids` und in `merged_from_cell_ids` dokumentiert; die gemergten Parent-Zellen erhalten `merged_into_cell_id`.

### Split

Bei einem Split darf der stärkste Child die Parent-`cell_id` behalten. Die Auswahl erfolgt über `core_ratio`, danach Fläche, danach Parent-Abstand und Eingabereihenfolge. Weitere Child-Zellen bekommen eigene neue `cell_id`s und verweisen über `parent_cell_id` bzw. `split_from_cell_id` auf die Ursprungzelle. Die Parent-Zelle dokumentiert ihre Children in `child_cell_ids` und `split_into_cell_ids`.

B213 erzeugt keine neue Kartenebene und keine sichtbare neue Objektklasse. API und KMZ reichen die vorhandenen Split-/Merge-Felder lediglich weiter. Ebenso wird keine neue ML-Logik eingeführt; die Daten werden nur so persistiert, dass spätere Statistik-, Label- und Verification-Schritte sie nutzen können.
