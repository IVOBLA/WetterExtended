# cell_filters.py
"""
HitL Cell Filters — Single Source of Truth für manuelle und KI-Filter.

Dieses Modul verwaltet alle benutzerdefinierten und KI-vorgeschlagenen
HSV-Bereiche für die Sturmzellen-Segmentierung. Es ist die einzige Quelle,
aus der object_tracking.py die "allowed_hsv_ranges" lesen soll
(Integration folgt in HitL-2).

Persistenz-Layout:
  train_data/cell_filters/
    ├── cell_filters.json       (JSON-Master-File, gitignored)
    └── polygons/               (PNG-Ausschnitte pro manuellem Filter)
        └── f_<timestamp>_<id>.png

Konkurrenz-Sicherheit:
  - threading.RLock  : Intra-Prozess-Safety (Flask + Scheduler + main)
  - fcntl.flock      : Cross-Process-Safety (drei systemd-Services)
  - os.replace()     : atomares Schreiben (kein halb-geschriebenes JSON)

Migration:
  Beim ersten Aufruf wird FILTER_CONFIG.allowed_hsv_ranges aus
  runtime_overrides.json einmalig nach cell_filters.json übernommen.
  Markiert mit source="migration". runtime_overrides.json bleibt unverändert.

API für object_tracking.py:
  get_active_hsv_ranges() -> list[tuple[tuple, tuple]]
    Gibt alle aktiven Bereiche als [(lower_hsv, upper_hsv), ...] zurück,
    kompatibel zum bisherigen FILTER_CONFIG["allowed_hsv_ranges"]-Format.

API für app.py (HitL-3 folgt):
  load_filters(), save_filters()
  add_manual_filter(...), remove_filter(...), set_filter_active(...)
  add_ai_suggestion(...), accept_ai_suggestion(...)
  save_polygon_png(...), list_active_polygon_pngs(...)
  get_padding_px(zoom_level: int | None) -> int
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

try:
    from debug_utils import debug_log
except Exception:
    def debug_log(msg):
        print(msg)


# ---------------------------------------------------------------------------
# Pfade (lazy aus config laden, damit Import-Order unkritisch ist)
# ---------------------------------------------------------------------------

def _cfg():
    import config as _cfg_mod
    return _cfg_mod


def _filters_dir() -> str:
    return getattr(_cfg(), "CELL_FILTERS_DIR", "train_data/cell_filters/").rstrip("/") + "/"


def _filters_path() -> str:
    return getattr(_cfg(), "CELL_FILTERS_PATH",
                   "train_data/cell_filters/cell_filters.json")


def _polygons_dir() -> str:
    return getattr(_cfg(), "CELL_FILTERS_POLYGON_DIR",
                   "train_data/cell_filters/polygons/").rstrip("/") + "/"


def _migration_marker() -> str:
    return os.path.join(_filters_dir(), ".migrated_v2")


# ---------------------------------------------------------------------------
# Locking + I/O
# ---------------------------------------------------------------------------

_LOCK = threading.RLock()

_EMPTY_DOC: dict = {
    "version": 2,
    "active_filters": [],
    "ai_suggestions": [],
}


def _ensure_dirs() -> None:
    os.makedirs(_filters_dir(), exist_ok=True)
    os.makedirs(_polygons_dir(), exist_ok=True)


def load_filters() -> dict:
    """Lese-API. Liefert {} bei fehlender Datei. Shared File-Lock."""
    path = _filters_path()
    if not os.path.exists(path):
        return dict(_EMPTY_DOC)
    try:
        with open(path, "r", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                data = json.load(f)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        if not isinstance(data, dict):
            return dict(_EMPTY_DOC)
        data.setdefault("version", 2)
        data.setdefault("active_filters", [])
        data.setdefault("ai_suggestions", [])
        return data
    except Exception as exc:
        debug_log(f"[CELL_FILTERS] load_filters Fehler: {exc}")
        return dict(_EMPTY_DOC)


def save_filters(data: dict) -> None:
    """Schreib-API. Exclusive File-Lock + atomic replace + fsync."""
    _ensure_dirs()
    path = _filters_path()
    tmp = path + ".tmp"
    with _LOCK:
        with open(tmp, "w", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=False)
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def migrate_from_runtime_config_if_needed() -> bool:
    """
    Beim allerersten Aufruf werden FILTER_CONFIG.allowed_hsv_ranges aus
    runtime_overrides.json (oder Default config.FILTER_CONFIG) einmalig in
    cell_filters.json übernommen. Idempotent über .migrated_v2-Marker.

    Rückgabe: True wenn migriert wurde, False wenn schon migriert.
    """
    _ensure_dirs()
    marker = _migration_marker()
    if os.path.exists(marker):
        return False

    try:
        import runtime_config
        fc = runtime_config.get("FILTER_CONFIG", None)
    except Exception:
        fc = None

    if fc is None:
        fc = getattr(_cfg(), "FILTER_CONFIG", {"allowed_hsv_ranges": []})

    ranges = list(fc.get("allowed_hsv_ranges", []))
    if not ranges:
        with open(marker, "w", encoding="utf-8") as f:
            f.write(_iso_now() + "  empty\n")
        return False

    doc = load_filters()
    now_iso = _iso_now()
    for idx, rng in enumerate(ranges):
        try:
            lower = [int(x) for x in rng[0]]
            upper = [int(x) for x in rng[1]]
        except Exception:
            continue
        doc["active_filters"].append({
            "id":            _make_id("mig", idx),
            "label":         f"migration_{idx}",
            "hsv_range":     [lower, upper],
            "source":        "migration",
            "created_at":    now_iso,
            "polygon_png":   None,
            "polygon_meta":  {},
            "active":        True,
        })

    save_filters(doc)
    with open(marker, "w", encoding="utf-8") as f:
        f.write(f"{now_iso}  migrated {len(ranges)} ranges\n")
    debug_log(f"[CELL_FILTERS] Migration: {len(ranges)} Bereiche übernommen.")
    return True


# ---------------------------------------------------------------------------
# Public Read-API (für object_tracking.py — HitL-2)
# ---------------------------------------------------------------------------

def get_active_hsv_ranges() -> list:
    """
    Liefert alle aktiven HSV-Bereiche als Liste von (lower_tuple, upper_tuple).
    Kompatibel zum bisherigen FILTER_CONFIG["allowed_hsv_ranges"]-Format,
    das cv2.inRange direkt akzeptiert.
    """
    migrate_from_runtime_config_if_needed()
    doc = load_filters()
    out: list = []
    for entry in doc.get("active_filters", []):
        if not entry.get("active", True):
            continue
        rng = entry.get("hsv_range")
        if not (isinstance(rng, list) and len(rng) == 2):
            continue
        lower = tuple(int(x) for x in rng[0])
        upper = tuple(int(x) for x in rng[1])
        if len(lower) == 3 and len(upper) == 3:
            out.append((lower, upper))
    return out


# ---------------------------------------------------------------------------
# Write-API (für app.py — HitL-3)
# ---------------------------------------------------------------------------

def add_manual_filter(
    label: str,
    hsv_range: list,
    polygon_meta: Optional[dict] = None,
    polygon_png: Optional[str] = None,
    source: str = "manual_polygon",
) -> str:
    """
    Fügt einen neuen aktiven Filter hinzu. Liefert die neue Filter-ID.
    hsv_range muss [[h_lo, s_lo, v_lo], [h_hi, s_hi, v_hi]] sein.
    """
    _validate_hsv_range(hsv_range)
    doc = load_filters()
    new_id = _make_id("f", len(doc.get("active_filters", [])))
    doc["active_filters"].append({
        "id":            new_id,
        "label":         str(label)[:40] or "manuell",
        "hsv_range":     [list(map(int, hsv_range[0])),
                          list(map(int, hsv_range[1]))],
        "source":        source,
        "created_at":    _iso_now(),
        "polygon_png":   polygon_png,
        "polygon_meta":  polygon_meta or {},
        "active":        True,
    })
    save_filters(doc)
    return new_id


def remove_filter(filter_id: str) -> bool:
    """Löscht einen Filter + zugehöriges PNG. True wenn entfernt."""
    doc = load_filters()
    before = len(doc.get("active_filters", []))
    target = None
    for entry in doc.get("active_filters", []):
        if entry.get("id") == filter_id:
            target = entry
            break
    if target is None:
        return False
    png_rel = target.get("polygon_png")
    if png_rel:
        png_path = os.path.join(_filters_dir(), png_rel)
        try:
            if os.path.exists(png_path):
                os.remove(png_path)
        except Exception as exc:
            debug_log(f"[CELL_FILTERS] PNG-Lösch-Warnung: {exc}")
    doc["active_filters"] = [
        e for e in doc["active_filters"] if e.get("id") != filter_id
    ]
    save_filters(doc)
    return len(doc["active_filters"]) < before


def set_filter_active(filter_id: str, active: bool) -> bool:
    """Aktiviert oder deaktiviert einen Filter. Datei wird nicht gelöscht."""
    doc = load_filters()
    changed = False
    for entry in doc.get("active_filters", []):
        if entry.get("id") == filter_id:
            entry["active"] = bool(active)
            changed = True
            break
    if changed:
        save_filters(doc)
    return changed


def add_ai_suggestion(
    model: str,
    based_on_filter_ids: list,
    suggested_ranges: list,
) -> str:
    """
    Speichert einen KI-Vorschlag (ohne ihn aktiv zu machen).
    suggested_ranges: [{"hsv_range": [[lo],[hi]], "label": str, "rationale": str}]
    Rückgabe: ID des Suggestion-Eintrags.
    """
    validated = []
    for s in suggested_ranges:
        try:
            _validate_hsv_range(s["hsv_range"])
            validated.append({
                "hsv_range": [list(map(int, s["hsv_range"][0])),
                              list(map(int, s["hsv_range"][1]))],
                "label":     str(s.get("label", "ki_vorschlag"))[:60],
                "rationale": str(s.get("rationale", ""))[:500],
            })
        except Exception as exc:
            debug_log(f"[CELL_FILTERS] AI-Vorschlag verworfen: {exc}")
    doc = load_filters()
    sug_id = _make_id("ai", len(doc.get("ai_suggestions", [])))
    doc["ai_suggestions"].append({
        "id":                   sug_id,
        "created_at":           _iso_now(),
        "model":                str(model)[:60],
        "based_on_filter_ids":  list(based_on_filter_ids),
        "suggested_ranges":     validated,
        "accepted":             False,
    })
    save_filters(doc)
    return sug_id


def accept_ai_suggestion(suggestion_id: str) -> list:
    """
    Übernimmt alle Ranges aus einem KI-Vorschlag als aktive Filter.
    Rückgabe: Liste der neu angelegten Filter-IDs.
    """
    doc = load_filters()
    target = None
    for s in doc.get("ai_suggestions", []):
        if s.get("id") == suggestion_id:
            target = s
            break
    if target is None or target.get("accepted"):
        return []
    new_ids = []
    for r in target.get("suggested_ranges", []):
        nid = add_manual_filter(
            label=r.get("label", "ki_vorschlag"),
            hsv_range=r["hsv_range"],
            polygon_meta={"ai_rationale": r.get("rationale", ""),
                          "source_suggestion_id": suggestion_id},
            polygon_png=None,
            source="ai_suggestion",
        )
        new_ids.append(nid)
    doc = load_filters()
    for s in doc.get("ai_suggestions", []):
        if s.get("id") == suggestion_id:
            s["accepted"] = True
            s["accepted_at"] = _iso_now()
            s["created_filter_ids"] = new_ids
            break
    save_filters(doc)
    return new_ids


def list_active_polygon_pngs(max_count: int = 5) -> list:
    """
    Liefert die letzten N aktiven Filter, die einen Polygon-PNG-Pfad haben.
    Format: [{"id", "label", "hsv_range", "polygon_png_abs", "created_at"}, ...]
    Sortiert nach created_at absteigend (jüngste zuerst).
    """
    doc = load_filters()
    items = []
    for entry in doc.get("active_filters", []):
        if not entry.get("active", True):
            continue
        png_rel = entry.get("polygon_png")
        if not png_rel:
            continue
        abs_path = os.path.join(_filters_dir(), png_rel)
        if not os.path.exists(abs_path):
            continue
        items.append({
            "id":               entry["id"],
            "label":            entry.get("label", ""),
            "hsv_range":        entry.get("hsv_range"),
            "polygon_png_abs":  abs_path,
            "polygon_png_rel":  png_rel,
            "created_at":       entry.get("created_at", ""),
            "polygon_meta":     entry.get("polygon_meta", {}),
        })
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return items[:max_count]


# ---------------------------------------------------------------------------
# PNG-Speicherung
# ---------------------------------------------------------------------------

def get_padding_px(zoom_level: Optional[int] = None) -> int:
    """
    Liefert die Padding-Breite in Pixeln, mit der das Polygon-PNG aus dem
    verarbeiteten Radarbild ausgeschnitten wird. User-konfigurierbar.

    Lookup-Reihenfolge:
      1. runtime_config["HITL_PADDING_PX"]              (User-Override)
      2. config.HITL_PADDING_PX_DEFAULT                  (Modul-Default 50)
    """
    try:
        import runtime_config
        default_px = getattr(_cfg(), "HITL_PADDING_PX_DEFAULT", 50)
        return int(runtime_config.get("HITL_PADDING_PX", default_px))
    except Exception:
        return int(getattr(_cfg(), "HITL_PADDING_PX_DEFAULT", 50))


def save_polygon_png(
    filter_id: str,
    processed_img_bgr,
    polygon_pixels_xy: list,
    padding_px: Optional[int] = None,
) -> str:
    """
    Schneidet das verarbeitete Radarbild rund um das Polygon mit Padding aus
    und speichert es als PNG mit semi-transparentem Maskenoverlay.

    Rückgabe:
      Relativer Pfad ab _filters_dir(), z.B. "polygons/f_xxx.png"
    """
    import cv2 as _cv2
    import numpy as _np

    if padding_px is None:
        padding_px = get_padding_px()
    padding_px = max(5, min(500, int(padding_px)))

    h_img, w_img = processed_img_bgr.shape[:2]
    pts = _np.array(polygon_pixels_xy, dtype=_np.int32).reshape(-1, 2)
    if len(pts) < 3:
        raise ValueError("Polygon braucht mindestens 3 Punkte")

    x_min = max(0, int(pts[:, 0].min()) - padding_px)
    y_min = max(0, int(pts[:, 1].min()) - padding_px)
    x_max = min(w_img, int(pts[:, 0].max()) + padding_px)
    y_max = min(h_img, int(pts[:, 1].max()) + padding_px)
    if x_max - x_min < 4 or y_max - y_min < 4:
        raise ValueError("Ausschnitt zu klein")

    crop = processed_img_bgr[y_min:y_max, x_min:x_max].copy()
    crop_h, crop_w = crop.shape[:2]

    shifted = pts.copy()
    shifted[:, 0] -= x_min
    shifted[:, 1] -= y_min

    overlay = crop.copy()
    _cv2.fillPoly(overlay, [shifted.reshape(-1, 1, 2)], (0, 200, 255))
    blended = _cv2.addWeighted(overlay, 0.25, crop, 0.75, 0)
    _cv2.polylines(blended, [shifted.reshape(-1, 1, 2)],
                   isClosed=True, color=(0, 165, 255), thickness=2)

    _ensure_dirs()
    fname = f"{filter_id}.png"
    rel_path = os.path.join("polygons", fname)
    abs_path = os.path.join(_filters_dir(), rel_path)
    ok = _cv2.imwrite(abs_path, blended)
    if not ok:
        raise IOError(f"cv2.imwrite fehlgeschlagen: {abs_path}")
    debug_log(f"[CELL_FILTERS] PNG gespeichert: {rel_path} "
              f"({crop_w}×{crop_h} px, padding={padding_px})")
    return rel_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _make_id(prefix: str, salt: int) -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    h = hashlib.sha1(
        f"{ts}-{salt}-{time.monotonic_ns()}".encode("utf-8")
    ).hexdigest()[:4]
    return f"{prefix}_{ts}_{h}"


def _validate_hsv_range(rng: Any) -> None:
    if not (isinstance(rng, (list, tuple)) and len(rng) == 2):
        raise ValueError("hsv_range braucht [lower, upper]")
    for bound in rng:
        if not (isinstance(bound, (list, tuple)) and len(bound) == 3):
            raise ValueError("Jede Grenze muss [H, S, V] sein")
        for v in bound:
            if not isinstance(v, (int, float)) or not (0 <= v <= 255):
                raise ValueError(f"HSV-Wert außerhalb 0–255: {v}")


# ---------------------------------------------------------------------------
# Selbsttest
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"cell_filters.py — Selbsttest")
    print(f"  Pfad: {_filters_path()}")
    migrated = migrate_from_runtime_config_if_needed()
    print(f"  Migration ausgeführt: {migrated}")
    doc = load_filters()
    print(f"  Version: {doc.get('version')}")
    print(f"  Aktive Filter: {len(doc.get('active_filters', []))}")
    print(f"  AI-Vorschläge: {len(doc.get('ai_suggestions', []))}")
    print(f"  get_active_hsv_ranges() → {len(get_active_hsv_ranges())} Einträge")
    print(f"  Padding (default): {get_padding_px()} px")
