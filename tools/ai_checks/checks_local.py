"""P83 — Deterministische Checks (Muster-Migration). Startet mit AC-080.

Weitere ACs werden in Folgeschritten (P8x) hierher migriert. Solange ein AC nicht
migriert ist, bleibt er 'not_implemented' und der LLM-Fallback im lokalen
Analyse-Prompt uebernimmt ihn.
"""
from __future__ import annotations

import json
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
