"""P-S06: mean_lifetime_by_intensity korrekt aggregiert."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def stats_env(tmp_path, monkeypatch):
    import config
    eval_dir = tmp_path / "evaluation"
    stats_dir = tmp_path / "statistics"
    eval_dir.mkdir(); stats_dir.mkdir()
    paths = dict(config.SAVE_PATHS)
    paths["evaluation"] = str(eval_dir)
    paths["statistics"] = str(stats_dir)
    monkeypatch.setattr(config, "SAVE_PATHS", paths)
    import stats_aggregator
    monkeypatch.setattr(stats_aggregator, "SAVE_PATHS", paths, raising=False)
    return eval_dir, stats_dir


def _end(f, **kw):
    base = {
        "id": "X", "first_seen": "2026-06-11_14-00-00", "last_seen": "2026-06-11_15-00-00",
        "lifetime_min": 60.0, "total_active_frames": 12, "end_reason": "dissolved",
        "start_lat": 46.61, "start_lon": 13.85, "end_lat": 46.7, "end_lon": 14.2,
        "track_length_km": 30.0, "mean_dir_deg": 90.0, "dir_consistency": 0.9,
        "segment_dirs_deg": [], "path_points": [], "mean_speed_kmh": 30.0,
        "stationary_frames": 0, "max_core_ratio": 0.4, "max_severity_level": 1,
        "max_hail_cat": "keiner", "max_hail_prob": 0.1, "max_lightning_10km": 3,
        "lineage": "new", "parents": [], "children": [],
    }
    base.update(kw)
    f.write(json.dumps(base) + "\n")


def test_mean_lifetime_by_intensity(stats_env):
    eval_dir, stats_dir = stats_env
    import stats_aggregator
    with open(eval_dir / "track_ends.jsonl", "w", encoding="utf-8") as f:
        # zwei schwache (Index 0): 40 + 60 -> Mittel 50
        _end(f, id="A", lifetime_min=40.0, max_severity_level=1, max_hail_cat="keiner")
        _end(f, id="B", lifetime_min=60.0, max_severity_level=1, max_hail_cat="keiner")
        # eine starke (Index 2): 120
        _end(f, id="C", lifetime_min=120.0, max_severity_level=3, max_hail_cat="keiner")
        # eine hagelverdächtige (Index 3): 90
        _end(f, id="D", lifetime_min=90.0, max_severity_level=3, max_hail_cat="gross")
    stats_aggregator.aggregate(reset=True)
    data = json.loads((stats_dir / "stats_2026.json").read_text(encoding="utf-8"))
    mli = data["mean_lifetime_by_intensity"]
    assert mli[0] == 50.0   # schwach
    assert mli[1] is None   # mittel: keine Samples
    assert mli[2] == 120.0  # stark
    assert mli[3] == 90.0   # hagelverdächtig


def test_existing_state_migration(stats_env):
    """Aggregator darf auf altem State (ohne lifetime_by_intensity) nicht crashen."""
    eval_dir, stats_dir = stats_env
    import stats_aggregator
    # Alten State ohne den neuen Key simulieren
    old_state = {"offset": 0, "seen_ids": [], "grid": {},
                 "years": {"2026": {
                     "cells_total": 1, "by_month": [0]*12, "by_day": {}, "by_hour": [0]*24,
                     "intensity_by_month": [[0,0,0,0] for _ in range(12)],
                     "dir_sum_sin": 0.0, "dir_sum_cos": 0.0, "dir_w_sum": 0.0,
                     "dir_rose16": [0]*16, "lifetime_bins": [0]*9,
                     "lifetime_sum": 0.0, "lifetime_n": 0,
                     "speed_bins": [0]*8, "speed_sum": 0.0, "speed_n": 0,
                     "merges": 0, "splits": 0, "stationary_tracks": 0,
                 }}}
    (stats_dir / "_aggregate_state.json").write_text(json.dumps(old_state), encoding="utf-8")
    with open(eval_dir / "track_ends.jsonl", "w", encoding="utf-8") as f:
        _end(f, id="A", lifetime_min=30.0, max_severity_level=1)
    # darf nicht crashen (setdefault-Migration)
    res = stats_aggregator.aggregate()
    assert res["processed"] == 1
    data = json.loads((stats_dir / "stats_2026.json").read_text(encoding="utf-8"))
    assert "mean_lifetime_by_intensity" in data
