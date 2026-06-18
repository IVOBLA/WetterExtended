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

Noch nicht Bestandteil von 1L.2:

- vollständige Split-/Merge-Auflösung mit Parent-/Child-Lineage,
- finale Karten-/API-Deduplizierung ausschließlich über `cell_id`,
- ML-Lead-Time-Labels für spätere Trainingsdaten.
