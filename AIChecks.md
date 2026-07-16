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
physikalische Bedeutung. Suche in tests/ nach catchment_area_geometry_km2 und
vergleiche den Wert mit der Fläche der gepatchten Geometrie. Jede Abweichung um mehr
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


---

## Erledigt

_(Format: `AC-xxx — Kurztitel · YYYY-MM-DD · Ergebnis in einem Satz.)_
