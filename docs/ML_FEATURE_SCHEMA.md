# ML Feature-Schema-Kompatibilität

WetterExtended sammelt Trainingsdaten über längere Zeit. Wenn sich Feature-Namen, Feature-Anzahl, Horizonte, Target-Encoding oder Berechnungslogik ändern, dürfen alte Samples nicht stillschweigend mit neuen Samples gemischt werden. Ein solches Mischen erzeugt falsch ausgerichtete Matrizen und verschlechtert die Modellqualität.

## Schema-Hash

`feature_schema.py` erzeugt zur Laufzeit ein kanonisches Schema und daraus einen stabilen `sha256:`-Hash. In den Hash gehen ein:

- `DATASET_SCHEMA_VERSION`
- `ML_CELL_FEATURES`
- `ML_STATION_FEATURES`
- Zeitfeatures (`hour_sin`, `hour_cos`, `month_sin`, `month_cos`)
- `ML_FORECAST_HORIZONS_MIN`
- `ML_TARGET_ENCODING`
- `ML_SEQUENCE_LENGTH`
- `ML_NUM_FEATURES`
- Feature-Flags für Klimatologie, IR, Hydro, Nowcast und DEM/Orographie

## Sample-Klassen

- **kompatibel**: Der gespeicherte `feature_schema_hash` entspricht dem aktuellen Runtime-Hash.
- **legacy**: Die Quelle besitzt keinen Schema-Hash. Diese Samples werden standardmäßig abgelehnt.
- **mismatch**: Ein Schema-Hash ist vorhanden, passt aber nicht zur aktuellen Runtime.

## Trainingsdaten-Metadaten

Neu erzeugte Object-/Weather-Quellen erhalten beim Speichern die aktuellen Schema-Metadaten: `feature_schema_hash`, `schema_version`, `feature_schema_version`, `feature_names`, `feature_count`, `horizons_min`, `target_encoding`, `created_at` sowie – wenn bekannt – `source_object_file` und `source_weather_file`. Leere No-Cell-Frames werden ebenfalls mit dem aktuellen Schema markiert.

## Training

`dataset_builder.py` filtert Quellen vor Aufnahme in das Dataset. Standard ist verpflichtend `compatible_only`: Scheduler, Hintergrundtraining, `retrain_all()`, Installations-Kompatibilitätsprüfung und manueller Admin-Start verwenden keine Legacy- oder Mismatch-Daten. Legacy-Samples können ausschließlich über den Expertenmodus `allow_legacy` im Admin-Retrain zusätzlich zugelassen werden; `ML_ALLOW_LEGACY_SAMPLES` ist standardmäßig `false`. Mismatch-Samples werden weiterhin abgelehnt.

`training_meta.json` enthält den verwendeten `feature_schema_hash`, `feature_schema_version` und die komplette Schema-Beschreibung. Beim Laden und bei der Promotion prüft `model_training.py`, ob das Modell zum aktuellen Runtime-Schema passt. Fehlt der Hash oder weicht er ab, wird kein Modell geladen; die Vorhersage fällt auf den kinematischen Fallback zurück.

## Admin-Bedienung und API

- `GET /api/admin/ml/schema` zeigt aktuelles Schema, aktives Modell-Schema und Scan-Zahlen.
- `POST /api/admin/ml/dataset-scan` scannt Quellen ohne Modelltraining.
- `POST /api/admin/ml/retrain` startet Training mit `schema_policy: "compatible_only"` oder `"allow_legacy"`.

Im Admin-Panel werden kompatible, Legacy- und Mismatch-Quellen, Ablehnungsgründe, Modell-Schema-Hash und Kompatibilitätsstatus angezeigt.

## Factory Reset

Vor einem Reset wird weiterhin `train_data` als ZIP gesichert. Beim Modus „nur neue Daten“ werden alte `objects`/`weather` Quellen archiviert. Neue Samples erhalten den aktuellen Hash; Training nach Reset verwendet dadurch nur neue kompatible Daten. Alte Daten bleiben im Backup/Archiv erhalten.

## HYDRO_FLOOD_ML_FEATURES

`HYDRO_FLOOD_ML_FEATURES` ist eine eigene Featuregruppe in `config.py` und wird nicht mit `ML_CELL_FEATURES` vermischt. Sie enthält Abfluss-, Stationsgrenzwert-, Einzugsgebiets- und Niederschlagsfeatures für das eigenständige Hydro-Flood-Risk-Modell. `w_cm` ist weder Feature noch Target noch Prognose.

Primäres Target ist `target_flood_expected`. Diagnose-Targets sind `target_q_delta_m3s`, `target_q_threshold_exceeded` und `target_q_distance_to_threshold_after_reaction_m3s`. Trainingsdaten liegen unter `train_data/hydro/ml/`, Modelle unter `train_data/models/hydro_flood/`.
