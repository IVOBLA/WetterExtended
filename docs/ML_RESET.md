# ML-Reset: Cold-Start für neue Daten

Der Admin-Modus **„ML zurücksetzen & nur neue Daten sammeln“** (`full_new_data_only`) ist ein sicherer Cold-Start für ML-Modelle und dynamische Datenhistorie.

## Begriffe

- **Backup**: Vor jedem Reset wird `train_data/` vollständig als ZIP nach `backups/YYYYMMDD_HHMMSS_train_data.zip` gesichert und validiert. Root-Backups werden nie automatisch gelöscht.
- **Konfiguration**: `.env`, `runtime_overrides.json` und `train_data/runtime_overrides.json` bleiben erhalten.
- **Statistik**: Langzeitstatistiken unter `train_data/statistics/` bleiben erhalten.
- **Statische Referenzdaten**: Daten, die teuer oder unnötig neu von Fremdsystemen geladen würden, bleiben erhalten, z. B. `train_data/dem/`, `train_data/cell_filters/` und `train_data/hydro/static/`.
- **Dynamische ML-Historie**: alte Trainingsdaten, Rohdaten-Caches, Nowcast-/Forecast-Zwischenstände, Evaluationsdaten und ML-Artefakte werden nach validiertem Backup entfernt.

## Was `full_new_data_only` löscht

Der Modus löscht insbesondere:

- `train_data/models/`
- `train_data/dataset/`
- `train_data/objects/`
- `train_data/weather/`
- `train_data/arome/`
- `train_data/cape/`
- `train_data/cloud/`
- `train_data/evaluation/`
- `train_data/external_responses/`
- `train_data/archived_training_sources/`
- eindeutig dynamische Hydro-Unterordner wie Messreihen, Impact- oder Verification-Historien

`models`, `dataset`, `objects` und `weather` werden danach als leere Arbeitsordner wieder angelegt.

## Was erhalten bleibt

Automatisch geschützt sind:

- `backups/` im Projekt-Root
- `.env`
- `runtime_overrides.json`
- `train_data/runtime_overrides.json`
- `train_data/statistics/`
- `train_data/cell_filters/`
- `train_data/dem/`
- `train_data/hydro/static/`
- fachlich statische Hydro-Indizes, Stations-, Netz-, Catchment-, Terrain- oder Geografie-Referenzen

Hydro wird nicht pauschal gelöscht. Unterordner werden einzeln als statische Referenz, dynamische Historie oder manuell zu prüfender Bereich klassifiziert.

## Vorab-Plan und manuelle Prüfung

Vor dem Start liefert `GET /api/admin/ml/reset/preview?mode=full_new_data_only`
einen verbindlichen Reset-Plan. Der Plan scannt alle direkten Kinder von
`train_data/` und zeigt pro Bereich Aktion, Begründung, Dateien, Ordner, Größe
und Beispieldateien.

Unbekannte Bereiche werden als `manual_review_required` markiert. Der Admin-Start
blockiert dann, damit kein fachlich unklarer Ordner blind gelöscht wird.

## Abschlussverifikation und Restdaten

Der beim Start gespeicherte `execution_plan` ist die Quelle der Wahrheit für den
Hintergrundjob. Nach Backup und Löschung prüft `verify_reset_result`, ob alle
geplanten Löschbereiche leer oder entfernt sind und ob geschützte Bereiche noch
existieren.

- `finished`: Alle geplanten dynamischen Bereiche sind leer oder entfernt.
- `completed_with_leftovers` / `failed_verification`: Mindestens ein geplanter
  Löschbereich enthält noch Dateien oder Ordner. Die Statusdatei und das UI
  listen Pfad, Datei-/Ordneranzahl, Größe und Beispiel-Restdateien.

Die Statusdatei `train_data/ml_reset_status.json` enthält dafür `execution_plan`,
`backup`, `delete_result` und `verification`.

## Warum danach kinematischer Fallback aktiv ist

Nach dem Cold-Start sind ML-Modellartefakte und alte Datasets entfernt. Bis neue Trainingsdaten gesammelt und ein neues Modell trainiert wurde, läuft die Vorhersage ohne ML-Modell sauber im kinematischen Fallback weiter.

## Wiederherstellung aus Root-Backup

1. Passendes ZIP in `backups/` auswählen.
2. Dienst stoppen, damit während der Wiederherstellung keine neuen Dateien geschrieben werden.
3. Inhalt des ZIPs in eine temporäre Stelle entpacken.
4. Den enthaltenen Ordner `train_data/` gezielt zurückkopieren oder einzelne benötigte Unterordner/Dateien wiederherstellen.
5. Dienst starten und Admin-Status prüfen.

Root-Backups sind bewusst außerhalb von `train_data/` abgelegt und werden vom Reset nicht gelöscht.
