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

---

## Erledigt

_(Format: `AC-xxx — Kurztitel · YYYY-MM-DD · Ergebnis in einem Satz.)_
