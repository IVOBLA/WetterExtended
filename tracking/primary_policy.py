"""B377: EINE Primary-Policy für Radar-Track-ID und fachliche cell_id.

Warum ein gemeinsames Modul
---------------------------
Bisher entschieden zwei widersprüchliche Regeln, welche Identität einen Merge
überlebt:

  Radar-Ebene (object_tracking.py):  groesste ALTE POLYGONFLAECHE
  Fach-Ebene  (cell_lineage.py):     Survivor-Kontinuitaet (B268), sonst
                                     CELL_LINEAGE_PRIMARY_MERGE_POLICY

Die konfigurierte Policy `highest_core_ratio` griff dadurch nur im Ausnahmefall.
Das Admin-Panel suggerierte Einfluss, den die Einstellung nicht hatte.

Dieses Modul ist die EINZIGE Quelle der Wahrheit. Beide Ebenen rufen
`select_primary_parent()` auf.

Policies
--------
continuity_score  (Default, empfohlen): gewichteter Score aus Trackalter,
                  Kernstärke, Kernkontinuität und Flächenbeitrag.
highest_core_ratio: bisheriges Fach-Verhalten (staerkster Kern gewinnt).
largest_area:       bisheriges Radar-Verhalten (groesste alte Flaeche gewinnt).
survivor_first:     B268-Verhalten (etablierte cell_id des Survivors gewinnt).
"""
from __future__ import annotations

from typing import Any

try:
    import runtime_config as _rc
except Exception:  # pragma: no cover
    _rc = None

_DEFAULTS = {
    "PRIMARY_POLICY": "continuity_score",
    "PRIMARY_W_AGE": 0.30,
    "PRIMARY_W_CORE": 0.30,
    "PRIMARY_W_AREA": 0.25,
    "PRIMARY_W_CORE_AREA": 0.15,
    # Ab diesem Trackalter (Frames) gilt ein Track als voll etabliert.
    "PRIMARY_AGE_SATURATION_FRAMES": 12,
}

VALID_POLICIES = ("continuity_score", "highest_core_ratio", "largest_area", "survivor_first")


def _cfg(key: str, default: Any = None) -> Any:
    if default is None:
        default = _DEFAULTS.get(key)
    if _rc is not None:
        try:
            return _rc.get(key, default)
        except Exception:
            pass
    return default


def _num(obj: dict, *keys: str) -> float:
    for k in keys:
        v = (obj or {}).get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return 0.0


def continuity_score(parent: dict, *, max_area: float = 0.0, max_core_area: float = 0.0) -> float:
    """Fachliche Kontinuität eines Merge-Parents (0..1, höher = eher Survivor).

    Bewusst mehrere Kriterien statt eines Einzelmerkmals: „groesste Flaeche
    gewinnt" bevorzugt bei einer zerfallenden Systemhuelle die Flaeche statt des
    konvektiv aktiven Kerns.
    """
    age = _num(parent, "total_active_frames", "age_frames")
    age_sat = max(float(_cfg("PRIMARY_AGE_SATURATION_FRAMES")), 1.0)
    s_age = min(age / age_sat, 1.0)

    s_core = min(max(_num(parent, "core_ratio"), 0.0), 1.0)

    area = _num(parent, "area", "area_px", "area_km2")
    s_area = (area / max_area) if max_area > 0 else 0.0
    s_area = min(max(s_area, 0.0), 1.0)

    core_area = _num(parent, "core_area_px")
    if core_area <= 0.0:
        core_area = _num(parent, "core_ratio") * area
    s_core_area = (core_area / max_core_area) if max_core_area > 0 else 0.0
    s_core_area = min(max(s_core_area, 0.0), 1.0)

    return (
        float(_cfg("PRIMARY_W_AGE")) * s_age
        + float(_cfg("PRIMARY_W_CORE")) * s_core
        + float(_cfg("PRIMARY_W_AREA")) * s_area
        + float(_cfg("PRIMARY_W_CORE_AREA")) * s_core_area
    )


def select_primary_parent(parents: list, *, policy: str | None = None,
                          survivor_id: str | None = None, id_key: str = "id") -> dict | None:
    """Einzige Quelle der Wahrheit für die Primary-Auswahl bei einem Merge.

    parents:     Liste von Parent-Objekten (dicts).
    survivor_id: optionale ID des global gematchten Survivors (nur für
                 `survivor_first` relevant).
    id_key:      Feld, das die ID traegt ("id" auf Radar-, "cell_id" auf Fachebene).
    """
    valid = [p for p in (parents or []) if isinstance(p, dict)]
    if not valid:
        return None

    policy = str(policy or _cfg("PRIMARY_POLICY"))
    if policy not in VALID_POLICIES:
        policy = "continuity_score"

    if policy == "survivor_first" and survivor_id:
        match = next((p for p in valid if str(p.get(id_key)) == str(survivor_id)), None)
        if match is not None:
            return match

    if policy == "largest_area":
        return max(enumerate(valid), key=lambda it: (_num(it[1], "area", "area_px", "area_km2"), -it[0]))[1]

    if policy == "highest_core_ratio":
        return max(enumerate(valid),
                   key=lambda it: (_num(it[1], "core_ratio"),
                                   _num(it[1], "area", "area_px", "area_km2"), -it[0]))[1]

    max_area = max((_num(p, "area", "area_px", "area_km2") for p in valid), default=0.0)
    max_core_area = max(
        (_num(p, "core_area_px") or _num(p, "core_ratio") * _num(p, "area", "area_px") for p in valid),
        default=0.0,
    )
    # -it[0] als letzter Tiebreak -> deterministisch bei identischem Score.
    return max(enumerate(valid),
               key=lambda it: (continuity_score(it[1], max_area=max_area, max_core_area=max_core_area),
                               -it[0]))[1]
