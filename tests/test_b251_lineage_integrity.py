"""B251 — Lineage-State-Integrität: F1 Timestamp-Order, F2 radar_confirmed,
F3 recycled cell_id, F4 ended-Flag."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cell_lineage as cl


# ─── Hilfsfunktionen ──────────────────────────────────────────────────────────

def _make_state(**cell_overrides):
    """Erstellt einen minimalen Lineage-State mit einer Zelle."""
    base = {
        "version": 1,
        "date_counters": {"20260625": 1},
        "ir_to_cell": {"ir_0": "WX-20260625-0001"},
        "radar_to_cell": {},
        "cells": {
            "WX-20260625-0001": {
                "cell_id": "WX-20260625-0001",
                "status": "ir_precursor",
                "first_seen_source": "ir108",
                "first_seen_timestamp": "2026-06-25_13-31-23",
                "last_seen_timestamp": "2026-06-25_13-31-23",
                "ir_track_id": "ir_0",
                "radar_track_id": None,
                "radar_confirmed": False,
                "ended": False,
                "aliases": [],
            }
        },
    }
    base["cells"]["WX-20260625-0001"].update(cell_overrides)
    return base


# ─── F1: last_seen vor first_seen wird repariert ──────────────────────────────

def test_normalize_state_repairs_reversed_timestamps():
    state = _make_state(
        first_seen_timestamp="2026-06-25_13-31-23",
        last_seen_timestamp="2026-06-18_00-15-00",  # 7 Tage davor!
    )
    repaired = cl._normalize_state(state)
    cell = repaired["cells"]["WX-20260625-0001"]
    assert cell["last_seen_timestamp"] == "2026-06-25_13-31-23", (
        "last_seen muss auf first_seen zurückgesetzt werden wenn es davor liegt"
    )


# ─── F2: radar_confirmed ohne radar_track_id wird repariert ──────────────────

def test_normalize_state_repairs_radar_confirmed_without_track():
    state = _make_state(
        status="radar_confirmed",
        radar_confirmed=True,
        radar_track_id=None,  # Inkonsistent!
    )
    repaired = cl._normalize_state(state)
    cell = repaired["cells"]["WX-20260625-0001"]
    assert cell["radar_confirmed"] is False, (
        "radar_confirmed=True ohne radar_track_id muss auf False repariert werden"
    )
    assert cell["status"] == "ir_precursor", (
        "status muss auf ir_precursor zurückgesetzt werden"
    )


def test_radar_confirmed_with_track_id_bleibt_erhalten():
    state = _make_state(
        status="radar_confirmed",
        radar_confirmed=True,
        radar_track_id="ABCDEF01",  # Gültig
    )
    repaired = cl._normalize_state(state)
    cell = repaired["cells"]["WX-20260625-0001"]
    assert cell["radar_confirmed"] is True
    assert cell["radar_track_id"] == "ABCDEF01"


# ─── F3: Abgelaufene cell_id wird nicht recycelt ─────────────────────────────

def test_ensure_ir_track_cell_id_keine_wiederverwendung_abgelaufener_id():
    """Wenn ir_to_cell auf eine ended-Zelle zeigt, muss eine neue ID vergeben werden."""
    state = {
        "version": 1,
        "date_counters": {"20260618": 1},
        "ir_to_cell": {"ir_0": "WX-20260618-0001"},
        "radar_to_cell": {},
        "cells": {
            "WX-20260618-0001": {
                "cell_id": "WX-20260618-0001",
                "status": "ir_precursor",
                "first_seen_source": "ir108",
                "first_seen_timestamp": "2026-06-18_00-00-00",
                "last_seen_timestamp": "2026-06-18_00-00-00",
                "ir_track_id": "ir_0",
                "radar_track_id": None,
                "radar_confirmed": False,
                # abgelaufen:
                "ended": False,  # bewusst False — soll auf True normalisiert werden
                "ended_at": "2026-06-25_15-25-00",
                "ended_without_radar": 1,
                "label_written": True,
                "negative_reason": "expired_without_radar",
                "aliases": [],
            }
        },
    }
    track = {"ir_id": "ir_0", "ir_track_id": "ir_0",
             "tiff_file": "ir108_20260625191500.tif",
             "observation_timestamp": "2026-06-25T19:15:00Z"}
    updated_track, updated_state = cl.ensure_ir_track_cell_id(
        track, timestamp="2026-06-25_19-15-00", state=state
    )
    new_cell_id = updated_track.get("cell_id")
    assert new_cell_id is not None, "Neue cell_id muss vergeben werden"
    assert new_cell_id != "WX-20260618-0001", (
        "Abgelaufene WX-20260618-0001 darf nicht wiederverwendet werden"
    )
    assert new_cell_id.startswith("WX-20260625-"), (
        f"Neue ID muss Datum 20260625 tragen, bekommen: {new_cell_id}"
    )
    # Altes Mapping muss entfernt worden sein
    assert updated_state["ir_to_cell"].get("ir_0") == new_cell_id, (
        "ir_to_cell muss auf neue ID zeigen"
    )


# ─── F4: ended=True bei Negativ-Label ────────────────────────────────────────

def test_normalize_state_setzt_ended_true_wenn_ended_at_gesetzt():
    state = _make_state(
        ended=False,  # Bug: ended=False obwohl ended_at gesetzt
        ended_at="2026-06-25_15-25-00",
        ended_without_radar=1,
        label_written=True,
        negative_reason="expired_without_radar",
    )
    repaired = cl._normalize_state(state)
    cell = repaired["cells"]["WX-20260625-0001"]
    assert cell["ended"] is True, (
        "ended muss True sein wenn ended_at gesetzt ist"
    )


def test_ended_bleibt_false_ohne_ended_at():
    state = _make_state(ended=False)
    repaired = cl._normalize_state(state)
    cell = repaired["cells"]["WX-20260625-0001"]
    assert cell["ended"] is False, "ended soll False bleiben wenn kein ended_at gesetzt"


# ─── Regressions-Test: gültiger State bleibt unverändert ──────────────────────

def test_normalize_state_korrekter_state_unveraendert():
    state = _make_state(
        first_seen_timestamp="2026-06-26_10-00-00",
        last_seen_timestamp="2026-06-26_10-15-00",
        radar_confirmed=False,
        radar_track_id=None,
        ended=False,
        ended_at=None,
    )
    repaired = cl._normalize_state(state)
    cell = repaired["cells"]["WX-20260625-0001"]
    assert cell["last_seen_timestamp"] == "2026-06-26_10-15-00"
    assert cell["radar_confirmed"] is False
    assert cell["ended"] is False
