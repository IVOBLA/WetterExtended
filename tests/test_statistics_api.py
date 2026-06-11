# tests/test_statistics_api.py
"""P-S03: Tests für die Statistik-API-Endpunkte."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    pytest.importorskip("flask")
    import app as app_module
    stats_dir = tmp_path / "statistics"
    stats_dir.mkdir()
    paths = dict(app_module.SAVE_PATHS)
    paths["statistics"] = str(stats_dir)
    monkeypatch.setitem(app_module.SAVE_PATHS, "statistics", str(stats_dir))

    (stats_dir / "stats_2026.json").write_text(json.dumps({
        "year": 2026, "cells_total": 42, "by_month": [0]*12,
        "dominant_dir_deg": 247.0, "dir_consistency": 0.8,
    }), encoding="utf-8")
    (stats_dir / "climatology_grid.json").write_text(json.dumps({
        "grid_deg": 0.1, "min_samples": 5, "cells": {"46.60_13.80": {"6": {"n": 7, "reliable": True}}},
    }), encoding="utf-8")

    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def test_years_lists_available(client):
    r = client.get("/api/statistics/years")
    assert r.status_code == 200
    assert 2026 in r.get_json()["years"]


def test_year_returns_aggregate(client):
    r = client.get("/api/statistics/2026")
    assert r.status_code == 200
    data = r.get_json()
    assert data["available"] is True
    assert data["cells_total"] == 42
    assert data["dominant_dir_deg"] == 247.0


def test_year_missing_graceful(client):
    r = client.get("/api/statistics/1999")
    assert r.status_code == 200
    assert r.get_json()["available"] is False


def test_climatology_endpoint(client):
    r = client.get("/api/statistics/climatology")
    assert r.status_code == 200
    data = r.get_json()
    assert data["available"] is True
    assert "46.60_13.80" in data["cells"]


def test_statistics_is_public_get(client):
    """Statistik-GET darf NICHT auth-pflichtig sein (kein 401/403)."""
    for url in ("/api/statistics/years", "/api/statistics/2026", "/api/statistics/climatology"):
        assert client.get(url).status_code == 200
