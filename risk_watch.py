# risk_watch.py
"""
Risk-Watch: erzwingt den kurzen Loop-Intervall auch ohne aktive Radar-Zelle,
wenn Gewitterpotenzial herrscht ODER eine CB-IR-Vorläuferzelle existiert.

CB-only: Der IR-Trigger nutzt ir_only_precursor == 1.0. Dieses Flag wird nur auf
konvektive IR-Cluster (CB-Kandidaten) gesetzt (detect_ir_cells: BT < 230 K + CAPE/LI).
Andere hochliegende Wolken (Cirren, Amboss-Reste, Frontbewölkung) lösen kein Risk-Watch aus.

Single Source of Truth für die Polling-Priorisierung (main.py-Loop, beide
Intervall-Entscheidungsstellen). Im Test ohne Netzwerk/Server nutzbar:
der HTTP-Getter ist injizierbar (Parameter http_get).
"""
from typing import Callable, Optional

import os
import time

import runtime_config
from config import (
    RISK_WATCH_ENABLED,
    RISK_WATCH_MIN_RISK_LEVEL,
    RISK_WATCH_MAX_DATA_AGE_MIN,
    IR_MAX_DATA_AGE_MIN, IR_WATCH_MIN_SCORE,
    SAVE_PATHS,
)
from debug_utils import debug_log

_RISK_GRID_URL = "http://127.0.0.1:5000/api/risk_grid"
_IR_STATE_FILE = os.path.join(
    SAVE_PATHS.get("ir_cells", "train_data/ir_cells/"), "ir_track_state.json"
)


def _underlying_data_age_min() -> float:
    """Alter (min) der jüngsten zugrunde liegenden Datenquelle (neueste Objekt-Datei
    ODER IR-Track-State). inf, wenn keine Quelle existiert (→ als veraltet behandelt)."""
    import glob
    newest = None
    try:
        candidates = glob.glob(
            os.path.join(SAVE_PATHS.get("objects", "train_data/objects/"), "*.json")
        )
    except Exception:
        candidates = []
    candidates.append(_IR_STATE_FILE)
    for p in candidates:
        try:
            m = os.path.getmtime(p)
            if newest is None or m > newest:
                newest = m
        except OSError:
            continue
    if newest is None:
        return float("inf")
    return (time.time() - newest) / 60.0


def _default_http_get(url: str, timeout: float = 5.0):
    import requests
    return requests.get(url, timeout=timeout)


def _max_risk_level(http_get: Callable) -> int:
    """Maximale Risikostufe (0..3) aus dem lokalen /api/risk_grid. 0 bei Fehler.
    Reiner localhost-Aufruf (eigener Flask-Dienst) — KEIN externer Request."""
    try:
        resp = http_get(_RISK_GRID_URL, timeout=5)
        if getattr(resp, "status_code", 0) != 200:
            return 0
        cells = resp.json().get("cells", []) or []
        return max((int(c.get("risk", 0)) for c in cells), default=0)
    except Exception as exc:
        debug_log(f"[RISK-WATCH] Risikogitter nicht erreichbar: {exc}")
        return 0


def risk_watch_active(
    ir_tracks: Optional[list] = None,
    http_get: Optional[Callable] = None,
    data_age_min: Optional[float] = None,
) -> bool:
    """
    True, wenn der kurze Loop-Intervall erzwungen werden soll.

    Auslöser:
      (a) Mindestens eine CB-IR-Vorläuferzelle (ir_only_precursor == 1.0) in ir_tracks.
          (CB-only durch vorgelagerten Konvektionsfilter in detect_ir_cells.)
      (b) Risikogitter meldet mindestens RISK_WATCH_MIN_RISK_LEVEL.

    Liefert False, wenn RISK_WATCH_ENABLED (config/override) ausgeschaltet ist.
    Bei (a) wird der HTTP-Getter NICHT aufgerufen (frühzeitiger Treffer).
    """
    if not bool(runtime_config.get("RISK_WATCH_ENABLED", RISK_WATCH_ENABLED)):
        return False

    # Codex-Review (1): Im Skip-Pfad werden keine IR-Tracks übergeben (ir_tracks is None).
    # Dann die persistierten aktiven Tracks laden — sonst sieht risk_watch eine
    # CB-IR-Vorläuferzelle nicht (das Risikogitter unterdrückt reine IR-Only-Zellen).
    if ir_tracks is None:
        try:
            from ir_cell_tracking import load_active_ir_tracks
            ir_tracks = load_active_ir_tracks()
        except Exception as exc:
            debug_log(f"[RISK-WATCH] IR-Tracks laden fehlgeschlagen: {exc}")
            ir_tracks = []

    # Codex-Review (2): Frische prüfen. Stoppt das Radar nach einem Gewitter, bleiben
    # alte Objekte/IR-Tracks (missing==0) im Zustand und würden den kurzen Intervall
    # sonst unbegrenzt erzwingen (umgeht den 120-min-Backoff). Sind die zugrunde
    # liegenden Daten älter als RISK_WATCH_MAX_DATA_AGE_MIN → kein Risk-Watch.
    _max_age = float(runtime_config.get("IR_MAX_DATA_AGE_MIN", IR_MAX_DATA_AGE_MIN))
    _age = data_age_min if data_age_min is not None else _underlying_data_age_min()
    if _age > _max_age:
        debug_log(
            f"[RISK-WATCH] Daten zu alt ({_age:.0f} > {_max_age:.0f} min) "
            "→ kein Risk-Watch"
        )
        return False

    # (a) CB-IR-Vorläuferzelle? ir_only_precursor stammt ausschließlich aus
    #     konvektiver IR-Detektion (CB) — keine sonstigen hohen Wolken.
    # B252: Observation-Timestamp des IR-Tracks prüfen. Eingefrorene Tracks
    # (gleicher tiff mehrere Zyklen) dürfen den Kurzintervall nicht erzwingen.
    _ir_obs_max_age = float(runtime_config.get("IR_MAX_DATA_AGE_MIN", IR_MAX_DATA_AGE_MIN))
    for ir in (ir_tracks or []):
        try:
            stage = ir.get("ir_stage") or ir.get("status")
            score = ir.get("ir_score")
            if score is None:
                score = float(runtime_config.get("IR_WATCH_MIN_SCORE", IR_WATCH_MIN_SCORE))
            score = float(score or 0.0)
            if float(ir.get("ir_only_precursor", 0.0)) == 1.0 and (stage in {None, "ir_precursor", "ir_watch_candidate", "ir_pre_cb", "ir_cb_precursor"}) and score >= float(runtime_config.get("IR_WATCH_MIN_SCORE", IR_WATCH_MIN_SCORE)):
                # B252: Observation-Alter des Tracks prüfen
                _obs_ts_str = (
                    ir.get("observation_timestamp")
                    or ir.get("last_seen_observation_timestamp")
                    or ir.get("source_timestamp")
                )
                if _obs_ts_str:
                    try:
                        from datetime import datetime as _dt_rw, timezone as _tz_rw
                        _obs_dt = None
                        for _fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d_%H-%M-%S", "%Y-%m-%dT%H:%M:%S"):
                            try:
                                _obs_dt = _dt_rw.strptime(str(_obs_ts_str).replace("+00:00", "Z"), _fmt).replace(tzinfo=_tz_rw.utc)
                                break
                            except ValueError:
                                pass
                        if _obs_dt:
                            _obs_age_min = (_dt_rw.now(_tz_rw.utc) - _obs_dt).total_seconds() / 60.0
                            if _obs_age_min > _ir_obs_max_age:
                                debug_log(
                                    f"[RISK-WATCH] IR-Track {ir.get('ir_id','?')} "
                                    f"Observation veraltet ({_obs_age_min:.0f} min > "
                                    f"{_ir_obs_max_age:.0f} min) → kein Kurzintervall"
                                )
                                continue
                    except Exception:
                        pass
                debug_log(f"[RISK-WATCH] frische IR-Frühphase/Vorläufer ({stage}) aktiv → kurzer Intervall")
                return True
        except (TypeError, ValueError, AttributeError):
            continue

    # (b) Gewitterpotenzial aus Risikogitter
    min_level = int(runtime_config.get("RISK_WATCH_MIN_RISK_LEVEL", RISK_WATCH_MIN_RISK_LEVEL))
    getter = http_get or _default_http_get
    max_level = _max_risk_level(getter)
    if max_level >= min_level:
        debug_log(
            f"[RISK-WATCH] Gewitterpotenzial Stufe {max_level} ≥ {min_level} "
            f"→ kurzer Intervall"
        )
        return True
    return False
