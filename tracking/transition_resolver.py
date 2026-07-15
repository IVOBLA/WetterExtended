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
from typing import Any

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
    # B393: Quantisierung der parent-lokalen Split-Geometrie.
    # Positionswerte sind auf 0..1 normalisiert.
    "TRANSITION_SPLIT_SIGNATURE_POS_BIN": 0.10,
    # Relative Parent-Flaechenanteile in 5-Prozent-Schritten.
    "TRANSITION_SPLIT_SIGNATURE_SHARE_BIN": 0.05,
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
    """Zeitstempelfreie UND framestabile Identitaet eines Uebergangs (analog B371).

    B388: `children` darf KEINE Detektionsindizes mehr enthalten.

    Ein Detektionsindex ist die Position in der Rueckgabeliste von cv2.findContours()
    und gilt nur INNERHALB eines Frames. Erscheint, verschwindet oder verschiebt sich
    eine unbeteiligte Kontur, verschieben sich alle nachfolgenden Indizes. Da
    confirm_candidates() den Bestaetigungszaehler ueber die Signatur fuehrt, fiel ein
    Kandidat bei unveraenderter Geometrie auf frames_seen=1 zurueck und wurde NIE
    bestaetigt -- waehrend die alte Signatur gleichzeitig als `reverted` galt.

    Besonders tueckisch: Bei einem Merge aendert sich die Konturanzahl per Definition
    (2 Zellen -> 1 Kontur), die Indizes verschieben sich also im Bestaetigungsframe
    regelmaessig. B370 hat die GRUPPIERUNG reihenfolgeinvariant gemacht, nicht die
    INDIZIERUNG.

    Aufrufer verwenden stattdessen:
      - Merge: _stable_merge_key(parents)      -- Kindmenge implizit (eine Zelle)
      - Split: _stable_child_key(parent_poly, child_polys) -- sortierte und
        quantisierte parent-lokale Kindgeometrie aus relativem Schwerpunkt und
        Parent-Flaechenanteil.
    """
    payload = "|".join([
        str(kind),
        ",".join(sorted(str(p) for p in (parents or []) if p)),
        ",".join(sorted(str(c) for c in (children or []) if c)),
    ])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _stable_merge_key(parents: list) -> list:
    """B388: Kindschluessel eines Merges — bewusst leer.

    Dieselben Parents verschmelzen zu genau EINER Zelle; der Detektionsindex dieser
    Zelle traegt keine zusaetzliche Information, ist aber frameweise instabil.
    """
    return []


def _poly_bounds(poly) -> tuple[float, float, float, float] | None:
    if poly is None:
        return None
    try:
        values = tuple(float(v) for v in poly.bounds)
        if len(values) == 4:
            return values
    except Exception:
        pass
    try:
        return (
            float(poly.x1),
            float(poly.y1),
            float(poly.x2),
            float(poly.y2),
        )
    except Exception:
        return None


def _poly_centroid_xy(poly) -> tuple[float, float] | None:
    if poly is None:
        return None
    try:
        centroid = poly.centroid
        return float(centroid.x), float(centroid.y)
    except Exception:
        bounds = _poly_bounds(poly)
        if bounds is None:
            return None
        x1, y1, x2, y2 = bounds
        return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def _quantized_bin(value: float, step: float) -> int:
    return int(round(float(value) / max(float(step), 1e-6)))


def _stable_child_key(parent_poly, child_polys: list) -> list[str]:
    """B393: indexfreie, parent-lokale Geometrie eines Split-Kandidaten.

    Pro Kind:
      - normierter Schwerpunkt der Parent-Kind-Schnittflaeche,
      - erklaerter Anteil der Parentflaeche.

    Die sortierten und quantisierten Deskriptoren sind unabhaengig von
    Detektionsindex, Kindreihenfolge, gemeinsamer Translation und Skalierung.
    """
    children = [poly for poly in (child_polys or []) if poly is not None]
    parent_bounds = _poly_bounds(parent_poly)
    parent_area = _safe_area(parent_poly)

    if parent_bounds is None or parent_area <= 0.0:
        return [f"n={len(children)}", "geometry=unavailable"]

    px1, py1, px2, py2 = parent_bounds
    width = max(px2 - px1, 1e-6)
    height = max(py2 - py1, 1e-6)
    pos_bin = float(_cfg("TRANSITION_SPLIT_SIGNATURE_POS_BIN"))
    share_bin = float(_cfg("TRANSITION_SPLIT_SIGNATURE_SHARE_BIN"))

    descriptors: list[str] = []
    for child_poly in children:
        try:
            piece = parent_poly.intersection(child_poly)
        except Exception:
            piece = child_poly

        piece_area = _safe_area(piece)
        centroid = _poly_centroid_xy(piece)
        if piece_area <= 0.0 or centroid is None:
            continue

        cx, cy = centroid
        rel_x = min(max((cx - px1) / width, 0.0), 1.0)
        rel_y = min(max((cy - py1) / height, 0.0), 1.0)
        share = min(max(piece_area / parent_area, 0.0), 1.0)

        descriptors.append(
            "x={}:y={}:s={}".format(
                _quantized_bin(rel_x, pos_bin),
                _quantized_bin(rel_y, pos_bin),
                _quantized_bin(share, share_bin),
            )
        )

    descriptors.sort()
    return [f"n={len(children)}", *descriptors]

@dataclass
class TransitionCandidate:
    kind: str                      # "merge" | "split"
    parents: list = field(default_factory=list)
    children: list = field(default_factory=list)
    signature: str = ""
    explained: float = 0.0
    frames_seen: int = 1
    phase: str = "candidate"
    # B381: Detektionsindex des primaeren Kindes (fuehrt die Parent-ID fort).
    primary_child: Any = None


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


def _explained_union_ratio(det_poly, parent_polys: list) -> float:
    """B387: Anteil der neuen Kontur, den die Parents GEMEINSAM erklaeren.

    Vorher wurden die Einzelschnittflaechen ADDIERT. Ueberlappen sich zwei
    Parent-Polygone -- bei konvergierenden Zellen kurz vor der Fusion der
    Normalfall, also genau die Situation, in der ein Merge erkannt werden soll --
    wurde der gemeinsame Bereich mehrfach gezaehlt. `explained` konnte dadurch
    ueber 1.0 steigen und einen Merge bestaetigen, den die Parents nicht erklaeren.

    Die geometrische Vereinigung zaehlt jeden Bereich genau einmal; das Ergebnis
    liegt per Konstruktion in [0, 1].
    """
    new_area = _safe_area(det_poly)
    if new_area <= 0:
        return 0.0
    pieces = []
    for poly in parent_polys:
        if poly is None:
            continue
        try:
            piece = det_poly.intersection(poly)
        except Exception:
            continue
        if piece is not None and not getattr(piece, "is_empty", False) and piece.area > 0:
            pieces.append(piece)
    if not pieces:
        return 0.0
    try:
        from shapely.ops import unary_union
        union_area = float(unary_union(pieces).area)
    except Exception:
        # Ohne Vereinigung waere die Summe eine Ueberschaetzung. Deckeln statt
        # falsch bestaetigen -- die Mindestabdeckung je Parent bleibt wirksam.
        union_area = min(sum(float(p.area) for p in pieces), new_area)
    return max(0.0, min(1.0, union_area / new_area))


def find_merge_candidates(all_tracks: dict, detections: dict, matched: dict) -> list:
    """n:1 — mehrere alte Zellen überdecken dieselbe neue Zelle.

    B387: Der Parameter heisst `all_tracks`, nicht `unmatched_tracks`. Vorher
    erhielt die Funktion ausschliesslich ungematchte Tracks; der Survivor
    (`matched.get(det_idx)`) wurde zwar der Parent-Liste hinzugefuegt, sein
    Flaechenbeitrag aber mit 0.0 gezaehlt, weil `survivor in unmatched_tracks`
    per Definition falsch war. Der Survivor ist typischerweise der GROESSTE
    Beitragende -- er dominiert den Merge und fuehrt die ID fort.

    Beispiel: Survivor erklaert 70 %, Secondary 25 % -> gezaehlt wurden 25 %,
    und der Merge fiel an TRANSITION_MERGE_MIN_EXPLAINED=0.50 durch, obwohl die
    Parents 95 % erklaerten. Echte Merges wurden dadurch systematisch verworfen.

    all_tracks:  track_id -> Polygon (ALLE alten Tracks, gematcht wie ungematcht)
    detections:  det_index -> Polygon
    matched:     det_index -> track_id (Ergebnis des globalen Matchings)
    """
    min_cov = float(_cfg("TRANSITION_MERGE_MIN_PARENT_COVERAGE"))
    min_expl = float(_cfg("TRANSITION_MERGE_MIN_EXPLAINED"))
    matched_track_ids = set((matched or {}).values())
    out = []
    for det_idx, det_poly in (detections or {}).items():
        new_area = _safe_area(det_poly)
        if new_area <= 0:
            continue
        survivor = (matched or {}).get(det_idx)
        parents, parent_polys = [], []
        for tid, tpoly in (all_tracks or {}).items():
            old_area = _safe_area(tpoly)
            if old_area <= 0:
                continue
            # Ein Track, der 1:1 einer ANDEREN Detektion zugeordnet wurde, lebt
            # eigenstaendig weiter und ist kein Merge-Parent.
            if tid != survivor and tid in matched_track_ids:
                continue
            inter = _inter(det_poly, tpoly)
            # Jeder Parent muss einen RELEVANTEN Anteil seiner eigenen alten
            # Flaeche beitragen. Der alte 0.30-Fallback liess kleine Randtracks
            # zu Merge-Parents werden, obwohl sie nichts erklaerten. Der Survivor
            # ist per globalem Match qualifiziert und umgeht diese Schranke.
            if tid == survivor or (inter / old_area) >= min_cov:
                parents.append(tid)
                parent_polys.append(tpoly)
        parents = list(dict.fromkeys(parents))
        if len(parents) < 2:
            continue
        # B387: geometrische Vereinigung statt Summe der Einzelschnitte.
        ratio = _explained_union_ratio(det_poly, parent_polys)
        if ratio < min_expl:
            continue   # die Parents erklaeren die neue Zelle nicht ausreichend
        out.append(TransitionCandidate(
            kind="merge", parents=parents, children=[det_idx],
            # B388: KEIN Detektionsindex in der Signatur -- er ist frameweise
            # instabil und liess die Bestaetigung auf frames_seen=1 zurueckfallen.
            # `children` bleibt fuer die Objektschleife erhalten, geht aber nicht
            # in die Identitaet ein.
            signature=transition_signature("merge", parents, _stable_merge_key(parents)),
            explained=round(ratio, 4),
        ))
    return out


def find_split_candidates(all_tracks: dict, detections: dict, matched: dict) -> list:
    """1:n — eine alte Zelle überdeckt mehrere neue Zellen.

    B381: Der Parameter heisst bewusst `all_tracks`, nicht `unmatched_tracks`.
    Bei einem normalen Split A -> X + Y ordnet Hungarian A korrekterweise 1:1
    einem der Kinder zu (z. B. X). A ist damit MATCHED. Wurden hier nur unmatched
    Tracks uebergeben, sah der Resolver genau den Fall nicht, fuer den er gebaut
    wurde -- den Split, bei dem das primaere Kind die Parent-ID fortfuehrt.
    Ergebnis: weiterhin 0 Splits, obwohl die Segmentierung Sub-Zellen erzeugt.

    Das globale 1:1-Match ist kein Ausschlusskriterium, sondern die Information,
    WELCHES Kind das primaere ist (AINT: das am besten passende Kind behaelt die UID).
    """
    min_expl = float(_cfg("TRANSITION_SPLIT_MIN_EXPLAINED"))
    min_share = float(_cfg("TRANSITION_SPLIT_MIN_CHILD_SHARE"))
    out = []
    for tid, tpoly in (all_tracks or {}).items():
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
        # B381: Das primaere Kind ist das global 1:1 gematchte. Es fuehrt die
        # Parent-ID fort; alle weiteren Kinder erhalten neue IDs.
        _primary_child = next((c for c in children if matched.get(c) == tid), None)
        if _primary_child is None:
            # Kein Kind wurde dem Parent zugeordnet (z. B. weil alle Paare gegatet
            # wurden). Dann ist das flaechengroesste Kind das primaere.
            _primary_child = max(children, key=lambda c: _safe_area(detections.get(c)))
        _child_polys = [
            detections.get(child_idx)
            for child_idx in children
            if detections.get(child_idx) is not None
        ]
        out.append(TransitionCandidate(
            kind="split", parents=[tid], children=children,
            # B393: Parent-ID plus quantisierte parent-lokale Kindgeometrie.
            # Keine Detektionsindizes, keine absolute Position und keine
            # Abhaengigkeit von der Kindreihenfolge.
            signature=transition_signature(
                "split",
                [tid],
                _stable_child_key(tpoly, _child_polys),
            ),
            explained=round(ratio, 4),
            primary_child=_primary_child,
        ))
    return out


def _pending_entry(raw) -> dict:
    """B396: liest den Pending-State abwaerts-kompatibel.

    Vor B396 war der Wert eine blanke Zahl (frames_seen). Nach einem Deployment
    ohne Neustart koennen beide Formen im Speicher liegen.
    """
    if isinstance(raw, dict):
        return {"frames_seen": int(raw.get("frames_seen", 0) or 0),
                "phase": str(raw.get("phase") or "candidate")}
    return {"frames_seen": int(raw or 0), "phase": "candidate"}


def confirm_candidates(candidates: list, pending: dict) -> tuple:
    """Zustandsautomat: candidate -> confirmed -> closed, oder -> reverted.

    B396: `confirmed` wird GENAU EINMAL ausgegeben -- beim Uebergang von
    `candidate`. Danach ist der Uebergang `closed`.

    Vorher schrieb die Funktion jede Signatur zurueck in new_pending, auch die
    bereits bestaetigten. frames_seen wuchs unbegrenzt weiter und blieb >= need,
    sodass derselbe Uebergang in JEDEM Folgeframe erneut als `confirmed` gemeldet
    wurde -- ein Zustand, der als EREIGNIS gemeint war. Das ist strukturell
    derselbe Defekt, den B371 auf der Fachschicht behoben hat, nur eine Ebene
    tiefer: B371 dedupliziert den Ledger, die Transition-Logik meldete weiter.

    `closed` heisst: die Konstellation besteht geometrisch fort, aber das Ereignis
    ist abgeschlossen. Die Objektschleife prueft `phase == "confirmed"` und setzt
    lineage="merged" damit automatisch nur noch im Ereignisframe.

    `pending` ist der frameuebergreifende Speicher
    (Signatur -> {"frames_seen": int, "phase": str}).
    Rueckgabe: (confirmed, still_candidate, reverted_signatures, neues pending)
    """
    need = int(_cfg("TRANSITION_CONFIRM_FRAMES"))
    seen_now = {c.signature for c in candidates}
    new_pending, confirmed, still = {}, [], []

    for c in candidates:
        prev = _pending_entry((pending or {}).get(c.signature))
        c.frames_seen = prev["frames_seen"] + 1

        if prev["phase"] in ("confirmed", "closed"):
            # Bereits bestaetigt -> das Ereignis ist abgeschlossen. Die Geometrie
            # zeigt den Verbund weiterhin, aber es ist kein neues Ereignis mehr.
            c.phase = "closed"
        elif c.frames_seen >= need:
            c.phase = "confirmed"
            confirmed.append(c)
        else:
            c.phase = "candidate"
            still.append(c)

        new_pending[c.signature] = {"frames_seen": c.frames_seen, "phase": c.phase}

    reverted = [sig for sig in (pending or {}) if sig not in seen_now]
    return confirmed, still, reverted, new_pending
