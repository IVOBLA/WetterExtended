# ML Factory Reset

WetterExtended unterstützt drei ML-Betriebsaktionen im bestehenden Trainings-/Admin-Panel.

## Retrain vs. Reset vs. Factory Reset

- **Modelle neu trainieren** startet die bestehende Trainingspipeline und verwendet den vorhandenen kumulativen Datensatz.
- **ML zurücksetzen** erstellt zuerst ein vollständiges Backup von `train_data`, entfernt danach Modelle, Scaler, Trainings-Metadaten und generierte Datasets. Rohdaten wie `objects` und `weather` bleiben erhalten und können erneut zum Dataset-Aufbau verwendet werden.
- **ML zurücksetzen & nur neue Daten sammeln** erstellt ebenfalls zuerst ein vollständiges Backup, entfernt Modelle und Datasets und archiviert zusätzlich die Trainingsquellen, die `dataset_builder.py` einliest (`objects`, `weather`). Danach können neue Modelle ausschließlich aus Daten entstehen, die nach dem Reset gesammelt wurden.

## Backup

Vor jedem Reset wird automatisch `train_data` als ZIP unter `train_data/backups/YYYYMMDD_HHMMSS_train_data.zip` gesichert. Das Archiv enthält ein `manifest.json` sowie alle vorhandenen Hauptbereiche wie `models`, `dataset`, `objects`, `weather`, `hydro`, `statistics` und weitere Unterordner/Dateien.

Die Anwendung validiert vor dem Löschen:

1. ZIP-Datei existiert.
2. ZIP-Datei ist größer als 0 Byte.
3. ZIP-Datei ist lesbar.
4. `manifest.json` ist enthalten.
5. Erwartete vorhandene Hauptverzeichnisse sind enthalten.

Schlägt diese Prüfung fehl, wird nicht gelöscht.

## Wiederherstellung

Zur Wiederherstellung das gewünschte ZIP aus dem Admin-Panel herunterladen, Services stoppen, den Inhalt in das Projektverzeichnis entpacken und Services neu starten. Das ZIP enthält Pfade unterhalb von `train_data/` und ist als vollständiger Trainingszustand gedacht.

## Download und Backupverwaltung

Im Admin-Panel zeigt der Abschnitt **ML Training** die aktuelle ML-Lage und die Tabelle **ML Backups** mit Datum, Größe, Reset-Typ, Download und Löschen. Nach erfolgreichem Backup erscheint ein direkter Download-Link.

## Sicherheitsmechanismen

- Reset läuft nur nach erfolgreichem Backup.
- Löschoperationen sind auf `train_data` bzw. freigegebene Unterpfade beschränkt.
- Symlinks werden nicht verfolgt, sondern nur als Link entfernt.
- Nicht gelöscht werden insbesondere `.env`, `runtime_overrides.json`, Hydro-Konfigurationen, Hydro-Overrides, Catchments, Topologie, statische Hydro-Dateien, Benutzer-/Konfigurationsdaten und Logs außerhalb des ML-Bereichs.
- Nach Factory Reset existiert kein aktives Modell. Die Prediction fällt automatisch auf den bestehenden kinematischen Fallback zurück.

## API

- `GET /api/admin/ml/status`
- `POST /api/admin/ml/backup`
- `GET /api/admin/ml/backups`
- `GET /api/admin/ml/backups/{id}/download`
- `DELETE /api/admin/ml/backups/{id}`
- `POST /api/admin/ml/reset` mit `{ "mode": "models_only" }` oder `{ "mode": "full_new_data_only" }`
