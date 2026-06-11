"""P-S02: Tests für Aggregator und Backfill."""

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
    eval_dir.mkdir()
    stats_dir.mkdir()
    paths = dict(config.SAVE_PATHS)
    paths["evaluation"] = str(eval_dir)
    paths["statistics"] = str(stats_dir)
    monkeypatch.setattr(config, "SAVE_PATHS", paths)
    import stats_aggregator
    import backfill_track_ends
    monkeypatch.setattr(stats_aggregator, "SAVE_PATHS", paths, raising=False)
    monkeypatch.setattr(backfill_track_ends, "SAVE_PATHS", paths, raising=False)
    return eval_dir, stats_dir


def _write_end(f, **kw):
    base = {
        "id": "X", "first_seen": "2026-06-11_14-00-00", "last_seen": "2026-06-11_15-00-00",
        "lifetime_min": 60.0, "total_active_frames": 12, "end_reason": "dissolved",
        "start_lat": 46.61, "start_lon": 13.85, "end_lat": 46.7, "end_lon": 14.2,
        "track_length_km": 30.0, "mean_dir_deg": 90.0, "dir_consistency": 0.9,
        "segment_dirs_deg": [], "path_points": [], "mean_speed_kmh": 30.0,
        "stationary_frames": 0, "max_core_ratio": 0.4, "max_severity_level": 2,
        "max_hail_cat": "keiner", "max_hail_prob": 0.1, "max_lightning_10km": 3,
        "lineage": "new", "parents": [], "children": [],
    }
    base.update(kw)
    f.write(json.dumps(base) + "\n")


def test_aggregate_counts_and_month(stats_env):
    eval_dir, stats_dir = stats_env
    import stats_aggregator
    with open(eval_dir / "track_ends.jsonl", "w", encoding="utf-8") as f:
        _write_end(f, id="A", first_seen="2026-06-11_14-00-00")
        _write_end(f, id="B", first_seen="2026-06-12_16-00-00")
        _write_end(f, id="C", first_seen="2026-07-01_15-00-00")
    res = stats_aggregator.aggregate(reset=True)
    assert res["processed"] == 3
    data = json.loads((stats_dir / "stats_2026.json").read_text(encoding="utf-8"))
    assert data["cells_total"] == 3
    assert data["by_month"][5] == 2   # Juni
    assert data["by_month"][6] == 1   # Juli


def test_aggregate_circular_direction(stats_env):
    """Jahresrichtung muss zirkulär gemittelt werden (350°+10° -> ~0°)."""
    eval_dir, stats_dir = stats_env
    import stats_aggregator
    with open(eval_dir / "track_ends.jsonl", "w", encoding="utf-8") as f:
        _write_end(f, id="A", mean_dir_deg=350.0, track_length_km=10.0)
        _write_end(f, id="B", mean_dir_deg=10.0, track_length_km=10.0)
    stats_aggregator.aggregate(reset=True)
    data = json.loads((stats_dir / "stats_2026.json").read_text(encoding="utf-8"))
    d = data["dominant_dir_deg"]
    assert min(d, 360.0 - d) < 1.0, f"Erwartet ~0°, bekommen {d}"


def test_aggregate_idempotent(stats_env):
    eval_dir, stats_dir = stats_env
    import stats_aggregator
    with open(eval_dir / "track_ends.jsonl", "w", encoding="utf-8") as f:
        _write_end(f, id="A")
    assert stats_aggregator.aggregate()["processed"] == 1
    # zweiter Lauf ohne neue Zeilen -> 0 neue
    assert stats_aggregator.aggregate()["processed"] == 0


def test_intensity_hail_priority(stats_env):
    eval_dir, stats_dir = stats_env
    import stats_aggregator
    with open(eval_dir / "track_ends.jsonl", "w", encoding="utf-8") as f:
        _write_end(f, id="A", max_severity_level=3, max_hail_cat="gross")  # -> Bucket 3
        _write_end(f, id="B", max_severity_level=1, max_hail_cat="keiner") # -> Bucket 0
    stats_aggregator.aggregate(reset=True)
    data = json.loads((stats_dir / "stats_2026.json").read_text(encoding="utf-8"))
    june = data["intensity_by_month"][5]
    assert june[3] == 1   # hagelverdächtig
    assert june[0] == 1   # schwach


def test_climatology_min_samples_flag(stats_env):
    eval_dir, stats_dir = stats_env
    import stats_aggregator
    with open(eval_dir / "track_ends.jsonl", "w", encoding="utf-8") as f:
        for i in range(3):
            _write_end(f, id=f"A{i}", start_lat=46.65, start_lon=13.85, mean_dir_deg=90.0)
    stats_aggregator.aggregate(reset=True)
    grid = json.loads((stats_dir / "climatology_grid.json").read_text(encoding="utf-8"))
    # 3 Samples < CLIM_MIN_SAMPLES(5) -> reliable=False
    any_cell = next(iter(grid["cells"].values()))
    any_month = next(iter(any_cell.values()))
    assert any_month["reliable"] is False
    assert any_month["n"] == 3


def test_backfill_reconstructs_tracks(stats_env):
    eval_dir, stats_dir = stats_env
    import backfill_track_ends
    with open(eval_dir / "cells_log.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-06-11_14-00-00", "count": 1,
                "cells": [{"id": "T1", "lat": 46.6, "lon": 14.0, "core_ratio": 0.2, "lineage": "new"}]}) + "\n")
        f.write(json.dumps({"ts": "2026-06-11_14-05-00", "count": 1,
                "cells": [{"id": "T1", "lat": 46.6, "lon": 14.1, "core_ratio": 0.3, "lineage": "tracked"}]}) + "\n")
    res = backfill_track_ends.backfill()
    assert res["tracks"] == 1
    lines = [l for l in (stats_dir / "track_ends_backfill.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    rec = json.loads(lines[0])
    assert rec["id"] == "T1"
    assert rec["lifetime_min"] == 5.0
    assert rec["mean_dir_deg"] is not None     # Ostbewegung
    assert rec["max_severity_level"] is None   # keine erfundenen Werte
