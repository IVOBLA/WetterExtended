# AIChecks — offene Prüfungen

Zentrale Liste aller Punkte, die in Prompts als **zu verifizieren** markiert wurden, aber noch
nicht am Livesystem oder an realen Daten bestätigt sind.

**Regel:** Jeder Claude-Code-Prompt trägt seine offenen Prüfungen hier ein. Erledigte Punkte
werden mit Datum und Ergebnis abgeschlossen — nicht gelöscht, damit nachvollziehbar bleibt, was
womit belegt wurde.

**Status:** `offen` · `bestätigt` · `widerlegt` · `hinfällig`

---

## Offen

### AC-001 — `train_data/association` wird nicht befüllt oder nicht exportiert
- **Aus:** B406
- **Befund:** Der Export vom 16.07.2026 enthält 0 Dateien unter `diagnostics/train_data/association`,
  obwohl der Exporteintrag seit B374 existiert (`debug_export.py:333`) und
  `object_tracking.py:1545` das Verzeichnis befüllt.
- **Zu klären:** Existiert `train_data/association` auf dem Pi? Enthält es Dateien? Sind sie älter
  als das 24-h-Fenster?
- **Prüfung:** Nach dem nächsten Export `diagnostics/diagnosis_presence.json` auswerten —
  `status` unterscheidet `missing` / `empty` / `ok`.
- **Blockiert:** Kalibrierung von `ASSOC_MAX_COST` (B400).

### AC-002 — `ASSOC_MAX_COST = 0.75` ist nicht kalibriert
- **Aus:** B400
- **Befund:** Begründete Setzung, keine Messung. Einzige Schwelle, die aktiv Matches verwirft.
- **Prüfung:** Verteilung von `cost` über akzeptierte Matches in `train_data/association/*.json`.
  Häufen sich `no_acceptable_track`-Ablehnungen bei real korrekten Zuordnungen → zu streng.
- **Blockiert durch:** AC-001.

### AC-003 — Transition-Schwellen sind nicht gegen den neuen Code kalibriert
- **Aus:** B375, B387, B394
- **Befund:** `TRANSITION_MERGE_MIN_EXPLAINED = 0.50` und
  `TRANSITION_MERGE_MIN_PARENT_COVERAGE = 0.40` wurden gegen 160 Merge-Beobachtungen vom
  14.07.2026 plausibilisiert (explained: Median 1.00, p25 0.69, p10 0.48; coverage ≥0.40 bei
  78 % von 373 Parent-Beziehungen). Diese Daten stammen jedoch vom **alten** Code — die
  Parentmengen fallen mit globalem Matching (B374) anders aus.
- **Prüfung:** Nach der nächsten Konvektionslage gegen `cell_lineage_events.jsonl` neu rechnen.

### AC-004 — Quellen-Rangfolge der Zuggeschwindigkeit ist instabil
- **Aus:** Analyse 16.07.2026
- **Befund:** Prognosegüte (Median km):

  | Lage | optflow 30 min | ewma 30 min | kalman 30 min |
  |---|---:|---:|---:|
  | 15.07. (31.188 Prognosen) | **11.03** | 14.54 | 12.43 |
  | 16.07. (15.143 Prognosen) | 10.82 | **9.18** | 12.51 |

  Die beste Quelle kippt zwischen zwei Lagen. Der bedingungslose Vorrang des optischen Flusses
  (P-M02, `of_available == 1`) ist damit **nicht** durch Daten gedeckt.
- **Zu klären:** Über mehrere Lagen messen, bevor die Priorität geändert wird. Eine Kalibrierung
  auf Basis einer Lage würde den Zufall festschreiben.
- **Wichtig:** **Nicht** auf Kalman umstellen — am 15.07. war optflow bei 60 min um 5,4 km besser.

### AC-005 — `MULTI_CORE_MIN_SADDLE_RATIO = 0.35` ist nicht kalibriert
- **Aus:** B380, B403
- **Befund:** B403 gibt Splits frei, die B376 blockierte. Ob die Menge stimmt, ist offen.
- **Prüfung:** Gegen die P66-Logs (`[P66] Multi-Core-Split: N Kerne → M Sub-Zellen`). Steigt M
  unplausibel, ist die Schwelle zu lax — **nicht** die Graph-Logik aus B403.

### AC-006 — `lineage="split"` muss im Livebetrieb auftreten
- **Aus:** B381, B383
- **Befund:** Ursprungsbefund waren 0 Splits in 724 Beobachtungen. B381 (Split nach Hungarian) und
  B383 (geodätische Flutung) sollen das beheben.
- **Prüfung:** Nächster Konvektions-Export: Tritt `lineage="split"` bei Multi-Core-Lagen auf?
  Bleibt es 0, liegt die Ursache in der Segmentierung oder den Schwellen (AC-005).

### AC-007 — Bestätigte Merges müssen genau ein Ledger-Event erzeugen
- **Aus:** B371, B391, B396
- **Befund:** B391 macht bestätigte Merges erstmals möglich; B371/B396 verhindern Wiederholung.
- **Prüfung:** `cell_lineage_events.jsonl`: je `event_signature` genau **ein** Eintrag, und
  `lineage="merged"` tritt überhaupt auf.

### AC-008 — Weitere Stellen mit manueller `_UF`-Multiplikation
- **Aus:** B405
- **Befund:** Drei Zweige derselben Schleife dekodierten die ML-Rohausgabe, einer wich ab
  (q10/q90, Faktor 30–40 Fehler). Dieselbe Konstellation kann anderswo existieren.
- **Prüfung:** `grep -n "\* _UF" prediction.py` — jede Stelle, die nicht über
  `_decode_ml_position()` läuft, hat denselben Defekt.

### AC-009 — `training_meta.json` fehlt im Debug-Export
- **Aus:** B405
- **Befund:** Die Datei liegt unter `models/v_*/` und wird nicht exportiert. `target_encoding` ist
  über `ml_readiness.json` verfügbar (`.training_meta.target_encoding = 'delta'`, belegt), die
  vollständige Feature-Liste jedoch nicht.
- **Relevanz:** Bei der ML-Reaktivierung ist die Feature-Liste zum Trainingszeitpunkt für
  Schema-Fragen nötig (vgl. P72 `core_violet_ratio` als Feature 120).

---

## Abgeschlossen

### AC-000 — Beispiel-Eintrag (Format)
- **Aus:** B406
- **Status:** hinfällig — dient nur der Formatdokumentation.
- **Abgeschlossen:** 2026-07-16
