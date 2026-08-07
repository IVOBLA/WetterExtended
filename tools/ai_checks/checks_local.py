"""P83 — Deterministische Checks (Muster-Migration). Startet mit AC-080.

Weitere ACs werden in Folgeschritten (P8x) hierher migriert. Solange ein AC nicht
migriert ist, bleibt er 'not_implemented' und der LLM-Fallback im lokalen
Analyse-Prompt uebernimmt ihn.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from tools.ai_checks import register

_STATUS_REL = "train_data/evaluation/local_analysis_status.json"
_LOG_REL = "train_data/evaluation/local_analysis_last_run.log"


def _read_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


# P93: Bekannte Zustaende, die keinen Fehler darstellen (run_local_analysis.py).
_AC080_OK_STATES = frozenset({"ok", "mode_repo", "mode_changed_today", "max_attempts_reached"})


@register("AC-080")
def check_ac080_incomplete_step_budget(base) -> dict:
    """AC-080 — Lokaler Analyse-Lauf: letzter Zustand nicht ok?

    Deterministisch: liest local_analysis_status.json. Jeder Zustand ausser den
    bekannten ok-Zustaenden (ok, mode_repo, mode_changed_today, max_attempts_reached)
    ist ein Finding — mit Unterscheidung Budget-Abbruch (incomplete) vs. echter
    Fehler (failed, precondition_failed) vs. unbekannter Zustand. Die Ein-/
    Mehrtagesabgrenzung bleibt dem LLM ueberlassen — der Statusfile traegt nur den
    letzten Lauf.
    """
    st = _read_json(Path(base) / _STATUS_REL)
    if st is None:
        return {"status": "ok",
                "beleg": f"kein {_STATUS_REL} vorhanden (lokale Analyse ggf. nie gelaufen)",
                "detail": {"state": None}}
    state = str(st.get("state", ""))
    if state in _AC080_OK_STATES:
        return {"status": "ok", "beleg": f"state={state}", "detail": {"state": state}}
    error = st.get("error")
    log = st.get("log_path", _LOG_REL)
    if state == "incomplete":
        return {
            "status": "finding",
            "beleg": f"state=incomplete; error={error!r}; log={log}",
            "detail": {
                "state": state,
                "error": error,
                "log_path": log,
                "hinweis": ("einmaliges incomplete = erwarteter Selbstschutz (kein Fehler); "
                            "mehrere Tage in Folge = Verbesserung: max_turns/timeout_s in "
                            "config.LOCAL_ANALYSIS_CONFIG anheben oder erledigte ACs nach "
                            "'## Erledigt' verschieben"),
            },
        }
    if state == "failed":
        return {
            "status": "finding",
            "beleg": f"state=failed; error={error!r}; rc={st.get('rc')}; log={log}",
            "detail": {
                "state": state,
                "error": error,
                "rc": st.get("rc"),
                "log_path": log,
                "hinweis": ("Echter Fehler — Timeout, Prozessabbruch oder unbrauchbare "
                            "Antwort. Log-Datei enthaelt die vollstaendige Spur."),
            },
        }
    if state == "precondition_failed":
        return {
            "status": "finding",
            "beleg": f"state=precondition_failed; error={error!r}",
            "detail": {
                "state": state,
                "error": error,
                "hinweis": ("Vorbedingung fehlt — CLI nicht gefunden, Prompt-Datei fehlt "
                            "oder anderer Start-Blocker. install.sh erneut ausfuehren und "
                            "Vorbedingungen pruefen."),
            },
        }
    # Unbekannter Zustand — sicherheitshalber melden statt verschlucken.
    return {
        "status": "finding",
        "beleg": f"state={state!r} (unbekannt); error={error!r}",
        "detail": {
            "state": state,
            "error": error,
            "hinweis": "Unbekannter Zustand — neue Version von run_local_analysis.py?",
        },
    }


@register("AC-046")
def check_ac046_drift_pooling(base) -> dict:
    """AC-046 — Drift-Trigger gegen die Horizont-Deltas (Pooling-Regressionsguard).

    Getreu zur AC: 'Meldet der Trigger Drift, obwohl jeder einzelne Horizont gleich
    gut oder besser ist, poolt er ueber Horizonte.' Beleg direkt aus drift_status.json
    (drift_detected, triggering_horizons, delta_by_horizon). Diese Felder sind laut
    Autor drift_detector.py bereits die Recent-gegen-Baseline-Deltas je Horizont
    (positiv = schlechter) — keine Re-Ableitung aus accuracy_history.jsonl noetig.
    """
    st = _read_json(Path(base) / "train_data/evaluation/drift_status.json")
    if st is None:
        return {"status": "ok", "beleg": "kein drift_status.json vorhanden",
                "detail": {"drift_detected": None}}
    if not st.get("drift_detected"):
        return {"status": "ok", "beleg": "drift_detected=false",
                "detail": {"drift_detected": False}}
    deltas = st.get("delta_by_horizon") or {}
    triggering = st.get("triggering_horizons") or []
    worst = max(deltas.values()) if deltas else None
    if not triggering:
        return {"status": "finding",
                "beleg": f"drift_detected=true, aber triggering_horizons leer; delta_by_horizon={deltas}",
                "detail": {"drift_detected": True, "triggering_horizons": triggering,
                           "delta_by_horizon": deltas,
                           "hinweis": "Drift ohne ausloesenden Einzel-Horizont — Pooling-Verdacht"}}
    if worst is not None and worst <= 0:
        return {"status": "finding",
                "beleg": f"drift_detected=true, aber max(delta_by_horizon)={worst}<=0 (jeder Horizont gleich/besser)",
                "detail": {"drift_detected": True, "delta_by_horizon": deltas,
                           "hinweis": "Trigger poolt ueber Horizonte (kein Horizont verschlechtert)"}}
    return {"status": "ok",
            "beleg": f"drift_detected=true, ausgeloest durch Horizonte {triggering} (delta>0)",
            "detail": {"drift_detected": True, "triggering_horizons": triggering}}


@register("AC-047")
def check_ac047_skipped_horizons(base) -> dict:
    """AC-047 — Uebersprungene Horizonte (einem Fenster fehlt Datenmaterial).

    Deterministisch: liest skipped_horizons_not_in_both_windows aus drift_status.json.
    Nicht leer -> aktuell fehlt einem Fenster ein Horizont. Ob DAUERHAFT dieselben
    Horizonte fehlen (Fensterlaenge/Zell-Lebensdauer), braucht Mehrtageshistorie
    und bleibt dem LLM.
    """
    st = _read_json(Path(base) / "train_data/evaluation/drift_status.json")
    if st is None:
        return {"status": "ok", "beleg": "kein drift_status.json vorhanden",
                "detail": {"skipped": None}}
    skipped = st.get("skipped_horizons_not_in_both_windows") or []
    if skipped:
        return {"status": "finding",
                "beleg": f"skipped_horizons_not_in_both_windows={skipped}",
                "detail": {"skipped": skipped,
                           "hinweis": ("Momentaufnahme: einem Fenster fehlt ein Horizont. "
                                       "DAUERHAFT dieselben Horizonte erst ueber "
                                       "Mehrtageshistorie beurteilbar — LLM.")}}
    return {"status": "ok", "beleg": "keine uebersprungenen Horizonte", "detail": {"skipped": []}}


@register("AC-014")
def check_ac014_stale_forecast_warnings(base) -> dict:
    """AC-014 — Schreiben stale Forecasts weiterhin Hochwasserwarnungen fort?

    Reines Ein-Datei-Praedikat ueber train_data/hydro/impact/latest_hydro_flood_risk.json
    (Container-Key 'stations', Autor hydro_flood_ml.py). Erwartung: keine Zeile mit
    forecast_evaluation_stale=true UND flood_expected=true bei
    current_q_above_threshold=false. Jeder Treffer ist eine fortgeschriebene
    Altwarnung (stale Prognose haelt eine Warnung ohne aktuelle Schwellenueberschreitung
    am Leben). Keine externen Konstanten, keine Re-Ableitung.
    """
    doc = _read_json(Path(base) / "train_data/hydro/impact/latest_hydro_flood_risk.json")
    if doc is None:
        return {"status": "ok", "beleg": "kein latest_hydro_flood_risk.json vorhanden",
                "detail": {"stations": None}}
    rows = doc.get("stations") or []
    hits = [
        str(r.get("station_id") or "?")
        for r in rows
        if isinstance(r, dict)
        and r.get("forecast_evaluation_stale") is True
        and r.get("flood_expected") is True
        and r.get("current_q_above_threshold") is False
    ]
    if hits:
        return {"status": "finding",
                "beleg": (f"{len(hits)} Station(en) mit stale-fortgeschriebener Warnung "
                          f"(forecast_evaluation_stale=true, flood_expected=true, "
                          f"current_q_above_threshold=false): {hits}"),
                "detail": {"stations": hits}}
    return {"status": "ok", "beleg": f"{len(rows)} Stationen geprueft, keine stale-Altwarnung",
            "detail": {"stations": []}}


@register("AC-043")
def check_ac043_direction_drift_alarm(base) -> dict:
    """AC-043 — Richtungs-Drift-Alarm gegen die Rohwerte (toter/Phantom-Alarm).

    Self-contained aus drift_status.json (seit P86 traegt jeder Horizont-Eintrag
    min_points). Ein Alarm muss genau dann true sein, wenn mindestens ein
    Kurzhorizont p90_deg > threshold_deg bei samples >= min_points zeigt — identisch
    zur Bedingung in drift_detector.check_drift(). Weicht direction_drift_alarm davon
    ab, ist er tot (muesste ausloesen, tut es nicht) oder Phantom. Eintraege ohne
    min_points (Altdaten vor P86) werden konservativ uebersprungen.
    """
    st = _read_json(Path(base) / "train_data/evaluation/drift_status.json")
    if st is None:
        return {"status": "ok", "beleg": "kein drift_status.json vorhanden",
                "detail": {"direction_drift_alarm": None}}
    by_h = st.get("direction_drift_by_horizon") or {}
    if not by_h:
        return {"status": "ok", "beleg": "keine Richtungs-Horizontdaten",
                "detail": {"direction_drift_by_horizon": {}}}
    triggering = []
    for hk, v in by_h.items():
        p90 = v.get("p90_deg")
        thr = v.get("threshold_deg")
        n = v.get("samples", 0)
        mp = v.get("min_points")
        if p90 is not None and thr is not None and mp is not None and n >= mp and p90 > thr:
            triggering.append(hk)
    expected = bool(triggering)
    actual = bool(st.get("direction_drift_alarm"))
    if expected and not actual:
        return {"status": "finding",
                "beleg": (f"toter Alarm: Horizonte {triggering} ueberschreiten threshold_deg bei "
                          f"samples>=min_points, aber direction_drift_alarm=false"),
                "detail": {"triggering_horizons": triggering, "direction_drift_alarm": actual}}
    if actual and not expected:
        return {"status": "finding",
                "beleg": ("Phantom-Alarm: direction_drift_alarm=true, aber kein Horizont "
                          "ueberschreitet threshold_deg bei samples>=min_points"),
                "detail": {"direction_drift_alarm": actual, "direction_drift_by_horizon": by_h}}
    return {"status": "ok",
            "beleg": f"direction_drift_alarm={actual} konsistent (triggering={triggering})",
            "detail": {"direction_drift_alarm": actual, "triggering_horizons": triggering}}


_AC042_REQ_DIR = ("p90_direction_error_deg", "median_direction_error_deg")
_AC042_REQ_SPD = ("p90_speed_error_kmh", "median_speed_error_kmh")
_AC042_COUNT_KEYS = ("count", "samples", "n")


def _read_jsonl_last(path):
    try:
        last = None
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    last = line
        return json.loads(last) if last else None
    except Exception:
        return None


@register("AC-042")
def check_ac042_stats_key_contract(base) -> dict:
    """AC-042 — Schluessel-Kontrakt accuracy_history.jsonl <-> drift_detector.py.

    drift_detector liest je Stats-Eintrag p90_/median_*_error_* und count|samples|n
    (drift_detector.py:317-331). accuracy_tracker._stat_errors schreibt genau diese
    Schluessel atomar (accuracy_tracker.py:625-630); leere Eintraege sind {}. Fehlt in
    einem NICHT-leeren Eintrag ein gelesener Schluessel, liest der Alarm None und ist per
    Datenkontrakt tot. Leere Eintraege ({}) = keine Daten -> uebersprungen. Die erwarteten
    Schluessel sind der Vertrag; ein Contract-Test haelt sie mit drift_detector.py synchron.
    """
    rec = _read_jsonl_last(Path(base) / "train_data/evaluation/accuracy_history.jsonl")
    if rec is None:
        return {"status": "ok", "beleg": "kein/leeres accuracy_history.jsonl vorhanden",
                "detail": {}}
    problems = []

    def _check(group_name, entries, req):
        for hk, v in (entries or {}).items():
            if not isinstance(v, dict) or not v:
                continue  # leerer Eintrag = keine Daten
            missing = [k for k in req if k not in v]
            if not any(k in v for k in _AC042_COUNT_KEYS):
                missing.append("count|samples|n")
            if missing:
                problems.append(f"{group_name}[{hk}] fehlt: {missing}")

    _check("direction_stats_by_horizon", rec.get("direction_stats_by_horizon"), _AC042_REQ_DIR)
    _check("speed_stats_by_horizon", rec.get("speed_stats_by_horizon"), _AC042_REQ_SPD)
    if problems:
        return {"status": "finding",
                "beleg": "Schluessel-Kontrakt verletzt: " + "; ".join(problems),
                "detail": {"probleme": problems}}
    return {"status": "ok", "beleg": "Stats-Schluessel-Kontrakt erfuellt", "detail": {}}


@register("AC-048")
def check_ac048_budget_group_normalization(base) -> dict:
    """AC-048 — Budgetgruppen-Normalisierung. Mehrere counts-Schluessel, die via
    group_for() auf dieselbe Gruppe abbilden, heisst die Normalisierung greift nicht.
    Eine Gruppe OHNE API_DAILY_BUDGET-Eintrag ist bewusst unbegrenzt (kein Fehler).
    """
    st = _read_json(Path(base) / "train_data/evaluation/api_budget.json")
    if st is None:
        return {"status": "ok", "beleg": "kein api_budget.json vorhanden", "detail": {}}
    counts = st.get("counts") or {}
    from api_budget_guard import group_for
    groups = {}
    for key in counts:
        groups.setdefault(group_for(key), []).append(key)
    collisions = {g: ks for g, ks in groups.items() if len(ks) > 1}
    if collisions:
        return {"status": "finding",
                "beleg": f"Normalisierung greift nicht — mehrere Schluessel je Gruppe: {collisions}",
                "detail": {"collisions": collisions}}
    return {"status": "ok", "beleg": f"{len(counts)} Gruppen, keine Normalisierungs-Kollision",
            "detail": {}}


@register("AC-049")
def check_ac049_provider_budget_usage(base) -> dict:
    """AC-049 — Provider-Summe gegen API_DAILY_BUDGET. Auslastung > 70 % -> Abrufkadenz
    melden (Limit NICHT anheben). Projektziel: unnoetige Fremdrequests vermeiden.
    """
    st = _read_json(Path(base) / "train_data/evaluation/api_budget.json")
    if st is None:
        return {"status": "ok", "beleg": "kein api_budget.json vorhanden", "detail": {}}
    counts = st.get("counts") or {}
    from api_budget_guard import group_for
    import config
    budget = getattr(config, "API_DAILY_BUDGET", {}) or {}
    sums = {}
    for key, n in counts.items():
        try:
            g = group_for(key)
            sums[g] = sums.get(g, 0) + int(n or 0)
        except Exception:
            continue
    hot = []
    for grp, limit in budget.items():
        try:
            lim = int(limit)
        except Exception:
            continue
        if lim <= 0:
            continue
        used = int(sums.get(grp, 0))
        pct = used / lim
        if pct > 0.7:
            hot.append(f"{grp}: {used}/{lim} ({pct*100:.0f}%)")
    if hot:
        return {"status": "finding",
                "beleg": "Provider-Auslastung > 70 % — Abrufkadenz pruefen (Limit NICHT anheben): " + "; ".join(hot),
                "detail": {"hot": hot}}
    return {"status": "ok", "beleg": "alle budgetierten Provider <= 70 % Auslastung",
            "detail": {"sums": sums}}


def _read_jsonl_all(path):
    try:
        out = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
        return out
    except Exception:
        return None


@register("AC-007")
def check_ac007_lineage_event_uniqueness(base) -> dict:
    """AC-007 — Eindeutigkeit der Lineage-Ereignisse.

    - Je event_signature genau ein Eintrag in cell_lineage_events.jsonl
      (train_data/cell_lineage/). Events OHNE event_signature (unresolved-Varianten,
      cell_lineage.py:1747/1756) werden uebersprungen.
    - Ein Merge-Event (event_type == "cell_merge") muss auftreten — die Events tragen
      event_type, kein lineage-Feld (cell_lineage.py:1497/1559). Nur gepruft, wenn die
      Datei nicht leer ist (kein Fehlalarm auf frischer Historie).
    - cell_lineage_write_status.json (train_data/system/): last_result != "error".
    """
    base = Path(base)
    problems = []
    st = _read_json(base / "train_data/system/cell_lineage_write_status.json")
    if isinstance(st, dict) and str(st.get("last_result")) == "error":
        problems.append(f"cell_lineage_write_status.last_result=error (last_error={st.get('last_error')!r})")
    events = _read_jsonl_all(base / "train_data/cell_lineage/cell_lineage_events.jsonl")
    if events:
        sig_counts = {}
        has_merge = False
        for e in events:
            if not isinstance(e, dict):
                continue
            if e.get("event_type") == "cell_merge":
                has_merge = True
            sig = e.get("event_signature")
            if sig:
                sig_counts[sig] = sig_counts.get(sig, 0) + 1
        dups = {s: c for s, c in sig_counts.items() if c > 1}
        if dups:
            problems.append(f"doppelte event_signature: {dups}")
        if not has_merge:
            problems.append("kein cell_merge-Event vorhanden (Merge-Erkennung pruefen)")
    if problems:
        return {"status": "finding", "beleg": "; ".join(problems), "detail": {"probleme": problems}}
    return {"status": "ok",
            "beleg": f"{len(events or [])} Lineage-Events, Signaturen eindeutig, write_status ok",
            "detail": {}}

def _rglob_first(base: Path, name: str) -> Path | None:
    """Sucht eine Datei per Name irgendwo unter base — robust gegen die je nach
    Debug-Export-Variante unterschiedliche Sektions-Pfadverschachtelung
    (z. B. hydro_ml/hydro_flood_samples_snapshot.sqlite3 vs. mit train_data/-Praefix).
    """
    try:
        return next(iter(sorted(Path(base).rglob(name))), None)
    except Exception:
        return None


_AC030_FORBIDDEN_FIELDS = (
    "cell_diagnostics", "station_runoff_series", "model_signature",
    "model_source", "ml_predicted_q_delta_m3s", "flood_probability",
    "hydro_flood_risk_score",
)


@register("AC-030")
def check_ac030_public_payload_leak(base) -> dict:
    """AC-030 — Interne Felder im oeffentlichen Hydro-Flood-Payload.

    Deterministisch: liest train_data/hydro/impact/latest_hydro_flood_risk.json
    (derselbe Pfad wie AC-014). Der Cache wird ausschliesslich mit
    include_debug=False geschrieben (evaluate_live_flood_risk(), write=True,
    hydro_flood_ml.py:1036), payload_scope muss daher stets "public" sein. Jede
    Stationszeile durchlaeuft _public_flood_row() (hydro_flood_ml.py:969-971),
    deren Whitelist die sieben verbotenen Felder nicht enthaelt. Ein Treffer
    bedeutet, dass eine andere Schreibstelle den Whitelist-Filter umgeht.
    """
    doc = _read_json(Path(base) / "train_data/hydro/impact/latest_hydro_flood_risk.json")
    if doc is None:
        return {"status": "ok", "beleg": "kein latest_hydro_flood_risk.json vorhanden",
                "detail": {}}
    problems = []
    scope = doc.get("payload_scope")
    if scope != "public":
        problems.append(f"payload_scope={scope!r} (erwartet 'public')")
    top_hits = [f for f in _AC030_FORBIDDEN_FIELDS if f in doc]
    if top_hits:
        problems.append(f"verbotene Felder auf Dokumentebene: {top_hits}")
    for row in doc.get("stations") or []:
        if not isinstance(row, dict):
            continue
        hits = [f for f in _AC030_FORBIDDEN_FIELDS if f in row]
        if hits:
            problems.append(f"station={row.get('station_id')!r}: verbotene Felder {hits}")
    if problems:
        return {"status": "finding", "beleg": "; ".join(problems),
                "detail": {"probleme": problems}}
    return {"status": "ok",
            "beleg": f"payload_scope=public, {len(doc.get('stations') or [])} Stationen ohne verbotene Felder",
            "detail": {}}


@register("AC-031")
def check_ac031_sqlite_snapshot_consistency(base) -> dict:
    """AC-031 — SQLite-Snapshot-Integritaet und Ausschluss unkoordinierter Kopien.

    Sucht hydro_flood_samples_snapshot.sqlite3 per rglob (_prepare_hydro_ml_snapshot()
    legt die Datei immer unter diesem Namen an, debug_export.py:516-568, unabhaengig
    von der Sektions-Pfadverschachtelung). PRAGMA integrity_check muss "ok" liefern.
    Zusaetzlich darf hydro_flood_samples.sqlite3 (ohne "_snapshot") inkl. -wal/-shm
    NICHT im Export liegen — debug_export.py:322-326 schliesst die unkoordinierte
    Live-Kopie beim generischen Wurzel-Scan explizit aus.
    """
    base = Path(base)
    snapshot = _rglob_first(base, "hydro_flood_samples_snapshot.sqlite3")
    problems = []
    if snapshot is None:
        return {"status": "ok", "beleg": "kein hydro_flood_samples_snapshot.sqlite3 im Export",
                "detail": {}}
    import sqlite3
    try:
        con = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
        try:
            rows = con.execute("PRAGMA integrity_check").fetchall()
        finally:
            con.close()
        result = rows[0][0] if rows else None
        if result != "ok":
            problems.append(f"integrity_check={result!r} an {snapshot} (erwartet 'ok')")
    except sqlite3.Error as exc:
        problems.append(f"integrity_check fehlgeschlagen an {snapshot}: {type(exc).__name__}: {exc}")
    stray = sorted(
        str(p) for pattern in ("hydro_flood_samples.sqlite3", "hydro_flood_samples.sqlite3-wal",
                                "hydro_flood_samples.sqlite3-shm")
        for p in base.rglob(pattern)
    )
    if stray:
        problems.append(f"unkoordinierte Kopie im Export: {stray}")
    if problems:
        return {"status": "finding", "beleg": "; ".join(problems), "detail": {"probleme": problems}}
    return {"status": "ok", "beleg": f"integrity_check=ok ({snapshot}), keine unkoordinierte Kopie",
            "detail": {}}


@register("AC-050")
def check_ac050_dataset_export_vs_sqlite(base) -> dict:
    """AC-050 — hydro_flood_dataset.jsonl gegen den SQLite-Snapshot.

    export_labeled_samples_jsonl() (hydro_flood_ml.py:2313-2328) schreibt ALLE
    Zeilen aus load_trainable_labeled_samples(False) — bei trainable_only=False
    ist das trotz des Funktionsnamens die komplette labeled_samples-Tabelle, nicht
    nur eine gefilterte "trainierbare" Teilmenge (hydro_flood_ml.py:1700-1707). Der
    korrekte Vergleich ist daher Zeilenzahl der JSONL gegen COUNT(*) FROM
    labeled_samples im Snapshot. Eine leere JSONL bei gefuellter DB ist immer ein
    eigener, dringlicher Befund (zweiter Schreiber hat sie geleert).
    """
    base = Path(base)
    jsonl = _rglob_first(base, "hydro_flood_dataset.jsonl")
    snapshot = _rglob_first(base, "hydro_flood_samples_snapshot.sqlite3")
    if jsonl is None or snapshot is None:
        return {"status": "ok",
                "beleg": f"jsonl={'vorhanden' if jsonl else 'fehlt'}, snapshot={'vorhanden' if snapshot else 'fehlt'}",
                "detail": {}}
    jsonl_rows = 0
    with open(jsonl, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                jsonl_rows += 1
    import sqlite3
    try:
        con = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
        try:
            db_rows = con.execute("SELECT COUNT(*) FROM labeled_samples").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error as exc:
        return {"status": "error", "beleg": f"Snapshot nicht lesbar: {type(exc).__name__}: {exc}",
                "detail": {}}
    if jsonl_rows == 0 and db_rows > 0:
        return {"status": "finding",
                "beleg": (f"hydro_flood_dataset.jsonl ist leer, aber Snapshot enthaelt "
                          f"{db_rows} labeled_samples — vermutlich von einem zweiten "
                          f"Schreiber geleert"),
                "detail": {"jsonl_rows": jsonl_rows, "db_rows": db_rows}}
    if jsonl_rows != db_rows:
        return {"status": "finding",
                "beleg": (f"jsonl_rows={jsonl_rows} != db_rows={db_rows} (labeled_samples) "
                          f"— Export nicht aktuell oder ueberschrieben"),
                "detail": {"jsonl_rows": jsonl_rows, "db_rows": db_rows}}
    return {"status": "ok", "beleg": f"jsonl_rows=db_rows={jsonl_rows}",
            "detail": {"jsonl_rows": jsonl_rows}}


_AC074_TS_PATTERN_SRC = r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.json$"


@register("AC-074")
def check_ac074_cell_id_uniqueness_per_frame(base) -> dict:
    """AC-074 — cell_id-Eindeutigkeit pro Frame.

    Sucht Objekt-Frame-Dateien per rglob nach dem main.py-Namensmuster
    f"{timestamp}.json" (main.py:996, Timestamp-Format %Y-%m-%d_%H-%M-%S) — robust
    gegen die je nach Debug-Export-Variante unterschiedliche Sektions-Pfad-
    verschachtelung von "objects". Andere gleichnamig gemusterte Dateien (z. B.
    Wetter-Snapshots) werden automatisch verworfen, da sie kein JSON-Array mit
    is_active_cell/cell_id sind. Gruppiert je Frame alle Objekte mit
    is_active_cell=true nach cell_id; mehr als ein aktives Objekt je cell_id im
    selben Frame ist ein Befund (Doku: cell_lineage.py _dedupe_frame_cell_ids /
    update_split_merge_lineage).
    """
    import re
    base = Path(base)
    ts_pattern = re.compile(_AC074_TS_PATTERN_SRC)
    frames = sorted(p for p in base.rglob("*.json") if ts_pattern.match(p.name))
    dup_findings = []
    checked = 0
    for frame in frames:
        try:
            objs = json.loads(frame.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(objs, list):
            continue
        checked += 1
        by_id: dict[str, int] = {}
        for o in objs:
            if not isinstance(o, dict) or o.get("is_active_cell") is not True:
                continue
            cid = o.get("cell_id")
            if cid is None:
                continue
            by_id[str(cid)] = by_id.get(str(cid), 0) + 1
        dups = {cid: n for cid, n in by_id.items() if n > 1}
        if dups:
            dup_findings.append({"frame": frame.name, "duplicates": dups})
    if dup_findings:
        return {"status": "finding",
                "beleg": (f"{len(dup_findings)} Frame(s) mit doppelter aktiver cell_id: "
                          + "; ".join(f"{d['frame']}: {d['duplicates']}" for d in dup_findings[:5])),
                "detail": {"frames": dup_findings}}
    return {"status": "ok", "beleg": f"{checked} Frame(s) geprueft, cell_id je Frame eindeutig",
            "detail": {"frames_checked": checked}}


def _ac079_is_secret_name(base: Path, name: str) -> bool:
    """Delegiert an tools.ro_query.is_secret_name() (B469), wenn importierbar;
    sonst identische Fallback-Logik, damit die Erkennung nie auseinanderlaeuft."""
    import sys
    if (base / "tools" / "ro_query.py").is_file():
        try:
            if str(base) not in sys.path:
                sys.path.insert(0, str(base))
            from tools.ro_query import is_secret_name
            return is_secret_name(name)
        except Exception:
            pass
    low = name.lower()
    if low.startswith(".env"):
        return True
    if low.endswith((".pem", ".key")):
        return True
    if "id_rsa" in low:
        return True
    return False


_AC079_ALLOWED = frozenset({".env", ".env.example"})


@register("AC-079")
def check_ac079_exposed_credential_copies(base) -> dict:
    """AC-079 — ungeschuetzte Zugangsdaten-Kopien im Datenwurzel-Verzeichnis.

    Verwendet dieselbe Erkennung wie tools/ro_query.py is_secret_name() (B469): jede
    .env-Variante (auch Kopien wie .env_Copy/.env.bak/.env~), *.pem, *.key und
    Dateien mit "id_rsa" im Namen. .env und .env.example sind erlaubt (.gitignore
    Zeile 38-41). Ist base ein Git-Checkout, wird zusaetzlich per `git ls-files`
    geprueft, ob ein Fund trotzdem versioniert ist (dann waere .gitignore
    unwirksam). Der Live-rsync-Zielabgleich (Punkt 3 der AC-Anweisung) liegt
    ausserhalb dieses Datenwurzel-Verzeichnisses und bleibt beim naechsten
    Livezugriff durch die KI zu pruefen.
    """
    base = Path(base)
    hits = []
    for p in base.rglob("*"):
        if not p.is_file() or p.name in _AC079_ALLOWED:
            continue
        if _ac079_is_secret_name(base, p.name):
            hits.append(str(p.relative_to(base)))
    if not hits:
        return {"status": "ok", "beleg": "keine ungeschuetzten Zugangsdaten-Kopien gefunden",
                "detail": {}}
    tracked = []
    if (base / ".git").is_dir():
        try:
            import subprocess
            out = subprocess.run(["git", "ls-files"], cwd=str(base), capture_output=True,
                                  text=True, timeout=30)
            tracked_files = set(out.stdout.splitlines()) if out.returncode == 0 else set()
            tracked = [h for h in hits if h in tracked_files]
        except Exception:
            tracked = []
    detail = {"gefunden": hits}
    if tracked:
        detail["git_getrackt"] = tracked
        return {"status": "finding",
                "beleg": f"{len(hits)} Zugangsdaten-Kopie(n) gefunden, davon {len(tracked)} im Git-Tree: {tracked}",
                "detail": detail}
    return {"status": "finding",
            "beleg": f"{len(hits)} Zugangsdaten-Kopie(n) im Datenwurzel-Verzeichnis: {hits}",
            "detail": detail}


@register("AC-057")
def check_ac057_export_admin_panel_persistence(base) -> dict:
    """AC-057 — Nächtlicher Export im Admin-Panel angekommen (Datei-Teil).

    Deterministisch abdeckbar ist nur der Datei-Teil: tools/publish_latest_debug_export_branch.py
    schreibt bei Erfolg train_data/evaluation/latest_export/latest_export_meta.json
    mit export_reason=EXPORT_REASON_SCHEDULED="scheduled_branch_publish"
    (debug_export.py:1164-1201, publish_latest_debug_export_branch.py:29). Fehlt die
    Datei ganz, kann kein automatischer Export je persistiert worden sein — Befund
    (unterscheidet nicht, ob der Timer nie lief oder nur nie erfolgreich war, dafuer
    fehlt hier die Zeitkorrelation). Ist export_reason gesetzt, aber nicht
    "scheduled_branch_publish" (z. B. "last_24h_debug_run"), bietet das Panel nur den
    letzten MANUELLEN Stand an.
    Der Journal-Abgleich der urspruenglichen AC-Anweisung (systemctl status,
    "Persistenz ... fehlgeschlagen"-Warnzeile) ist deterministisch NICHT aus dem
    Debug-Export ableitbar: debug_export.py:701 exportiert nur die Journale von
    wetterprojekt/-scheduler/-admin, nicht von wetterprojekt-debug-export-branch
    selbst (das Skript kann sein eigenes Journal nicht in seinen eigenen Export
    aufnehmen). Dieser Teil bleibt ein Livezugriff auf dem Pi (ro_query.py journal).
    """
    meta = _read_json(Path(base) / "train_data/evaluation/latest_export/latest_export_meta.json")
    if meta is None:
        return {"status": "finding",
                "beleg": "kein latest_export_meta.json vorhanden — noch nie ein Export persistiert",
                "detail": {"hinweis": ("Ob der Timer nie lief oder nur nie erfolgreich war, "
                                        "klaert erst der Journal-Livezugriff auf dem Pi.")}}
    reason = meta.get("export_reason")
    if reason != "scheduled_branch_publish":
        return {"status": "finding",
                "beleg": f"export_reason={reason!r} (erwartet 'scheduled_branch_publish') — "
                         f"Panel bietet nur den letzten manuellen Stand an",
                "detail": {"export_reason": reason, "created_at_utc": meta.get("created_at_utc"),
                           "hinweis": "Journal-Livezugriff noetig, um Timer-Erfolg zu bestaetigen."}}
    return {"status": "ok",
            "beleg": f"export_reason=scheduled_branch_publish, created_at_utc={meta.get('created_at_utc')}",
            "detail": {"created_at_utc": meta.get("created_at_utc"),
                       "hinweis": "Warnzeilen im Journal des Publish-Skripts bleiben Livezugriff-Aufgabe."}}


def _effective_runtime_override(base: Path, key: str):
    doc = _read_json(_rglob_first(Path(base), "effective_runtime_config.json") or Path("/nonexistent"))
    if isinstance(doc, dict) and key in doc:
        return doc[key]
    return None


@register("AC-077")
def check_ac077_cycle_timing(base) -> dict:
    """AC-077 — Zyklusdauer des Live-Loops gegen LOOP_INTERVAL_CELLS_S.

    Deterministisch: liest train_data/status/cycle_timing.json (main.py:430-458,
    Felder last_duration_s/avg_duration_s/max_duration_s/cells_active). Vergleicht
    avg_duration_s bei cells_active=true mit LOOP_INTERVAL_CELLS_S (Default 120s,
    config.py:1328) — per effective_runtime_config.json overridebar, da runtime-
    veraenderlich. Erreicht oder ueberschreitet avg_duration_s das Intervall, ist der
    Verarbeitungszyklus der Engpass. Die Korrelation mit konkreten Gewitterlagen aus
    dem Log-Zeitfenster (Teil 3 der AC) bleibt dem LLM ueberlassen — dafuer fehlt hier
    der Log-Text.
    """
    base = Path(base)
    timing = _read_json(_rglob_first(base, "cycle_timing.json") or base / "nonexistent.json")
    if timing is None:
        return {"status": "ok", "beleg": "kein cycle_timing.json vorhanden", "detail": {}}
    if not timing.get("cells_active"):
        return {"status": "ok", "beleg": "cells_active=false, Intervall-Vergleich nicht anwendbar",
                "detail": {"cells_active": False}}
    avg = timing.get("avg_duration_s")
    interval = _effective_runtime_override(base, "LOOP_INTERVAL_CELLS_S")
    if interval is None:
        interval = 120
    if avg is None:
        return {"status": "ok", "beleg": "avg_duration_s fehlt (zu wenig Zyklen fuer Mittelwert)",
                "detail": {}}
    if float(avg) >= float(interval):
        return {"status": "finding",
                "beleg": (f"avg_duration_s={avg} >= LOOP_INTERVAL_CELLS_S={interval} "
                          f"(last={timing.get('last_duration_s')}, max={timing.get('max_duration_s')}) "
                          f"— Verarbeitungszyklus ist der Engpass"),
                "detail": {"avg_duration_s": avg, "last_duration_s": timing.get("last_duration_s"),
                           "max_duration_s": timing.get("max_duration_s"), "interval_s": interval,
                           "hinweis": "code_ref: main.py _record_cycle_timing"}}
    return {"status": "ok",
            "beleg": f"avg_duration_s={avg} < LOOP_INTERVAL_CELLS_S={interval}",
            "detail": {"avg_duration_s": avg, "interval_s": interval}}


@register("AC-078")
def check_ac078_analysis_duration_vs_timeout(base) -> dict:
    """AC-078 — Lokaler Analyse-Lauf nahe am Zeitlimit (Punkt 7 der AC).

    Deterministisch abgedeckt ist hier ausschliesslich Punkt 7 der AC-Anweisung:
    duration_s > 80% von timeout_s (LOCAL_ANALYSIS_CONFIG, Default 1700s,
    config.py:1055, per effective_runtime_config.json overridebar). Die Punkte 1-5
    (Zustandsklassifikation von state) deckt bereits check_ac080_incomplete_step_budget
    ab; Punkt 2 (mode_repo trotz ANALYSIS_MODE=local) und Punkt 6 (Doppel-Analyse ueber
    analysis_result.json-Zeitstempel) benoetigen eine Mehrquellen-/Mehrtageskorrelation
    und bleiben bewusst beim LLM.
    """
    base = Path(base)
    st = _read_json(base / "train_data/evaluation/local_analysis_status.json")
    if st is None or st.get("duration_s") is None:
        return {"status": "ok", "beleg": "kein Lauf mit duration_s vorhanden", "detail": {}}
    duration = float(st["duration_s"])
    timeout_cfg = _effective_runtime_override(base, "LOCAL_ANALYSIS_CONFIG")
    timeout_s = None
    if isinstance(timeout_cfg, dict):
        timeout_s = timeout_cfg.get("timeout_s")
    if timeout_s is None:
        timeout_s = 1700
    threshold = 0.8 * float(timeout_s)
    if duration > threshold:
        return {"status": "finding",
                "beleg": (f"duration_s={duration} > 80% von timeout_s={timeout_s} "
                          f"(Schwelle={threshold:.1f}) — Auftrag zu umfangreich fuer das Zeitlimit"),
                "detail": {"duration_s": duration, "timeout_s": timeout_s,
                           "hinweis": "Als Verbesserung melden (max_turns/timeout_s anheben "
                                      "oder erledigte ACs nach '## Erledigt' verschieben), nicht als Fehler."}}
    return {"status": "ok",
            "beleg": f"duration_s={duration} <= 80% von timeout_s={timeout_s}",
            "detail": {"duration_s": duration, "timeout_s": timeout_s}}


@register("AC-073")
def check_ac073_lineage_state_corruption(base) -> dict:
    """AC-073 — Lineage-State: Korruption, Quarantaene, liegen gebliebene Temp-Dateien.

    Deterministisch: durchsucht alle exportierten *.service.log-Dateien nach den
    zwei fixen cell_lineage.py-Logzeilen (_debug(), Zeile 208/267:
    '[CELL-LINEAGE] State konnte nicht geladen werden' /
    '... nicht gespeichert werden'); beide Dienste (main.py=wetterprojekt,
    app.py=wetterprojekt-admin) koennen sie schreiben, daher wird ueber alle
    vorhandenen Service-Logs gesucht statt einen festen Dienstnamen anzunehmen.
    Prueft train_data/cell_lineage/ (Export-Sektion "cell_lineage", nicht
    umverschachtelt-sicher -> Suche ueber Pfadanteile) auf *.corrupt.*-Dateien
    (B453-Quarantaene, cell_lineage.py:230) und auf liegen gebliebene *.tmp-Dateien
    (cell_lineage.py:250). Die Ursachenklaerung (Punkt 2 der AC: Quarantaene mit dem
    Log korrelieren) bleibt dem LLM.
    """
    base = Path(base)
    log_hits = []
    for log_path in sorted(base.rglob("*.service.log")):
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for marker in ("[CELL-LINEAGE] State konnte nicht geladen werden",
                       "[CELL-LINEAGE] State konnte nicht gespeichert werden"):
            for line in text.splitlines():
                if marker in line:
                    log_hits.append({"log": log_path.name, "zeile": line.strip()})
    corrupt_files = sorted(
        str(p.relative_to(base)) for p in base.rglob("*.corrupt.*")
        if "cell_lineage" in p.parts
    )
    stray_tmp = sorted(
        str(p.relative_to(base)) for p in base.rglob("*.tmp")
        if "cell_lineage" in p.parts
    )
    problems = []
    if log_hits:
        problems.append(f"{len(log_hits)} Log-Treffer State laden/speichern fehlgeschlagen")
    if corrupt_files:
        problems.append(f"{len(corrupt_files)} quarantaenierte *.corrupt.*-Datei(en): {corrupt_files}")
    if stray_tmp:
        problems.append(f"{len(stray_tmp)} liegen gebliebene *.tmp-Datei(en): {stray_tmp}")
    if problems:
        return {"status": "finding", "beleg": "; ".join(problems),
                "detail": {"log_hits": log_hits, "corrupt_files": corrupt_files,
                           "stray_tmp": stray_tmp}}
    return {"status": "ok", "beleg": "keine Lade-/Speicherfehler, keine Quarantaene, keine Temp-Reste",
            "detail": {}}


@register("AC-045")
def check_ac045_rejected_training_versions(base) -> dict:
    """AC-045 — Verworfene Trainingsversionen duerfen nicht aktiv sein.

    Deterministisch: liest diagnostics/progress_snapshot.json (debug_export.py:1050-1057,
    _build_progress_snapshot() sammelt alle v_*/training_meta.json unter train_data/models/).
    Jede training_meta.json traegt status="promoted"|"rejected" (model_training.py:1128-1144).
    Ist eine als "rejected" markierte Version gleichzeitig is_active=true (oder ist die
    aktive Version ohne status="promoted"), hat eine verworfene Version Alarm/Promotion/
    Fallback-Guard ausgehebelt — Befund. Die [TRAINING] REJECTED-Logzeilen werden zusaetzlich
    ueber alle exportierten *.service.log-Dateien ausgezaehlt und als Kontext mitgeliefert;
    Haeufung/Retention (letzter Satz der AC) bleibt Mehrtages-LLM-Aufgabe.
    """
    base = Path(base)
    snapshot = _rglob_first(base, "progress_snapshot.json")
    if snapshot is None:
        return {"status": "ok", "beleg": "kein progress_snapshot.json vorhanden", "detail": {}}
    doc = _read_json(snapshot)
    if not isinstance(doc, dict):
        return {"status": "ok", "beleg": "progress_snapshot.json nicht lesbar", "detail": {}}
    versions = ((doc.get("progress") or {}).get("versions")) or []
    active_version = (doc.get("progress") or {}).get("active_version") or doc.get("active_version")
    rejected_active = [
        v for v in versions
        if isinstance(v, dict) and v.get("is_active") is True and v.get("status") != "promoted"
    ]
    rejected_count_log = 0
    for log_path in base.rglob("*.service.log"):
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        rejected_count_log += text.count("[TRAINING] REJECTED")
    if rejected_active:
        return {"status": "finding",
                "beleg": (f"aktive Version {active_version!r} hat status="
                          f"{rejected_active[0].get('status')!r} statt 'promoted' — "
                          f"verworfene Version ist aktiv"),
                "detail": {"active_version": active_version, "rejected_active": rejected_active,
                           "rejected_log_lines": rejected_count_log}}
    return {"status": "ok",
            "beleg": (f"aktive Version {active_version!r} hat status=promoted; "
                      f"{rejected_count_log} REJECTED-Logzeile(n) im Export als Kontext"),
            "detail": {"active_version": active_version, "rejected_log_lines": rejected_count_log,
                       "version_count": len(versions)}}


_AC068_076_HORIZONS = (10, 20, 30, 40, 60)
_AC068_076_TS_FMT = "%Y-%m-%d_%H-%M-%S"


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def _bearing_change_deg(b1: float, b2: float) -> float:
    d = abs(b2 - b1) % 360.0
    return d if d <= 180.0 else 360.0 - d


def _forecast_chain(obj: dict) -> "list[tuple[float, float]] | None":
    """origin -> forecast_lat_10/lon_10 -> ... -> forecast_lat_60/lon_60, nur wenn
    ALLE Horizonte vorhanden sind (sonst kann keine vollstaendige Kette bewertet werden)."""
    lat0, lon0 = obj.get("lat"), obj.get("lon")
    if lat0 is None or lon0 is None:
        return None
    pts = [(float(lat0), float(lon0))]
    for h in _AC068_076_HORIZONS:
        flat, flon = obj.get(f"forecast_lat_{h}"), obj.get(f"forecast_lon_{h}")
        if flat is None or flon is None:
            return None
        pts.append((float(flat), float(flon)))
    return pts


def _max_bearing_jump(pts: "list[tuple[float, float]]") -> float:
    if len(pts) < 3:
        return 0.0
    bearings = [_bearing_deg(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
                for i in range(len(pts) - 1)]
    changes = [_bearing_change_deg(bearings[i], bearings[i + 1]) for i in range(len(bearings) - 1)]
    return max(changes) if changes else 0.0


def _ac068_076_frames(base: Path):
    import re
    ts_pattern = re.compile(_AC074_TS_PATTERN_SRC)
    return sorted(p for p in base.rglob("*.json") if ts_pattern.match(p.name))


@register("AC-076")
def check_ac076_bearing_jumps_mixed_mode(base) -> dict:
    """AC-076 — Bearing-Spruenge >45° in GEMISCHTEN ml/kinematic-Prognosefolgen.

    Deterministisch: fuer jedes Objekt in jedem Objekt-Frame (gleiches Namensmuster
    wie AC-074) wird die Kette lat/lon -> forecast_lat_10/lon_10 -> ... ->
    forecast_lat_60/lon_60 (prediction.py:313/941f./1814f./1891f., Horizonte aus
    config.py:820 ML_FORECAST_HORIZONS_MIN=[10,20,30,40,60]) auf Bearing-Spruenge
    zwischen aufeinanderfolgenden Segmenten geprueft. Nur Faelle mit GEMISCHTER
    forecast_mode_<h>-Folge (mindestens zwei unterschiedliche Modi ueber die
    Horizonte) zaehlen fuer diese AC. Zusaetzlich wird die Quote der
    forecast_consistency_adjusted_<h>-Flags ueber alle gemischten Faelle
    ausgewertet; >10% ist laut AC ein Hinweis auf systematische ML/Kinematik-
    Divergenz (code_ref: prediction.py _enforce_cross_horizon_consistency).
    """
    base = Path(base)
    frames = _ac068_076_frames(base)
    findings = []
    mixed_count = 0
    adjusted_true_count = 0
    for frame in frames:
        try:
            objs = json.loads(frame.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(objs, list):
            continue
        for o in objs:
            if not isinstance(o, dict):
                continue
            modes_present = [o.get(f"forecast_mode_{h}") for h in _AC068_076_HORIZONS
                              if o.get(f"forecast_mode_{h}")]
            if len(set(modes_present)) < 2:
                continue
            mixed_count += 1
            if any(o.get(f"forecast_consistency_adjusted_{h}") is True for h in _AC068_076_HORIZONS):
                adjusted_true_count += 1
            pts = _forecast_chain(o)
            if pts is None:
                continue
            max_jump = _max_bearing_jump(pts)
            if max_jump > 45:
                findings.append({
                    "frame": frame.name, "cell_id": o.get("cell_id"),
                    "max_bearing_jump_deg": round(max_jump, 1),
                    "forecast_mode_by_horizon": {str(h): o.get(f"forecast_mode_{h}")
                                                  for h in _AC068_076_HORIZONS},
                })
    if findings:
        quote = adjusted_true_count / mixed_count if mixed_count else 0.0
        return {"status": "finding",
                "beleg": (f"{len(findings)} gemischte ml/kinematic-Folge(n) mit Bearing-Sprung >45°; "
                          f"forecast_consistency_adjusted-Quote={quote:.1%} ueber {mixed_count} "
                          f"gemischte Faelle"),
                "detail": {"findings": findings[:10], "mixed_case_count": mixed_count,
                           "adjusted_quote": quote,
                           "hinweis": ("Quote > 10% der gemischten Faelle deutet auf systematische "
                                       "ML/Kinematik-Divergenz — dann forecast_gate_reason_<h> der "
                                       "betroffenen Horizonte mit auswerten.")}}
    return {"status": "ok",
            "beleg": f"{mixed_count} gemischte Faelle, keine Bearing-Spruenge >45°",
            "detail": {"mixed_case_count": mixed_count}}


@register("AC-068")
def check_ac068_speed_and_zigzag_plausibility(base) -> dict:
    """AC-068 — Zuggeschwindigkeit und Prognose-Zickzack auf Plausibilitaet.

    Deterministisch: speed_kmh>60 (Kärntner Gewitterzellen typisch 15-50 km/h,
    object_tracking.py:2590 speed_kmh), Bearing-Sprung >45° in JEDER Prognosefolge
    (nicht auf gemischte Modi beschraenkt wie AC-076 — Punkt 3 der AC nennt keine
    Einschraenkung), sowie Naehe zum Geschwindigkeits-Deckel (>=95% von
    MAX_CELL_SPEED_KMH, Default 150.0, config.py:509, per
    effective_runtime_config.json overridebar). real_dt aus
    history[-2].timestamp/history[-1].timestamp (Format %Y-%m-%d_%H-%M-%S,
    object_tracking.py:2774-2788) wird als Kontext mitgeliefert, die
    dt-Skalierungs-Korrelation (<3 min) wird nur als Hypothese benannt, nicht als
    bestaetigter Fehler (so verlangt Punkt 2 der AC). Punkt 4 (Kausalitaet
    Zickzack <-> Overspeed) wird durch Ueberschneidung der beiden Fundlisten pro
    Frame+cell_id ermittelt.
    """
    base = Path(base)
    frames = _ac068_076_frames(base)
    max_speed_cfg = _effective_runtime_override(base, "MAX_CELL_SPEED_KMH")
    max_speed = float(max_speed_cfg) if isinstance(max_speed_cfg, (int, float)) else 150.0
    overspeed, zigzag, near_cap = [], [], []
    for frame in frames:
        try:
            objs = json.loads(frame.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(objs, list):
            continue
        for o in objs:
            if not isinstance(o, dict):
                continue
            speed = o.get("speed_kmh")
            real_dt = None
            history = o.get("history")
            if isinstance(history, list) and len(history) >= 2:
                try:
                    from datetime import datetime
                    t1 = datetime.strptime(str(history[-2].get("timestamp")), _AC068_076_TS_FMT)
                    t2 = datetime.strptime(str(history[-1].get("timestamp")), _AC068_076_TS_FMT)
                    real_dt = (t2 - t1).total_seconds() / 60.0
                except Exception:
                    real_dt = None
            if isinstance(speed, (int, float)):
                if speed > 60:
                    overspeed.append({"frame": frame.name, "cell_id": o.get("cell_id"),
                                       "speed_kmh": speed, "real_dt_min": real_dt})
                if max_speed > 0 and speed >= 0.95 * max_speed:
                    near_cap.append({"frame": frame.name, "cell_id": o.get("cell_id"),
                                      "speed_kmh": speed})
            pts = _forecast_chain(o)
            if pts is not None:
                max_jump = _max_bearing_jump(pts)
                if max_jump > 45:
                    zigzag.append({"frame": frame.name, "cell_id": o.get("cell_id"),
                                   "max_bearing_jump_deg": round(max_jump, 1), "speed_kmh": speed})
    problems = []
    if overspeed:
        low_dt = [x for x in overspeed if x["real_dt_min"] is not None and x["real_dt_min"] < 3]
        msg = f"{len(overspeed)} Zelle(n) mit speed_kmh>60"
        if low_dt:
            msg += (f", davon {len(low_dt)} bei real_dt<3min "
                    f"(dt-Skalierungs-Hypothese, code nicht eingesehen — nicht als bestaetigt melden)")
        problems.append(msg)
    if zigzag:
        overlap_keys = {(z["frame"], z["cell_id"]) for z in zigzag} & \
                       {(x["frame"], x["cell_id"]) for x in overspeed}
        msg = f"{len(zigzag)} Zelle(n) mit Bearing-Sprung >45°"
        if overlap_keys:
            msg += f", davon {len(overlap_keys)} zusammen mit speed_kmh>60 (zusammenhaengender Befund)"
        else:
            msg += " (eigenstaendiges Prognose-Problem, keine ueberhoehte Geschwindigkeit dabei)"
        problems.append(msg)
    if near_cap:
        problems.append(f"{len(near_cap)} Zelle(n) nahe MAX_CELL_SPEED_KMH={max_speed} — Clamping-Verdacht")
    if problems:
        return {"status": "finding", "beleg": "; ".join(problems),
                "detail": {"overspeed": overspeed[:10], "zigzag": zigzag[:10], "near_cap": near_cap[:10]}}
    return {"status": "ok",
            "beleg": f"{len(frames)} Frame(s) geprueft, keine Geschwindigkeits-/Sektor-Auffaelligkeit",
            "detail": {"frames_checked": len(frames)}}


@register("AC-010")
def check_ac010_nested_archives_in_export(base) -> dict:
    """AC-010 — Export auf Fremdarchive (verschachtelte ZIPs) pruefen.

    Da ``base`` bereits entpackt ist, bildet die rekursive Suche nach ZIPs
    die Prüfung des ursprünglichen Export-Archivs äquivalent ab. Treffer in
    ``latest_export`` sind ein Rekursionsverdacht; andere Treffer bleiben zur
    Einordnung als möglicherweise legitime Nutzdaten ein Finding.
    """
    base = Path(base)
    hits = sorted(str(p.relative_to(base)) for p in base.rglob("*.zip"))
    if not hits:
        return {"status": "ok", "beleg": "keine *.zip-Dateien im Baum gefunden", "detail": {}}
    recursive = [h for h in hits if "latest_export" in h]
    if recursive:
        return {"status": "finding",
                "beleg": f"{len(recursive)} ZIP(s) unter latest_export/ — Export-Rekursion "
                         f"vermutet (B406/B407 nicht wirksam): {recursive}",
                "detail": {"recursive": recursive, "other": [h for h in hits if h not in recursive]}}
    return {"status": "finding",
            "beleg": f"{len(hits)} ZIP-Datei(en) im Export, ausserhalb von latest_export/ — "
                     f"pruefen ob legitime Nutzdaten: {hits}",
            "detail": {"hits": hits,
                       "hinweis": "Kein Rekursionsverdacht (nicht unter latest_export/), "
                                  "Einordnung als legitime Nutzdaten bleibt LLM-Aufgabe."}}


_AC058_NGINX_LINE_RE = re.compile(
    r'^\S+ \S+ \S+ \[[^\]]+\] "(?P<method>\S+) (?P<path>\S+) \S+" '
    r'(?P<status>\d+) (?P<bytes>\d+|-)'
)


@register("AC-058")
def check_ac058_hydro_flood_risk_store_defect(base) -> dict:
    """AC-058 — Hydro-Flood-Risk auf Store-Defekt und Antwortgroesse pruefen.

    Deckt die Punkte 1-5 der AC-Anweisung ab: kleine Nginx-Antworten,
    gehäufte strukturierte ``hydro_api``-Fehler, SQLite-Integrität, einen nie
    geschriebenen Risk-Cache und einen degradierten Sample-Store. Punkt 6
    ist eine Negativ-Anweisung für das LLM und keine prüfbare Zustandsaussage.
    """
    base = Path(base)
    problems = []
    detail = {}

    nginx_log = base / "api_logs" / "nginx" / "nginx_access.log"
    if nginx_log.is_file():
        try:
            lines = nginx_log.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            lines = []
        small = []
        exact_105 = 0
        for line in lines:
            m = _AC058_NGINX_LINE_RE.match(line)
            if not m or m.group("method") != "GET" or m.group("path") != "/api/hydro/flood-risk":
                continue
            b = m.group("bytes")
            n = int(b) if b.isdigit() else None
            if n is not None and n < 2000:
                small.append(n)
                if n == 105:
                    exact_105 += 1
        if small:
            msg = f"{len(small)} /api/hydro/flood-risk-Antwort(en) < 2000 Bytes"
            if exact_105:
                msg += (f", davon {exact_105}x exakt 105 Bytes "
                        f"(DatabaseError: database disk image is malformed vermutet)")
            problems.append(msg)
            detail["small_nginx_responses"] = {"count": len(small), "exact_105": exact_105}

    api_health = base / "train_data" / "evaluation" / "api_health.jsonl"
    if api_health.is_file():
        hydro_fails = []
        try:
            for line in api_health.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if isinstance(rec, dict) and rec.get("service") == "hydro_api":
                    hydro_fails.append(rec)
        except Exception:
            pass
        if len(hydro_fails) > 5:
            problems.append(
                f"{len(hydro_fails)} hydro_api-Fehler in api_health.jsonl "
                f"({hydro_fails[0].get('ts_utc')} bis {hydro_fails[-1].get('ts_utc')})"
            )
            detail["hydro_api_failures"] = len(hydro_fails)

    snapshot = _rglob_first(base, "hydro_flood_samples_snapshot.sqlite3")
    if snapshot is not None:
        try:
            con = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
            try:
                rows = con.execute("PRAGMA integrity_check").fetchall()
                result = rows[0][0] if rows else None
                if result != "ok":
                    tables = []
                    for row in rows:
                        msg = str(row[0])
                        m2 = re.search(r"rootpage (\d+)", msg)
                        if m2:
                            rp = int(m2.group(1))
                            tname = con.execute(
                                "SELECT name FROM sqlite_master WHERE rootpage=?", (rp,)
                            ).fetchone()
                            tables.append(tname[0] if tname else f"rootpage={rp}")
                    problems.append(f"integrity_check={result!r}"
                                     + (f", betroffene Tabelle(n): {tables}" if tables else ""))
                    detail["sqlite_integrity"] = result
            finally:
                con.close()
        except sqlite3.Error as exc:
            problems.append(f"integrity_check fehlgeschlagen: {type(exc).__name__}: {exc}")

    manifest = _read_json(base / "manifest.json")
    risk_doc_path = base / "train_data" / "hydro" / "impact" / "latest_hydro_flood_risk.json"
    scanned_roots = (manifest or {}).get("scanned_roots") or []
    impact_scanned = any(str(r).rstrip("/").endswith("train_data/hydro/impact") for r in scanned_roots)
    if not risk_doc_path.is_file():
        if impact_scanned:
            problems.append("latest_hydro_flood_risk.json fehlt, obwohl train_data/hydro/impact "
                            "laut manifest.json gescannt wurde — Risk-Cache nie geschrieben")
    else:
        doc = _read_json(risk_doc_path)
        if isinstance(doc, dict):
            store_status = doc.get("sample_store_status")
            if store_status == "degraded":
                faults = doc.get("sample_store_faults") or []
                stages = [f.get("stage") for f in faults if isinstance(f, dict)]
                problems.append(f"sample_store_status=degraded, stages={stages}")
                detail["sample_store_faults"] = stages

    if problems:
        return {"status": "finding", "beleg": "; ".join(problems), "detail": detail}
    return {"status": "ok", "beleg": "keine Store-Defekte/Antwortgroessen-Auffaelligkeiten gefunden",
            "detail": detail}


@register("AC-075")
def check_ac075_hydro_ml_pytest_contamination(base) -> dict:
    """AC-075 — Hydro-ML-Statusdateien auf Pytest-Kontamination pruefen.

    Deckt Punkte 1-2 ab: Pytest-Temporärpfade und unplausibel kleine
    Datenbanken. Punkt 3 (Zeitkorrelation mit ``install_pytest.log``) bleibt
    mangels byte-exakt verifiziertem Logformat bewusst LLM-Aufgabe.
    """
    base = Path(base)
    problems = []
    detail = {}

    integrity = _rglob_first(base, "hydro_sample_db_integrity.json")
    if integrity is not None:
        doc = _read_json(integrity)
        db_path = str((doc or {}).get("db_path") or "")
        if db_path.startswith("/tmp/pytest"):
            problems.append(f"hydro_sample_db_integrity.json: db_path={db_path!r} "
                            f"zeigt auf eine Pytest-Temp-DB (B455-Fehlerklasse)")
            detail["integrity_db_path"] = db_path

    maintenance = _rglob_first(base, "hydro_ml_maintenance_latest.json")
    if maintenance is not None:
        doc = _read_json(maintenance) or {}
        for key in ("db_size_before", "db_size_after"):
            size = doc.get(key)
            if isinstance(size, (int, float)) and 0 < size < 100_000:
                problems.append(f"hydro_ml_maintenance_latest.json: {key}={size} Bytes "
                                f"(<100 KB) — vermutlich Test-DB statt realer Sample-DB")
                detail[key] = size

    if problems:
        return {"status": "finding", "beleg": "; ".join(problems), "detail": detail}
    return {"status": "ok", "beleg": "keine Pytest-Kontamination in den Hydro-ML-Statusdateien",
            "detail": {}}
