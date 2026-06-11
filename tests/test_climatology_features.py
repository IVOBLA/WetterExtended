# tests/test_climatology_features.py
"""P-S05: Tests für Zellalter + Klimatologie-Prior-Features."""

import json
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def clim_env(tmp_path, monkeypatch):
    import config
    stats_dir = tmp_path / "statistics"
    stats_dir.mkdir()
    paths = dict(config.SAVE_PATHS)
    paths["statistics"] = str(stats_dir)
    monkeypatch.setattr(config, "SAVE_PATHS", paths)
    import climatology_features as cf
    monkeypatch.setattr(cf, "SAVE_PATHS", paths, raising=False)
    # Cache leeren
    cf._CACHE.update(mtime=None, cells={}, max_n=0)
    return stats_dir, cf


def _write_grid(stats_dir, cells, grid_deg=0.1):
    (stats_dir / "climatology_grid.json").write_text(
        json.dumps({"grid_deg": grid_deg, "min_samples": 5, "cells": cells}),
        encoding="utf-8",
    )


def test_cell_age_min_from_first_seen(clim_env):
    _, cf = clim_env
    objs = [{"id": "A", "lat": 46.65, "lon": 13.85, "first_seen": "2026-06-11_14-00-00"}]
    cf.enrich_objects(objs, "2026-06-11_15-15-00")
    assert objs[0]["cell_age_min"] == 75.0


def test_reliable_cell_sets_clim_features(clim_env):
    stats_dir, cf = clim_env
    # Zelle key für lat 46.65/lon 13.85 bei grid 0.1: floor -> 46.60_13.80
    _write_grid(stats_dir, {
        "46.60_13.80": {"6": {
            "n": 10, "reliable": True,
            "dir_cos": round(math.cos(math.radians(247.0)), 4),
            "dir_sin": round(math.sin(math.radians(247.0)), 4),
            "mean_lifetime_min": 48.0,
        }}
    })
    objs = [{"id": "A", "lat": 46.65, "lon": 13.85, "first_seen": "2026-06-11_14-00-00"}]
    cf.enrich_objects(objs, "2026-06-11_15-00-00")
    o = objs[0]
    assert o["clim_cell_freq"] == 1.0          # n == max_n
    assert abs(o["clim_dir_cos"] - math.cos(math.radians(247.0))) < 1e-3
    assert o["clim_mean_lifetime_min"] == 48.0


def test_unreliable_cell_yields_zero(clim_env):
    stats_dir, cf = clim_env
    _write_grid(stats_dir, {
        "46.60_13.80": {"6": {"n": 3, "reliable": False,
                              "dir_cos": 0.5, "dir_sin": 0.5, "mean_lifetime_min": 40.0}}
    })
    objs = [{"id": "A", "lat": 46.65, "lon": 13.85, "first_seen": "2026-06-11_14-00-00"}]
    cf.enrich_objects(objs, "2026-06-11_15-00-00")
    o = objs[0]
    assert o["clim_cell_freq"] == 0.0
    assert o["clim_dir_cos"] == 0.0
    assert o["clim_mean_lifetime_min"] == 0.0
    assert o["cell_age_min"] == 60.0           # Alter trotzdem gesetzt


def test_missing_grid_file_graceful(clim_env):
    _, cf = clim_env  # kein Grid geschrieben
    objs = [{"id": "A", "lat": 46.65, "lon": 13.85, "first_seen": "2026-06-11_14-00-00"}]
    cf.enrich_objects(objs, "2026-06-11_15-00-00")
    o = objs[0]
    assert o["cell_age_min"] == 60.0
    assert all(o[k] == 0.0 for k in cf._CLIM_KEYS)


def test_disabled_toggle_zeros_clim(clim_env, monkeypatch):
    stats_dir, cf = clim_env
    import config
    monkeypatch.setattr(config, "CLIM_FEATURES_ENABLED", False)
    monkeypatch.setattr(cf, "CLIM_FEATURES_ENABLED", False, raising=False)
    _write_grid(stats_dir, {"46.60_13.80": {"6": {"n": 10, "reliable": True,
                            "dir_cos": 0.5, "dir_sin": 0.5, "mean_lifetime_min": 50.0}}})
    objs = [{"id": "A", "lat": 46.65, "lon": 13.85, "first_seen": "2026-06-11_14-00-00"}]
    cf.enrich_objects(objs, "2026-06-11_15-00-00")
    assert objs[0]["clim_cell_freq"] == 0.0


def test_ml_num_features_includes_new(clim_env):
    """Die 5 neuen Features müssen in ML_CELL_FEATURES stehen und ML_NUM_FEATURES erhöhen."""
    import importlib, config
    importlib.reload(config)
    for k in ("cell_age_min", "clim_cell_freq", "clim_dir_cos", "clim_dir_sin", "clim_mean_lifetime_min"):
        assert k in config.ML_CELL_FEATURES, f"{k} fehlt in ML_CELL_FEATURES"
    expected = len(config.ML_CELL_FEATURES) + len(config.ML_STATION_FEATURES) + len(config.ML_TIME_FEATURES)
    assert config.ML_NUM_FEATURES == expected
