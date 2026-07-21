# AIChecks — Arbeitsanweisungen für die KI

Diese Datei enthält **ausschließlich Arbeitsanweisungen**: was bei einem vorliegenden
Debug-Export oder Livezugriff zu tun ist. Keine Befunde, keine Herleitungen, keine Messwerte —
die stehen in `docs/HAILO_INTEGRATION.md` beim jeweiligen B-/P-Eintrag.

**Regeln:**
- Jeder Prompt trägt hier ein, was danach zu prüfen oder zu tun ist.
- Formuliere im Imperativ und ausführbar: was, worin, mit welchem Ergebnis.
- Erledigte Anweisungen unter „Erledigt" verschieben, mit Datum und Ergebnis in einer Zeile.
- Keine Anweisung ohne konkrete Datenquelle.

---

## Offen

### AC-048 — Prüfe Budgetgruppen gegen die Servicenamen
Werte im 24h-Export `train_data/evaluation/api_budget.json` unter `counts` aus. Jede
Gruppe muss einen Eintrag in `config.API_DAILY_BUDGET` haben oder bewusst unbegrenzt
sein. Erscheinen mehrere Gruppen desselben Providers (z. B. `openmeteo` neben
`open-meteo-*`), greift die Normalisierung in `group_for()` nicht — melden. Eine
Gruppe ohne Limit ist ungedeckelt.

### AC-049 — Prüfe die Summe der Provider-Requests gegen das Limit
Summiere im 24h-Export `train_data/evaluation/api_budget.json` unter `counts` alle
Gruppen eines Providers und vergleiche mit `config.API_DAILY_BUDGET`. Nähert sich die
Summe dem Limit (> 70 %), ist die Abrufkadenz zu melden — nicht das Limit anzuheben.
Das Projektziel ist, unnötige Fremdrequests zu vermeiden.

### AC-046 — Prüfe Drift-Meldungen gegen die Horizont-Tabelle
Vergleiche im 24h-Export `train_data/evaluation/drift_status.json`
(`drift_detected`, `delta_by_horizon`) mit
`train_data/evaluation/accuracy_history.jsonl` (`mae_km` je Horizont, recent gegen
baseline). Meldet der Trigger Drift, obwohl jeder einzelne Horizont gleich gut oder
besser ist, poolt er wieder über Horizonte — melden. Ein gepoolter Mittelwert über
Horizonte mit unterschiedlichem Wertebereich ist keine Qualitätsaussage.

### AC-047 — Prüfe übersprungene Horizonte
Werte im 24h-Export `train_data/evaluation/drift_status.json` das Feld
`skipped_horizons_not_in_both_windows` aus. Werden dauerhaft dieselben Horizonte
übersprungen, fehlt einem Fenster systematisch Datenmaterial — Ursache in der
Fensterlänge oder der Zell-Lebensdauer suchen und melden.

### AC-044 — Prüfe Drift-Mails gegen den Ausliefermodus
Vergleiche im 24h-Export jede `[DRIFT-MAIL]`-Zeile im Service-Log mit
`delivered_mode_counts` aus `train_data/evaluation/accuracy_history.jsonl` zum selben
Zeitpunkt. Wurde bei 100 % `kinematic_fallback` eine Mail versendet, greift das Gate
nicht — melden. Prüfe zusätzlich, ob `train_data/evaluation/drift_status.json` bei
unterdrückten Alarmen `alert_suppression_reason` trägt.

### AC-045 — Prüfe verworfene Trainingsversionen im Modellverzeichnis
Suche im Service-Log nach `[TRAINING] REJECTED` und vergleiche mit dem Inhalt von
`train_data/models/`. Ein `v_*`-Verzeichnis einer verworfenen Version darf keinen
Alarm, keine Promotion und keinen Fallback-Guard aushebeln. Häufen sich verworfene
Verzeichnisse, ist zusätzlich die Retention zu melden.

### AC-001 — Prüfe, ob die Assoziations-Diagnose geschrieben wird
Werte `diagnostics/diagnosis_presence.json` aus dem Export aus.
- `status="ok"` → AC-002 durchführen.
- `status="empty"` oder `"missing"` → prüfe auf dem Pi, ob `train_data/association` existiert und
  befüllt wird (`object_tracking.py`, `_persist_association_diagnosis`); melde das Ergebnis als
  neuen Befund.

### AC-002 — Kalibriere `ASSOC_MAX_COST`
Sobald `diagnostics/train_data/association/*.json` im Export vorliegt:
- Bilde die Verteilung von `cost` über alle akzeptierten Matches (Median, p75, p90, p99).
- Zähle Ablehnungen mit `reason="cost_above_max"` und `reason="no_acceptable_track"`.
- Setze `ASSOC_MAX_COST` so, dass p99 der korrekten Matches darunter liegt.
- Prüfe gegen `forecast_error_details.jsonl`, ob die Ablehnungen mit höherem Prognosefehler
  korrelieren. Wenn nein: Schwelle ist zu streng.

### AC-003 — Kalibriere die Transition-Schwellen gegen den neuen Code
Sobald `cell_lineage_events.jsonl` Einträge aus einer Konvektionslage enthält:
- Rechne `explained_ratio` und `parent coverage` je bestätigtem Merge neu.
- Setze `TRANSITION_MERGE_MIN_EXPLAINED` und `TRANSITION_MERGE_MIN_PARENT_COVERAGE` anhand der
  Perzentile (p10 der echten Merges muss über der Schwelle liegen).
- Verwende **nur** Daten ab B374 — ältere Parentmengen stammen aus dem greedy Matching.

### AC-004 — Messe die Quellen-Rangfolge über mehrere Lagen
Werte `forecast_error_details.jsonl` je `kinematic_source` (optflow / ewma / kalman) und
`horizon_min` (10/30/60) aus, Median in km.
- Sammle **mindestens drei** Konvektionslagen, bevor die Priorität in `prediction.py` (P-M02,
  `of_available == 1`) geändert wird.
- Ändere die Priorität **nicht** auf Basis einer einzelnen Lage.

### AC-005 — Prüfe die Split-Menge gegen die Sattel-Schwelle
Zähle im Service-Log `[P66] Multi-Core-Split: N Kerne -> M Sub-Zellen`.
- Vergleiche M mit der Zahl visuell getrennter Kerne auf den Radar-Overlays.
- Bei unplausibel vielen Sub-Zellen: erhöhe `MULTI_CORE_MIN_SADDLE_RATIO`, **nicht** den
  Komponentengraphen aus B403 ändern.

### AC-006 — Prüfe, ob Splits im Livebetrieb auftreten
Zähle in `objects/train_data/objects/*.json` die Objekte mit `lineage="split"`.
- Erwartung: > 0 bei Lagen, in denen die P66-Logs Sub-Zellen melden.
- Bleibt es 0: prüfe zuerst die Segmentierung (AC-005), dann
  `TRANSITION_SPLIT_MIN_EXPLAINED` / `TRANSITION_SPLIT_MIN_CHILD_SHARE`.

### AC-007 — Prüfe die Eindeutigkeit der Lineage-Ereignisse
Werte `cell_lineage_events.jsonl` aus.
- Je `event_signature` darf **genau ein** Eintrag existieren.
- `lineage="merged"` muss überhaupt auftreten.
- `cell_lineage_write_status.json`: `last_result` muss `"ok"` sein.

### AC-008 — Suche weitere Stellen mit manueller `_UF`-Multiplikation
Führe `grep -n "\* _UF" prediction.py` aus.
- Jede Stelle, die eine ML-Rohausgabe verarbeitet und **nicht** über `_decode_ml_position()`
  läuft, ignoriert `target_encoding` und ist zu melden.

### AC-009 — Nimm `training_meta.json` in den Debug-Export auf
Die Datei liegt unter `models/v_*/training_meta.json` und fehlt im Export.
- Prüfe, ob die Feature-Liste zum Trainingszeitpunkt für Schema-Fragen benötigt wird.
- Falls ja: als eigenen Prompt umsetzen (Exportliste in `debug_export.py`).

### AC-010 — Prüfe jeden Export auf Fremdarchive
Führe `unzip -l <export>.zip | grep '\.zip$'` aus.
- Treffer unter `latest_export/` → Rekursion (B406/B407 nicht wirksam), melden.
- Treffer außerhalb → prüfen, ob es legitime Nutzdaten sind.

### AC-011 — Prüfe nach jedem Prompt, ob der Changelog-Eintrag existiert
Vor jedem Abschlussbericht ausführen:
  grep -c "^### B" docs/HAILO_INTEGRATION.md
Die höchste dort eingetragene B-Nummer muss der höchsten Nummer unter tests/test_b*_
entsprechen. Weicht sie ab, ist der Bericht unvollständig — Eintrag nachziehen, bevor
der Prompt als erledigt gilt.

### AC-012 — Prüfe Tests auf stille AttributeErrors
Nach jedem Prompt mit neuen Tests ausführen:
  grep -rn '__import__(' tests/
Treffer auf einem Modulobjekt (z. B. h.__import__("x")) sind immer defekt und lassen
den Test scheitern, bevor eine Assertion läuft. Ein solcher Test belegt nichts.
Regulär importieren und das Modul direkt patchen.

### AC-013 — Prüfe im Export, ob Warnungen ohne Zellframe entstehen
Werte im 24h-Export je Station aus:
  flood_status, current_q_above_threshold, forecast_evaluation_stale, cell_frame_status
Erwartung: bei cell_frame_status != "ok" und current_q_above_threshold=true muss
flood_expected=true sein. Jede Zeile mit current_q_above_threshold=true und
flood_expected=false ist ein Regressionsbefund.

### AC-014 — Prüfe, ob stale Forecasts Warnungen fortschreiben
Suche im Export Zeilen mit forecast_evaluation_stale=true und flood_expected=true
bei current_q_above_threshold=false. Erwartung: keine. Jeder Treffer ist eine
fortgeschriebene Altwarnung.

### AC-015 — Prüfe Testfixtures auf geometrische Konsistenz
Ein Test, der load_station_catchment_index mit einem Polygon patcht und
catchment_diagnostics mit einer davon abweichenden Fläche, erzeugt Zahlen ohne
physikalische Bedeutung. Ausführen:
  grep -rn "catchment_area_geometry_km2" tests/
Vergleiche je Treffer den Wert mit der Fläche der gepatchten Geometrie. Jede Abweichung um mehr
als Faktor 2 ist zu melden; Konstantenassertions auf abgeleitete Niederschlagswerte in
solchen Tests prüfen nichts.

### AC-016 — Prüfe Sandbox-Fehler gegen den Pi
pytest in der Codex-Sandbox liefert andere Zahlen als der Pi, weil Abhängigkeiten und
Python-Version abweichen. Fehlende Module erzeugen Collection-Errors, und pytest bricht
dann die gesamte Sammlung ab — dreistellige Fehlerzahlen sind dann ein Artefakt.
Maßgeblich ist install_pytest.log vom Pi. Sandbox-Fehler, die auf dem Pi grün sind,
sind nicht zu reparieren.

### AC-017 — Prüfe, ob Zellen im Einzugsgebiet gezählt werden
Werte im 24h-Export je Station input_cell_count und contributing_cell_count aus.
Erwartung: bei Zellen im Land ist contributing_cell_count für mindestens eine Station
> 0. Ist er über einen ganzen Gewittertag durchgehend 0 bei input_cell_count > 0, wird
die Zell-Catchment-Zuordnung nicht ausgewertet — sofort melden.


### AC-018 — Prüfe Modellintegritätsfehler im Export
Suche im 24h-Export nach model_rejection_reason. Erwartung: leer oder
"model_not_promoted". Jedes Auftreten von model_integrity_error ist zu melden, mit
der genauen Kennung (model_hash_mismatch, metadata_hash_mismatch,
manifest_field_mismatch, schema_hash_mismatch, non_finite_probe_inference) und dem
Zeitpunkt des letzten Trainings aus hydro_flood_training_meta.json.

### AC-019 — Prüfe Modell-Cache-Trefferquote
Werte model_cache_status je Stationszeile im Export aus. Erwartung: genau ein "miss"
je Auswertungslauf, alle weiteren Stationen "hit". Mehrere "miss" pro Lauf bedeuten,
dass der Stat-Key instabil ist — Ursache melden, nicht den Cache vergrößern.


### AC-020 — Prüfe Zellbezug in neuen Samples
Werte im 24h-Export hydro_flood_samples aus. Zähle Zeilen mit precip_event_active=true
und leerer contributing_lineage_ids-Liste. Erwartung: null. Jeden Treffer als Verlust
des Zellbezugs im Produktivpfad melden; die Liste nicht im Test füllen.

### AC-021 — Prüfe Eventverteilung vor jedem Training
Vor jeder ML-Reaktivierung für das Log ausführen:
  python -c "import hydro_flood_ml as h; r=h.analyze_training_dataset(h.load_trainable_labeled_samples(False)); print(r['event_count'], r['train_time_range'], r['validation_time_range'])"
Erwartung: event_count >= HYDRO_ML_MIN_TRAIN_EVENTS + HYDRO_ML_MIN_VALIDATION_EVENTS,
und train_time_range endet vor validation_time_range. Überlappende Bereiche verwerfen.

### AC-022 — Prüfe Ausschlussgründe im Datensatz
Werte im Export sample_failures nach Grund gruppiert aus. Häuft sich ein Grund über 5 % der
Gesamtsamples, die Ursache im Produktivpfad suchen und als Befund melden; die
Validierung nicht lockern.

### AC-023 — Prüfe Speicherverbrauch der Readiness
Werte im 24h-Export die Laufzeit von /api/hydro/flood-risk/status aus. Liegt sie über
2 s, ist der Readiness-Cache unwirksam. Ursache melden — nicht das Polling-Intervall erhöhen.

### AC-024 — Prüfe Q-History-Wachstum
Werte im Export q_history-Zeilen und Datenbankgröße aus. Wachstum über
HYDRO_Q_HISTORY_RETENTION_DAYS bedeutet, dass der Maintenance-Job zu prüfen ist.

### AC-025 — Prüfe Sampling-Rate
Zähle im Export Samples je Station und Tag, getrennt nach precip_event_active. No-cell-Samples
müssen unter HYDRO_ML_MAX_NO_CELL_SAMPLES_PER_DAY bleiben.

### AC-026 — Prüfe, ob Extremereignisse erhalten bleiben
Samples im Export mit current_q_above_threshold=true dürfen durch Subsampling nie entfernt
werden. Einen Rückgang nach Maintenance sofort melden.

### AC-027 — Prüfe Targetverteilung
Werte im 24h-Export target_q_delta_m3s aus. Erwartung: keine negativen Werte, und der Anteil exakt-null-Targets ist plausibel (fallende und gleichbleibende Verläufe). Liegt der Nullanteil über 90 %, sammelt das System fast nur Ruhelagen — als Befund für die Sampling-Parameter aus B416 melden.

### AC-028 — Prüfe Nutzung gesicherter Niederschläge
Zähle im Export Zeilen mit observed_precip_available=true, getrennt nach observed_precip_used_in_forecast. Werte die Gründe unter observed_precip_rejection_reason gruppiert aus. Häuft sich ein Grund, ist entweder die Qualitätsschwelle falsch oder die Quelle liefert anders als spezifiziert — beides melden, nicht die Schwelle senken.

### AC-029 — Prüfe Niederschlags-Volumenbilanz
Werte im Export bei gleichzeitig vorhandener Messung und Zellprognose precip_window_overlap_min und precip_window_gap_min aus. Erwartung: overlap = 0. Jeder Wert > 0 bedeutet ein zeitlich überlappendes Intervall; die Messung muss abgelehnt werden, damit keine überhöhte Q-Prognose entsteht — sofort melden.


### AC-030 — Prüfe den öffentlichen Payload auf interne Felder
Werte im 24h-Export den gespeicherten hydro_flood_risk-Cache aus. Erwartung:
payload_scope="public", und keines der Felder cell_diagnostics,
station_runoff_series, model_signature, model_source, ml_predicted_q_delta_m3s,
flood_probability, hydro_flood_risk_score ist enthalten. Jeder Treffer ist ein Leck —
die aufrufende Stelle melden, nicht das Feld im Frontend ignorieren.

### AC-031 — Prüfe die Konsistenz des SQLite-Snapshots
Öffne hydro_flood_samples_snapshot.sqlite3 aus dem Export und führe aus:
  PRAGMA integrity_check;
Erwartung: "ok". Prüfe zusätzlich, dass weder hydro_flood_samples.sqlite3 noch eine
-wal/-shm-Datei im Export liegt. Ein Treffer bedeutet, dass die unkoordinierte Kopie
zurück ist.

### AC-032 — Prüfe den bbox_fallback-Zweig
heuristic_score() testet auf geometry_quality == "bbox_fallback". Prüfe im Export,
ob geometry_quality je einen anderen Wert annimmt. Ist der Zweig über 30 Tage nie
erreicht worden, als toten Code zur Entfernung in einem eigenen Prompt vormerken —
nicht nebenbei löschen.

### AC-033 — Prüfe, ob Deferred-Zustände die Erholung überleben
Suche im 24h-Export Zeitpunkte, an denen cell_frame_status von "missing"/"stale" auf
"ok" wechselt. Prüfe den unmittelbar folgenden hydro_flood_risk-Payload: deferred_reason
muss verschwunden und forecast_evaluation_stale false sein. Bleibt der Deferred-Zustand
über den Wechsel hinweg bestehen, greift die Cache-Invalidierung nicht — melden.

### AC-034 — Prüfe Migrationszeitpunkt nach Upgrade
Vergleiche im Export den Zeitstempel des Prozessstarts (systemd) mit applied_at in
schema_migrations. Liegt applied_at systematisch bei 03:35 statt beim Start, läuft die
Migration nur im Cronjob — melden. Zwischen Upgrade und Migration entstehen keine
Labels.

### AC-035 — Prüfe Trainingsstatus über Prozessgrenzen
Rufe laut Pi-Log /api/admin/hydro/flood-risk/retrain/status während eines laufenden Trainings
mehrfach ab. Zeigen manche Antworten "idle", ist der Status prozesslokal und die
409-Zusage nicht eingehalten — melden.


### AC-036 — Prüfe, ob event_id im Produktivpfad gesetzt wird
Werte im 24h-Export labeled_samples aus. Zähle Zeilen mit event_id IS NULL.
Erwartung: null. Jeder Treffer bedeutet, dass die inkrementelle Vergabe nicht greift
und readiness_status() wieder auf 0 Events zählt — melden, nicht die Zählung ändern.

### AC-037 — Prüfe die Eventverteilung auf Plausibilität
Gruppiere im Export labeled_samples nach event_id. Enthält ein Event mehr als 50 % aller Samples,
greift die Trennung nicht: HYDRO_EVENT_DRY_GAP_MIN und die No-cell-Gruppierung prüfen.
Eine hohe Eventzahl allein ist kein Erfolg — sie muss die Wetterlage abbilden.

### AC-038 — Prüfe Readiness gegen die Trainingssicht
Vergleiche im Log readiness_status()["event_count"] mit
analyze_training_dataset(load_trainable_labeled_samples(False))["event_count"].
Weichen sie um mehr als 10 % ab, ist die Nachführung nach dem Training ausgeblieben
oder der Readiness-Cache invalidiert nicht — melden.

### AC-039 — Prüfe Bestandstests nach jeder Vertragsänderung
Ändert ein Prompt eine Signatur, den Payload-Umfang, eine Validierungsregel oder ein
DB-Schema, führe vor dem Abschlussbericht aus:
  python -m pytest -q tests/test_*hydro*.py 2>&1 | tail -1
Eine Auswahl der neu geschriebenen Tests genügt nicht — eine Vertragsänderung betrifft
jeden Test, der den Vertrag nutzt. Neue Fehler in Altbeständen sind im Log zu melden.

### AC-040 — Prüfe auf Kommentarleichen nach Migrationen
Nach jeder Datenquellen-Migration ausführen:
  grep -rn "Datei-Tail\|jsonl\|JSONL" hydro_flood_ml.py
Ein Docstring oder Kommentar, der eine abgelöste Quelle beschreibt, ist gefährlicher
als keiner — er führt die nächste Analyse in die Irre. Treffer melden.

### AC-041 — Prüfe Testisolation im Gesamtlauf
Ein Test, der isoliert grün und im Gesamtlauf rot ist, deutet auf Kontamination
(sys.modules, eingefrorene Modulkonstanten, offene Dateihandles). Vergleiche im Log:
  python -m pytest -q tests/test_XXX.py 2>&1 | tail -1
  python -m pytest -q 2>&1 | grep "test_XXX"
Bei Abweichung den Verursacher suchen und dort reparieren, nicht im Opfer.

### AC-042 — Prüfe, ob der Richtungs-Drift-Alarm auslösen kann
Vergleiche im 24h-Export die Schlüssel in accuracy_history.jsonl
(direction_stats_by_horizon) mit den in drift_detector.py gelesenen. Ausführen:
  grep -n '_v.get(' drift_detector.py
Jeder gelesene Schlüssel muss im Export vorkommen. Liest der Detektor einen Schlüssel,
den accuracy_tracker nicht schreibt, ist der Alarm tot — melden.

### AC-043 — Prüfe Alarm gegen Kennzahl im Export
Vergleiche im Export drift_status.json (direction_drift_alarm) mit
accuracy_history.jsonl (p90_direction_error_deg, count je Horizont). Liegt p90 über
DRIFT_DIRECTION_THRESHOLD_DEG bei count >= DRIFT_DIRECTION_SPEED_MIN_POINTS, muss der
Alarm true sein. Jede Abweichung ist zu melden — ein Alarm, der nie auslöst, ist keine
Entwarnung.


### AC-050 — Prüfe den Datensatz-Export gegen SQLite
Vergleiche im 24h-Export die Zeilenzahl von hydro_flood_dataset.jsonl mit der Zahl der
trainierbaren labeled_samples aus dem SQLite-Snapshot. Weichen sie ab, ist der Export
nicht aktuell oder wurde überschrieben. Ist die JSONL leer bei gefüllter Datenbank, hat
ein zweiter Schreiber sie geleert — sofort melden. Datenquelle: 24h-Export mit
hydro_flood_dataset.jsonl und SQLite-Snapshot.

### AC-051 — Prüfe eingefrorene Pfad-Defaults
Ausführen:
  grep -nE "def .*\(.*: *Path *= *[A-Z_]+" hydro_flood_ml.py accuracy_tracker.py
Ein Default-Argument mit einer Modulkonstante wird beim Import eingefroren und folgt
keinem Laufzeit-Patch. Jeder Treffer ist zu melden — Tests, die den Pfad patchen,
schreiben sonst ins echte train_data/. Datenquelle: die Funktionssignaturen im
aktuellen Arbeitsbaum.

### AC-052 — Prüfe Testartefakte im Arbeitsbaum
Nach jedem Testlauf, der install_pytest.log erzeugt, zusätzlich ausführen:
  git status --short
  git status --short | grep -c "train_data/" || true
Erscheint eine Datei unter train_data/ — etwa hydro_flood_dataset.jsonl —, hat ein Test
an einem beim Import eingefrorenen Pfad-Default geschrieben statt in tmp_path. Melden:
solche Tests verändern den Produktivbestand und verfälschen den nächsten Debug-Export.

### AC-053 — Prüfe neue AIChecks-Blöcke gegen die B407-Regeln
Vor dem Anhängen eines Blocks ausführen:
  python -m pytest -q tests/test_b407_aichecks_arbeitsanweisungen.py
Der Titel muss mit einem Verb aus der Liste in test_aichecks_entries_are_imperative
beginnen, und der Block muss eines der Wörter .json, .jsonl, grep, Log, log, Export
oder Pi enthalten. Die Schlüsselwortliste im Test wird nie erweitert — der Block passt
sich an. Ein Block ohne diese Wörter hat keine überprüfbare Datenquelle.

### AC-054 — Prüfe das Niederschlagsgedächtnis auf Doppelzählung und Wachstum
Im Debug-Export auf dem Pi ausführen:
  sqlite3 train_data/hydro/ml/hydro_flood_samples.sqlite3 "SELECT COUNT(*), COUNT(DISTINCT frame_timestamp), MIN(frame_timestamp), MAX(frame_timestamp) FROM catchment_precip_ledger;"
  sqlite3 train_data/hydro/ml/hydro_flood_samples.sqlite3 "SELECT station_id, frame_timestamp, cell_id, COUNT(*) c FROM catchment_precip_ledger GROUP BY 1,2,3 HAVING c > 1;"
Die zweite Abfrage muss leer bleiben — jede Zeile dort ist eine Doppelzählung und
verfälscht den prognostizierten Abfluss nach oben. Liegt die Spanne zwischen MIN und
MAX über HYDRO_PRECIP_LEDGER_RETENTION_MIN (Default 180 min, siehe
runtime_overrides.json), läuft purge_precip_ledger nicht: melden, das Wachstum ist
sonst auf dem Pi unbegrenzt.

### AC-055 — Prüfe, ob das Niederschlagsgedächtnis im Forecast ankommt
Nach einem Zelldurchzug auf dem Pi ausführen:
  curl -s localhost/api/hydro/flood-risk | python3 -m json.tool | grep -E "antecedent_(status|last_hit_age_min|routed_delta_q_m3s)"
  grep -c "antecedent_status" train_data/hydro/impact/latest_hydro_flood_risk.json
Ist antecedent_status über Stunden durchgehend "no_history", obwohl der Debug-Export
Zellen im Einzugsgebiet zeigt, schreibt P74 nicht: melden. Steht antecedent_status auf
"ok" und antecedent_routed_delta_q_m3s bleibt dennoch exakt 0.0, während
antecedent_runoff_volume_m3 > 0 ist, läuft die Kaskade nicht aus der Vergangenheit an —
ebenfalls melden, der gefallene Regen bleibt dann wirkungslos.

### AC-056 — Prüfe den Trainingsbestand nach dem Schemawechsel auf p75_antecedent_v1
Im Debug-Export ausführen:
  sqlite3 train_data/hydro/ml/hydro_flood_samples.sqlite3 "SELECT feature_schema_version, COUNT(*) FROM labeled_samples GROUP BY 1;"
  curl -s localhost/api/hydro/flood-risk/status | python3 -m json.tool | grep -A3 readiness
Dass Zeilen mit b418_live_catchment_v5 nicht mehr trainierbar sind, ist die dokumentierte
Folge von P75 und kein Fehler. Wächst die Zahl der Zeilen mit p75_antecedent_v1 über
mehrere Tage mit Zellaktivität dagegen nicht, greift die Sample-Aufzeichnung nicht:
melden. Alte Zeilen niemals löschen — sie belegen die Historie.

### AC-057 — Prüfe, ob der nächtliche Export im Admin-Panel ankommt
Nach einem Lauf des Timers auf dem Pi ausführen:
  systemctl status wetterprojekt-debug-export-branch.service --no-pager | tail -5
  cat train_data/evaluation/latest_export/latest_export_meta.json
  journalctl -u wetterprojekt-debug-export-branch.service --since "-2 days" | grep -E "Für Admin-Panel persistiert|Persistenz .* fehlgeschlagen"
Fehlt latest_export_meta.json, obwohl der Service erfolgreich lief, oder ist
export_reason dort nicht "scheduled_branch_publish", während created_at_utc älter als
der letzte Timer-Lauf ist, dann persistiert der automatische Export nicht: melden — das
Panel bietet dann nur den alten manuellen Stand an. Eine Warnzeile "Persistenz für das
Admin-Panel fehlgeschlagen" im Log ist immer zu melden, auch wenn der Push gelang.

---

### AC-058 — Prüfe Hydro-Flood-Risk auf Store-Defekt und Antwortgröße

**Datenquellen im Export:**
- `api_logs/nginx/nginx_access.log`
- `api_logs/journal/wetterprojekt-admin.service.log`
- `hydro_ml/hydro_flood_samples_snapshot.sqlite3`
- `train_data/hydro/impact/` (Verzeichnisinhalt)
- `manifest.json` → `scanned_roots`

**Durchzuführen:**

1. Aus `nginx_access.log` alle `GET /api/hydro/flood-risk`-Zeilen extrahieren und die
   Antwortgrößen (vorletztes Feld) auszählen. Bei mehr als 20 Stationen ist jede
   Antwort unter 2000 Bytes eine Fehlerantwort. Bei konstant 105 Bytes prüfen, ob die
   Meldung `DatabaseError: database disk image is malformed` lautet (47 Zeichen →
   105 Bytes compact). Befund melden mit Anzahl und Zeitspanne.
2. In `wetterprojekt-admin.service.log` nach `[API-FAIL] hydro_api:` suchen, Fehlertypen
   auszählen und ersten/letzten Zeitstempel angeben. Mehr als 5 Vorkommen in 24 h ist
   ein Befund.
3. Auf `hydro_flood_samples_snapshot.sqlite3` `PRAGMA integrity_check` ausführen. Bei
   Meldungen die betroffene `rootpage` über
   `SELECT type,name,rootpage FROM sqlite_master WHERE rootpage=<n>` auflösen und die
   Tabelle benennen. Jede Abweichung von `ok` ist ein Befund.
4. Prüfen, ob `hydro_impact/latest_hydro_flood_risk.json` im Export enthalten ist.
   Fehlt sie, obwohl `manifest.json` → `scanned_roots` das Verzeichnis
   `train_data/hydro/impact` listet, wurde der Risk-Cache nie geschrieben — Befund.
5. Falls `latest_hydro_flood_risk.json` vorhanden ist: `sample_store_status` prüfen.
   Wert `degraded` ist ein Befund; `sample_store_faults[].stage` benennen.
6. `train_data/hydro/live/hydro_status.json` NICHT als Beleg für Fehlerfreiheit
   verwenden. `_mark_cache` in `hydro_fetch.py` baut die Datei bei jedem Cache-Treffer
   aus `latest_hydro.json["status"]` neu auf und löscht dabei `hydro_flood_eval_error`.
   Maßgeblich sind Journal und Antwortgröße.

### AC-068 — Prüfe Zuggeschwindigkeit und Prognose-Sektor der Zellen auf Plausibilität

**Datenquellen im Export:**
- `objects/latest_objects.json` (jüngster Frame)
- `objects/train_data/objects/*.json` (Verlauf der letzten Frames)

**Durchzuführen:**

1. Für jede Zelle im jüngsten Frame `speed_kmh` gegen den realen Frame-Abstand halten:
   aus `history[-2].timestamp` und `history[-1].timestamp` das reale Intervall
   `real_dt` in Minuten bilden (Format `%Y-%m-%d_%H-%M-%S`). Prüfmaßstab: Kärntner
   Gewitterzellen ziehen typisch mit 15–50 km/h. Jede Zelle mit `speed_kmh > 60` melden,
   zusammen mit ihrem `real_dt`.
2. Korrelation prüfen: Tritt hohe `speed_kmh` systematisch bei kleinem `real_dt`
   (unter ~3 min) auf, ist das ein Hinweis auf eine dt-Skalierung, die bei zu kurzem
   Frame-Abstand nach oben treibt (nominal sind Frames ~5 min auseinander). Diesen
   Zusammenhang je betroffener Zelle als Hypothese melden — nicht als bestätigten Fehler,
   solange der Code nicht eingesehen wurde (`code_ref`/`beleg` beachten).
3. Zickzack der Prognose prüfen: aus den Prognosepunkten je Horizont einer Zelle die
   Peilung (bearing) zwischen aufeinanderfolgenden Punkten bilden und die größte
   Richtungsänderung zwischen zwei Segmenten bestimmen. Änderungen über ~45° kennzeichnen
   eine springende Prognoselinie, aus der der Unsicherheitskegel einen fehlerhaften
   Sektor zeichnet. Betroffene Zell-IDs mit der größten Richtungsänderung melden.
4. Kausalität einordnen: Tritt der Prognose-Zickzack ausschließlich bei den Zellen mit
   überhöhter `speed_kmh` auf, ist der fehlerhafte Sektor voraussichtlich Folge der
   Geschwindigkeit — dann als zusammenhängender Befund melden. Tritt er auch bei Zellen
   mit plausibler Geschwindigkeit auf, als eigenständiges Prognose-Problem melden.
5. `speed_kmh`-Werte am oberen Deckel (nahe `MAX_CELL_SPEED_KMH`) getrennt melden: Sie
   deuten auf ein Clamping hin, das die eigentliche Fehlskalierung nur kappt, statt sie
   zu verhindern.

## Erledigt

_(Format: `AC-xxx — Kurztitel · YYYY-MM-DD · Ergebnis in einem Satz.)_

### AC-059 — Prüfe WAL-Wachstum und Verbindungs-Lebenszyklus der Sample-DB

**Datenquellen:** Livezugriff auf dem Pi; `manifest.json` → `excluded_files`;
`hydro_ml/hydro_ml_snapshot_status.json`.

**Durchzuführen:**

1. Auf dem Pi die WAL-Größe im Verhältnis zur Hauptdatei bestimmen:
   `ls -la train_data/hydro/ml/hydro_flood_samples.sqlite3*`
   Ist die `-wal`-Datei größer als 10 % der Hauptdatei, ist der Checkpoint blockiert —
   Befund melden mit beiden Größen.
2. Offene Filedeskriptoren auf die DB je Dienst zählen:
   `for s in wetterprojekt wetterprojekt-scheduler wetterprojekt-admin; do
      pid=$(systemctl show -p MainPID --value $s); echo -n "$s: ";
      ls -l /proc/$pid/fd 2>/dev/null | grep -c hydro_flood_samples; done`
   Mehr als 2 gleichzeitig offene Deskriptoren je Dienst sind ein Befund.
3. Im Quelltext prüfen, dass keine neue rohe Verwendung hinzugekommen ist:
   `python3 -c "t=open('hydro_flood_ml.py').read(); print(t.count('_sample_db()') - t.count('with _sample_db() as'))"`
   Ergebnis muss exakt `1` sein (die Definitionszeile). Jeder andere Wert ist ein Befund.

### AC-060 — Prüfe die Integrität der Hydro-ML-Sample-Datenbank

**Datenquellen im Export:**
- `hydro_ml/hydro_sample_db_integrity.json`
- `hydro_ml/hydro_ml_maintenance_latest.json`
- `hydro_ml/hydro_flood_samples_snapshot.sqlite3`
- `api_logs/journal/wetterprojekt-scheduler.service.log`

1. Melde jeden `integrity_status` außer `ok` samt `affected_tables`, `message_count`
   und `checked_at`. Fehlt das Feld trotz Wartungsbericht, melde eine Version vor B432.
2. Melde `status=degraded_sample_db` aus dem Wartungsbericht.
3. Führe unabhängig `PRAGMA quick_check` auf dem Snapshot aus und löse jede `Tree <n>`-
   Nummer über `sqlite_master.rootpage` auf. Melde Abweichungen zum Zustandsbericht.
4. Suche im Scheduler-Journal nach `WARNUNG Hydro-ML Sample-DB defekt` und melde jedes
   Vorkommen mit Zeitstempel und Tabellenliste.
5. Melde aus Reparaturberichten `rows_copied`, `rows_skipped` und `quarantine_path`.
   `rows_skipped > 0` ist endgültiger Datenverlust und immer ein Befund.

### AC-061 — Werte den Zustand der Hochwasserbewertung aus

**Datenquellen im Export:**
- `train_data/hydro/live/hydro_flood_eval_status.json`
- `train_data/hydro/live/hydro_status.json`
- `api_logs/journal/wetterprojekt-admin.service.log`
- `manifest.json` → `created_at`

**Durchzuführen:**

1. `hydro_flood_eval_status.json` lesen. `hydro_flood_eval_status` mit `error` ist immer
   ein Befund: `error` und `hydro_flood_eval_at` melden. Wert `deferred` mit
   `deferred_reason` melden, wenn er über mehrere Exporte hinweg anhält.
2. `hydro_flood_eval_at` gegen `manifest.json` → `created_at` prüfen. Liegt der
   Zeitstempel mehr als 30 Minuten zurück, steht die Bewertung — Befund, unabhängig vom
   gemeldeten Status. Der Abruf läuft alle ~15 Minuten.
3. Fehlt die Datei ganz, ist die Bewertung seit dem letzten Deploy nie gelaufen —
   Befund. Ein fehlender Eintrag ist seit B433 kein Indiz für Fehlerfreiheit mehr.
4. `sample_store_status` in derselben Datei prüfen. `degraded` ist ein Befund; die
   `sample_store_faults[].stage` benennen (siehe AC-058).
5. `hydro_status.json` NICHT als Beleg für den Zustand der Bewertung verwenden. Die
   Datei beschreibt ausschließlich den Abruf. Bis B433 löschte `_mark_cache` dort jeden
   Eval-Fehler beim nächsten Cache-Treffer; die Trennung ist jetzt beabsichtigt.
6. Widerspricht `hydro_flood_eval_status: ok` den `[API-FAIL] hydro_api`-Zeilen im
   Journal, ist das immer ein Befund — dann scheitert der Endpunkt an einer Stelle, die
   der Eval-Block nicht sieht.

### AC-062 — Prüfe die Einzugsgebiets-Überlappung aus dem Export

**Datenquellen:** `hydro_static/station_catchments.geojson`,
`hydro_static/station_network_index.json`, der neueste Frame unter `objects/`,
`config/train_data/runtime_overrides.json` und `manifest.json`.

1. `dropped_expected_files` prüfen und jeden Eintrag als Befund melden.
2. Fehlt `station_catchments.geojson`, obwohl `scanned_roots` sie nennt, stammt der
   Export von vor B434; die weiteren Schritte entfallen.
3. Stationspolygon über `properties.station_id` laden und mit jeder Zellkontur
   (`contour_geo`) schneiden; Schnittfläche in km² bestimmen.
4. Sowohl `HYDRO_MIN_OVERLAP_AREA_KM2` als auch `HYDRO_MIN_OVERLAP_RATIO_CELL` prüfen.
5. Regenrate in der Reihenfolge `nowcast_rain_rate_1h`, `rain_rate_mm_h`,
   `precip_rate_mm_h`, `nowcast_rr_mm15 × 4`, zuletzt `intensity`-Proxy bestimmen.
   `severity.rain_mm_h` ist nicht die verwendete Quelle.
6. Abweichungen von `contributing_cell_count` in
   `hydro_impact/latest_hydro_flood_risk.json` mit Schnittfläche und Schwellen melden.
7. `contributing_cell_count: null` bedeutet „nicht berechnet“ und ist nicht 0.

### AC-063 — Prüfe Snapshot-Integritätsstatus und Startup-Recovery

**Datenquellen im Export:**
- `hydro_ml/hydro_ml_snapshot_status.json`
- `hydro_ml/hydro_flood_samples_snapshot.sqlite3`
- `api_logs/journal/wetterprojekt-scheduler.service.log`
- `hydro_ml/hydro_sample_db_integrity.json`

**Durchzuführen:**

1. `hydro_ml_snapshot_status.json` lesen. Wert `corrupt` ist ein Befund:
   `hydro_ml_snapshot_integrity` melden. Steht dort `ok`, unabhängig davon
   `PRAGMA quick_check` auf `hydro_flood_samples_snapshot.sqlite3` ausführen; weicht das
   Ergebnis ab, läuft die Snapshot-Prüfung nicht — Befund (Export älter als B436).
2. Im Scheduler-Journal nach `Hydro-Startup-Recovery` suchen. Jedes Vorkommen mit
   `status`, `repair`, `gerettet`, `verloren` melden. `verloren` > 0 bedeutet
   endgültigen Datenverlust und ist immer zu melden.
3. Häufen sich `Hydro-Startup-Recovery`-Zeilen über mehrere Exporte, deutet das auf
   wiederkehrende unclean shutdowns hin (Stromversorgung/SD-Karte des Pi) — als
   Hardware-Verdacht melden, nicht als Codebug.

### AC-064 — Prüfe die Deploy-seitige Hydro-DB-Reparatur

**Datenquellen:** Livezugriff auf dem Pi; `train_data/evaluation/install_pytest.log`;
Verzeichnis `train_data/hydro/ml/` und `train_data/hydro/ml/quarantine/`.

**Durchzuführen:**

1. Nach einem `install.sh --mode=upgrade`-Lauf im Installer-Ausgang nach der Zeile
   „Phase 8.95 — Hydro-Sample-DB-Integrität" suchen. Fehlt sie, ist der Installer älter
   als B437 — melden.
2. Steht dort „Hydro-DB repariert: N Zeilen gerettet, M unlesbar übersprungen", das
   Wertepaar melden. `M > 0` ist endgültiger Datenverlust der Tendenz-Historie und immer
   zu melden.
3. Prüfen, dass nach dem Lauf `hydro_flood_ml.sample_db_integrity()` `ok` liefert und die
   drei Services aktiv sind (`systemctl is-active`). Ein `corrupt` nach abgeschlossenem
   Installer ist ein Befund.
4. In `train_data/hydro/ml/` nach `*.pre_b437.*`-Sicherungen und in `quarantine/` nach
   Originalen suchen. Häufen sich diese über mehrere Deploys, deutet das auf
   wiederkehrende Korruption hin (Hardware/Stromversorgung) — als Verdacht melden.

### AC-065 — Prüfe pending_samples auf nicht-objekt-wertige Payloads

**Datenquellen im Export:** `hydro_ml/hydro_flood_samples_snapshot.sqlite3`;
`api_logs/journal/wetterprojekt-admin.service.log`;
`train_data/hydro/ml/hydro_ml_maintenance_latest.json`.

**Durchzuführen:**

1. Auf `hydro_flood_samples_snapshot.sqlite3` zählen:
   `SELECT COUNT(*) FROM pending_samples WHERE payload NOT LIKE '{%'`. Jeder Treffer ist
   ein nicht-objekt-wertiger Payload und ein Befund — Anzahl und, falls vorhanden,
   `sample_id`/`created_at` melden.
2. Im Admin-Journal nach `'float' object has no attribute 'get'` und allgemein nach
   `AttributeError` in `hydro_api`-Zeilen suchen. Jedes Vorkommen mit Zeitstempel
   melden.
3. Falls ein Materialisierungsergebnis vorliegt (Scheduler-Log oder
   `hydro_ml_maintenance_latest.json`), `malformed_pending_skipped` prüfen. Ein Wert > 0
   ist zu melden; hält er über mehrere Läufe an, wurden kaputte Zeilen nicht entfernt —
   dann ist die B438-Bereinigung nicht wirksam.
4. Nicht `quick_check` allein als Beweis für gesunde Samples werten: strukturell
   intakte B-Trees (quick_check == ok) können inhaltlich kaputte Payloads enthalten.
   Die Zählung aus Schritt 1 ist die maßgebliche Prüfung.

### AC-066 — Prüfe, dass keine Entwarnung gesendet wird

**Datenquellen im Export:** `api_logs/journal/*.log`; `main.py` (im Source-Export).

**Durchzuführen:**

1. In den Journalen nach `[EMAIL] Entwarnung gesendet` und jeder WhatsApp-Entwarnung
   suchen. Jedes Vorkommen nach dem B440-Deploy ist ein Befund.
2. Im Source prüfen, dass `main.py` weder `send_allclear_email` noch `send_allclear_wa`
   aufruft. Ein Treffer ist ein Befund.
3. Gegenprobe, dass die Warn-Sperre weiterhin zurückgenommen wird: nach einer
   Gewitterlage muss `[WARN-RESET]` für die betroffenen Orte im Log erscheinen. Fehlt es
   dauerhaft, würden Orte nach dem ersten Alarm nicht wieder warnen — Befund.
### AC-067 — Prüfe den persistenten Warn-Cooldown

**Datenquellen im Export:** `train_data/evaluation/warn_cooldown.json`;
`api_logs/journal/*.log`.

**Durchzuführen:**

1. Aus den Journalen alle `[EMAIL] Warnung gesendet: <Ort>` mit Zeitstempel je Ort
   extrahieren. Liegen für denselben Ort zwei Sendungen näher als WARN_COOLDOWN_S
   (Default 900 s) beieinander, ist der Cooldown unwirksam — Befund mit beiden
   Zeitstempeln.
2. Prüfen, ob `warn_cooldown.json` existiert und je Ort einen plausiblen letzten
   Sendezeitpunkt führt. Fehlt die Datei trotz gesendeter Warnungen, greift die
   Persistenz nicht — Befund.
3. `[WARN-CD] … Cooldown aktiv … Alarm unterdrückt` im Log gegenzählen: Es belegt, dass
   das Gate arbeitet. Bei häufigen `[EMAIL] Warnung gesendet` ohne jedes
   `[WARN-CD]`-Suppress über Stunden ist zu prüfen, ob das Gate umgangen wird.
4. Nicht den cell_id-basierten B98-Schutz als alleinigen Beleg werten — der ist durch
   ID-Wechsel umgehbar. Maßgeblich ist der ortsbasierte Abstand aus Schritt 1.

### AC-069 — Prüfe die JSONL-Leser der Hydro-Impact-Pipeline auf Nicht-Objekt-Zeilen

**Datenquellen im Export:** `train_data/hydro/impact/hydro_impact_*.jsonl`;
`train_data/hydro/*verifications*.jsonl`; `api_logs/journal/wetterprojekt-admin.service.log`.

**Durchzuführen:**

1. In jeder `hydro_impact_*.jsonl` und der Verifications-JSONL prüfen, ob jede Zeile ein
   JSON-Objekt (`{…}`) ist. Jede Zeile, deren `json.loads` kein dict ergibt (Zahl, Array,
   String, null), ist ein Befund — Datei, Zeilennummer und Wert melden.
2. Im Admin-Journal nach `AttributeError: 'float' object has no attribute 'get'` in
   `hydro_api`-Zeilen suchen. Jedes Vorkommen mit Zeitstempel melden.
3. Nicht `_hydro_safe`/`fallback=True` als Beleg für Fehlerfreiheit werten — der Wrapper
   verdeckt den Absturz, das Widget liefert trotzdem leere Daten.

### AC-070 — Prüfe, dass contributing_lineage_ids befüllt ist

**Datenquellen im Export:** `hydro_ml/hydro_flood_samples_snapshot.sqlite3`;
`objects/train_data/objects/*.json`.

**Durchzuführen:**

1. In der Sample-DB alle Zeilen mit `contributing_cell_count>0` zählen und davon jene mit
   leerer `contributing_lineage_ids`-Liste. Ist der Anteil leerer Listen bei vorhandenen
   Zellen weiterhin nahe 100 %, greift die B447-Korrektur nicht — Befund mit den beiden
   Zahlen.
2. Gegenprobe im Zellschema: In `objects/train_data/objects/*.json` prüfen, welche
   Identitätsschlüssel die Zellobjekte tragen (`cell_id`/`id`/`parents`/`lineage`). Taucht
   wieder ein Lesen von `lineage_id`/`parent_cell_ids` auf einem Zellobjekt auf, ist das
   ein erneuter Schlüssel-Mismatch — Befund.
3. Nicht `contributing_cell_ids` als Beleg für einen funktionierenden Lineage-Bezug
   werten: Die Zell-Liste war schon vor B447 korrekt; maßgeblich ist die Lineage-Liste.

### AC-071 — Prüfe, dass geometry_quality im Export vorhanden ist

**Datenquellen im Export:** `hydro_ml/hydro_flood_samples_snapshot.sqlite3`;
exportierte `labeled_samples`.

**Durchzuführen:**

1. In den exportierten `labeled_samples` prüfen, ob `geometry_quality` gesetzt ist und
   welche Werte vorkommen (`shapely`, `unavailable`, `bbox_fallback`). Ist der Wert über
   alle Samples weiterhin None, greift die B448-Durchreichung nicht — Befund.
2. Damit AC-032 fortführen: Zählen, wie oft `geometry_quality == "bbox_fallback"` über
   den verfügbaren Zeitraum vorkommt. Wird der Wert über 30 Tage nie erreicht, den
   bbox_fallback-Zweig als toten Code zur Entfernung in einem eigenen Prompt vormerken —
   nicht nebenbei löschen.
