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

## Training

`dataset_builder.py` filtert Quellen vor Aufnahme in das Dataset. Standard ist `compatible_only`. Legacy-Samples können nur explizit per Admin-Policy `allow_legacy` erlaubt werden. Mismatch-Samples werden abgelehnt.

`training_meta.json` enthält den verwendeten `feature_schema_hash` und die komplette Schema-Beschreibung. Beim Laden und bei der Promotion prüft `model_training.py`, ob das Modell zum aktuellen Runtime-Schema passt. Bei Mismatch wird kein Modell geladen; die Vorhersage fällt auf den kinematischen Fallback zurück.

## Admin-Bedienung und API

- `GET /api/admin/ml/schema` zeigt aktuelles Schema, aktives Modell-Schema und Scan-Zahlen.
- `POST /api/admin/ml/dataset-scan` scannt Quellen ohne Modelltraining.
- `POST /api/admin/ml/retrain` startet Training mit `schema_policy: "compatible_only"` oder `"allow_legacy"`.

Im Admin-Panel werden kompatible, Legacy- und Mismatch-Quellen, Ablehnungsgründe, Modell-Schema-Hash und Kompatibilitätsstatus angezeigt.

## Factory Reset

Vor einem Reset wird weiterhin `train_data` als ZIP gesichert. Beim Modus „nur neue Daten“ werden alte `objects`/`weather` Quellen archiviert. Neue Samples erhalten den aktuellen Hash; Training nach Reset verwendet dadurch nur neue kompatible Daten. Alte Daten bleiben im Backup/Archiv erhalten.
