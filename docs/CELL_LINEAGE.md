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
