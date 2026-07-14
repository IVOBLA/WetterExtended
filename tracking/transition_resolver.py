"""B375: Merge-/Split-Auflösung NACH dem globalen 1:1-Matching.

Trennt Zustand von Ereignis
---------------------------
Bisher war `lineage="merged"` ein Dauerzustand: solange die Geometrie den Verbund
zeigte, meldete jeder Frame erneut ein Merge. Belegt: 23 Merge-Serien, im Mittel
6.6 Frames, die längste 11 Frames (~55 min) -- das ist kein Fusionsereignis,
sondern ein bestehender Verbund.

Gleichzeitig war der Split-Pfad strukturell unerreichbar: `used_ids` verhinderte,
dass dieselbe alte ID mehreren neuen Konturen zugeordnet wird -- genau die
Bedingung, die object_tracking.py fuer einen Split verlangte. Ergebnis: 0 Splits
in 724 Beobachtungen, obwohl P66 nachweislich Sub-Zellen erzeugt.

Zustandsautomat:  candidate -> confirmed -> closed
                            \\-> reverted

Ein Kandidat wird erst nach TRANSITION_CONFIRM_FRAMES konsistenten Frames
bestaetigt. Bis dahin darf die Karte ihn anzeigen, aber die Identitaet/Lineage
wird nicht veraendert. Verschwindet er, gilt `reverted` -- ohne Lineage-Wirkung.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

try:
    import runtime_config as _rc
except Exception:  # pragma: no cover
    _rc = None

_DEFAULTS = {
    "TRANSITION_CONFIRM_FRAMES": 2,
    # Mindestanteil der ALTEN Flaeche, den ein Parent zur neuen Zelle beitragen muss.
    "TRANSITION_MERGE_MIN_PARENT_COVERAGE": 0.40,
    # Mindestanteil der NEUEN Flaeche, den alle Parents zusammen erklaeren muessen.
    "TRANSITION_MERGE_MIN_EXPLAINED": 0.50,
    # Mindestanteil der ALTEN Flaeche, den alle Kinder zusammen erklaeren muessen.
    "TRANSITION_SPLIT_MIN_EXPLAINED": 0.50,
    "TRANSITION_SPLIT_MIN_CHILD_SHARE": 0.15,
}


def _cfg(key, default=None):
    if default is None:
        default = _DEFAULTS.get(key)
    if _rc is not None:
        try:
            return _rc.get(key, default)
        except Exception:
            pass
    return default


def transition_signature(kind: str, parents: list, children: list) -> str:
    """Zeitstempelfreie Identitaet eines Uebergangs (analog B371)."""
    payload = "|".join([
        str(kind),
        ",".join(sorted(str(p) for p in (parents or []) if p)),
        ",".join(sorted(str(c) for c in (children or []) if c)),
    ])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


@dataclass
class TransitionCandidate:
    kind: str                      # "merge" | "split"
    parents: list = field(default_factory=list)
    children: list = field(default_factory=list)
    signature: str = ""
    explained: float = 0.0
    frames_seen: int = 1
    phase: str = "candidate"


def _safe_area(poly) -> float:
    try:
        return float(poly.area)
    except Exception:
        return 0.0


def _inter(a, b) -> float:
    if a is None or b is None:
        return 0.0
    try:
        return float(a.intersection(b).area)
    except Exception:
        return 0.0


def find_merge_candidates(unmatched_tracks: dict, detections: dict, matched: dict) -> list:
    """n:1 — mehrere UNMATCHED alte Zellen überdecken dieselbe neue Zelle.

    unmatched_tracks: track_id -> Polygon (nicht 1:1 zugeordnet)
    detections:       det_index -> Polygon
    matched:          det_index -> track_id (Ergebnis des globalen Matchings)
    """
    min_cov = float(_cfg("TRANSITION_MERGE_MIN_PARENT_COVERAGE"))
    min_expl = float(_cfg("TRANSITION_MERGE_MIN_EXPLAINED"))
    out = []
    for det_idx, det_poly in (detections or {}).items():
        new_area = _safe_area(det_poly)
        if new_area <= 0:
            continue
        parents, explained = [], 0.0
        for tid, tpoly in (unmatched_tracks or {}).items():
            old_area = _safe_area(tpoly)
            if old_area <= 0:
                continue
            inter = _inter(det_poly, tpoly)
            # Jeder Parent muss einen RELEVANTEN Anteil seiner eigenen alten
            # Flaeche beitragen. Der alte 0.30-Fallback liess kleine Randtracks
            # zu Merge-Parents werden, obwohl sie nichts erklaerten.
            if old_area > 0 and (inter / old_area) >= min_cov:
                parents.append(tid)
                explained += inter
        survivor = matched.get(det_idx)
        if survivor:
            parents.append(survivor)
            explained += _inter(det_poly, unmatched_tracks.get(survivor)) if survivor in unmatched_tracks else 0.0
        parents = list(dict.fromkeys(parents))
        if len(parents) < 2:
            continue
        ratio = explained / max(new_area, 1e-6)
        if ratio < min_expl:
            continue   # die Parents erklaeren die neue Zelle nicht ausreichend
        out.append(TransitionCandidate(
            kind="merge", parents=parents, children=[det_idx],
            signature=transition_signature("merge", parents, [str(det_idx)]),
            explained=round(ratio, 4),
        ))
    return out


def find_split_candidates(unmatched_tracks: dict, detections: dict, matched: dict) -> list:
    """1:n — eine UNMATCHED alte Zelle überdeckt mehrere neue Zellen.

    Dieser Pfad war bisher strukturell unerreichbar (used_ids), obwohl P66
    nachweislich Sub-Zellen erzeugt. Ergebnis: 0 Splits in 724 Beobachtungen.
    """
    min_expl = float(_cfg("TRANSITION_SPLIT_MIN_EXPLAINED"))
    min_share = float(_cfg("TRANSITION_SPLIT_MIN_CHILD_SHARE"))
    out = []
    for tid, tpoly in (unmatched_tracks or {}).items():
        old_area = _safe_area(tpoly)
        if old_area <= 0:
            continue
        children, explained = [], 0.0
        for det_idx, det_poly in (detections or {}).items():
            inter = _inter(det_poly, tpoly)
            if old_area > 0 and (inter / old_area) >= min_share:
                children.append(det_idx)
                explained += inter
        if len(children) < 2:
            continue
        ratio = explained / max(old_area, 1e-6)
        if ratio < min_expl:
            continue
        out.append(TransitionCandidate(
            kind="split", parents=[tid], children=children,
            signature=transition_signature("split", [tid], [str(c) for c in children]),
            explained=round(ratio, 4),
        ))
    return out


def confirm_candidates(candidates: list, pending: dict) -> tuple:
    """Zustandsautomat: candidate -> confirmed nach N konsistenten Frames.

    `pending` ist der frameuebergreifende Speicher (Signatur -> frames_seen).
    Rueckgabe: (confirmed, still_candidate, reverted_signatures, neues pending)
    """
    need = int(_cfg("TRANSITION_CONFIRM_FRAMES"))
    seen_now = {c.signature for c in candidates}
    new_pending, confirmed, still = {}, [], []

    for c in candidates:
        c.frames_seen = int((pending or {}).get(c.signature, 0)) + 1
        if c.frames_seen >= need:
            c.phase = "confirmed"
            confirmed.append(c)
        else:
            c.phase = "candidate"
            still.append(c)
        new_pending[c.signature] = c.frames_seen

    reverted = [sig for sig in (pending or {}) if sig not in seen_now]
    return confirmed, still, reverted, new_pending
