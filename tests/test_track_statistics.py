# tests/test_track_statistics.py
"""P-S01: Tests für zirkuläre Richtungsmathematik und write_track_end."""

import json
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import track_statistics as ts


# ---------------------------------------------------------------------------
# circular_mean_deg
# ---------------------------------------------------------------------------

def test_circular_mean_wraparound_350_10():
    """PFLICHTFALL: 350° und 10° müssen zu 0° mitteln — niemals 180°."""
    mean, r = ts.circular_mean_deg([350.0, 10.0])
    assert mean is not None
    assert min(mean, 360.0 - mean) < 0.6, f"Erwartet ~0°, bekommen {mean}°"
    assert r > 0.9, f"Konsistenz muss hoch sein, bekommen {r}"


def test_circular_mean_simple():
    mean, r = ts.circular_mean_deg([80.0, 100.0])
    assert abs(mean - 90.0) < 0.6
    assert r > 0.9


def test_circular_mean_opposite_directions():
    """Entgegengesetzte Richtungen → Konsistenz ~0, Mittel None."""
    mean, r = ts.circular_mean_deg([0.0, 180.0])
    assert r < 0.01
    assert mean is None


def test_circular_mean_weighted():
    """Gewichtung: langes Segment dominiert."""
    mean, _ = ts.circular_mean_deg([0.0, 90.0], weights=[9.0, 1.0])
    assert mean < 15.0 or mean > 345.0, f"Erwartet nahe 0°, bekommen {mean}°"


def test_circular_mean_empty():
    mean, r = ts.circular_mean_deg([])
    assert mean is None and r == 0.0


def test_circular_mean_from_sums_consistent():
    angles = [350.0, 10.0, 5.0]
    s = sum(math.sin(math.radians(a)) for a in angles)
    c = sum(math.cos(math.radians(a)) for a in angles)
    mean, r = ts.circular_mean_from_sums(s, c, float(len(angles)))
    ref_mean, ref_r = ts.circular_mean_deg(angles)
    assert abs(((mean - ref_mean) + 180) % 360 - 180) < 0.2
    assert abs(r - ref_r) < 0.01


# ---------------------------------------------------------------------------
# bearing / haversine
# ---------------------------------------------------------------------------

def test_bearing_east():
    b = ts.bearing_deg(46.6, 14.0, 46.6, 14.3)
    assert abs(b - 90.0) < 2.0, f"Ostkurs erwartet, bekommen {b}°"


def test_bearing_north():
    b = ts.bearing_deg(46.6, 14.0, 46.9, 14.0)
    assert min(b, 360.0 - b) < 1.0, f"Nordkurs erwartet, bekommen {b}°"


def test_haversine_known_distance():
    # ~0.1° Breite ≈ 11.1 km
    d = ts.haversine_km(46.6, 14.0, 46.7, 14.0)
    assert 10.5 < d < 11.7, f"Erwartet ~11.1 km, bekommen {d}"


# ---------------------------------------------------------------------------
# write_track_end
# ---------------------------------------------------------------------------

@pytest.fixture()
def ends_file(tmp_path, monkeypatch):
    path = tmp_path / "track_ends.jsonl"
    monkeypatch.setattr(ts, "track_ends_path", lambda: str(path))
    return path


def _sample_obj():
    return {
        "id": "T001",
        "first_seen": "2026-06-11_14-00-00",
        "lat": 46.72, "lon": 14.31,
        "total_active_frames": 16,
        "history": [{"timestamp": "2026-06-11_15-15-00", "lat": 46.71, "lon": 14.29}],
        "dir_sum_sin": math.sin(math.radians(250.0)) * 10.0,
        "dir_sum_cos": math.cos(math.radians(250.0)) * 10.0,
        "dir_km_sum": 10.0,
        "seg_dirs_deg": [251.0, 249.0],
        "path_points": [[46.61, 13.85], [46.72, 14.31]],
        "path_length_km": 41.2,
        "speed_sum_kmh": 330.0, "speed_n": 10.0,
        "stationary_frames": 2,
        "max_core_ratio": 0.41,
        "max_severity_level": 2,
        "max_hail_cat": "klein",
        "max_hail_prob": 0.3,
        "max_lightning_10km": 14,
        "lineage": "new", "parents": [], "children": [],
    }


def test_write_track_end_record_fields(ends_file):
    ok = ts.write_track_end(_sample_obj(), "dissolved", "2026-06-11_15-20-00")
    assert ok is True
    rec = json.loads(ends_file.read_text(encoding="utf-8").strip())
    assert rec["id"] == "T001"
    assert rec["end_reason"] == "dissolved"
    assert rec["lifetime_min"] == 75.0
    assert abs(rec["mean_dir_deg"] - 250.0) < 0.5
    assert rec["dir_consistency"] == 1.0
    assert rec["mean_speed_kmh"] == 33.0
    assert rec["start_lat"] == 46.61 and rec["end_lat"] == 46.72
    assert rec["track_length_km"] == 41.2
    assert rec["max_severity_level"] == 2
    assert rec["max_hail_cat"] == "klein"


def test_write_track_end_idempotent(ends_file):
    obj = _sample_obj()
    assert ts.write_track_end(obj, "merged_into:X", "2026-06-11_15-20-00") is True
    assert ts.write_track_end(obj, "dissolved", "2026-06-11_15-25-00") is False
    lines = [l for l in ends_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1, "Pro Track darf nur 1 Datensatz geschrieben werden"


def test_write_track_end_minimal_obj(ends_file):
    """Objekt ohne Akkumulatoren (Altbestand) darf nicht crashen."""
    ok = ts.write_track_end(
        {"id": "T002", "first_seen": "2026-06-11_14-00-00", "lat": 46.6, "lon": 14.0},
        "dissolved", "2026-06-11_14-10-00",
    )
    assert ok is True
    rec = json.loads(ends_file.read_text(encoding="utf-8").strip())
    assert rec["mean_dir_deg"] is None
    assert rec["track_length_km"] == 0.0
