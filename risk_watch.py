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

import runtime_config
from config import RISK_WATCH_ENABLED, RISK_WATCH_MIN_RISK_LEVEL
from debug_utils import debug_log

_RISK_GRID_URL = "http://127.0.0.1:5000/api/risk_grid"


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

    # (a) CB-IR-Vorläuferzelle? ir_only_precursor stammt ausschließlich aus
    #     konvektiver IR-Detektion (CB) — keine sonstigen hohen Wolken.
    for ir in (ir_tracks or []):
        try:
            if float(ir.get("ir_only_precursor", 0.0)) == 1.0:
                debug_log("[RISK-WATCH] CB-IR-Vorläuferzelle aktiv → kurzer Intervall")
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
