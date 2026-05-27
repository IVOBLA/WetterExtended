import json
from pathlib import Path

import pytest

import app as app_module
import runtime_config


@pytest.fixture()
def client(tmp_path, monkeypatch):
    eval_dir = tmp_path / "evaluation"
    obj_dir = tmp_path / "objects"
    lightning_dir = tmp_path / "lightning"
    eval_dir.mkdir()
    obj_dir.mkdir()
    lightning_dir.mkdir()

    monkeypatch.setitem(app_module.SAVE_PATHS, "evaluation", str(eval_dir))
    monkeypatch.setitem(app_module.SAVE_PATHS, "objects", str(obj_dir))
    monkeypatch.setitem(app_module.SAVE_PATHS, "lightning", str(lightning_dir))
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client(), eval_dir


def _write_atm(eval_dir: Path, locations):
    (eval_dir / "atmosphere_latest.json").write_text(
        json.dumps({"locations": locations}), encoding="utf-8"
    )


def test_risk_grid_atmosphere_only_returns_cells(client):
    c, eval_dir = client
    _write_atm(eval_dir, [
        {"name": "Klagenfurt", "lat": 46.6228, "lon": 14.3050, "li": -3.1, "potential": "hoch"},
        {"name": "Villach", "lat": 46.6103, "lon": 13.8558, "li": -3.1, "potential": "hoch"},
        {"name": "Wolfsberg", "lat": 46.8406, "lon": 14.8442, "li": -3.0, "potential": "mäßig"},
    ])

    resp = c.get("/api/risk_grid")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, dict)
    assert "cells" in data
    assert len(data["cells"]) > 0
    assert data["sources"]["atm_locations"] > 0
    assert any((cell.get("info") or {}).get("dominant") == "atm" for cell in data["cells"])

    coords = {(cell["lat"], cell["lon"]) for cell in data["cells"]}
    assert len(coords) > 3


def test_risk_grid_missing_atmosphere_file_returns_json(client):
    c, _ = client
    resp = c.get("/api/risk_grid")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["cells"] == []
    assert data["sources"]["atm_locations"] == 0


def test_risk_grid_robust_runtime_config_and_bad_data(client):
    c, eval_dir = client
    _write_atm(eval_dir, [
        {"name": "bad-no-coords", "li": -2.5},
        {"name": "bad-li-none", "lat": 46.7, "lon": 14.1, "li": None},
        {"name": "bad-li-nan", "lat": 46.9, "lon": 14.6, "li": "nan", "potential": "mäßig"},
        {"name": "good", "lat": 46.8, "lon": 14.3, "li": -3.2, "potential": "hoch"},
    ])

    runtime_config.patch({"RISK_FAST_CELL_KMH": "abc", "RISK_STATIONARY_BOOST": ""})
    try:
        resp = c.get("/api/risk_grid")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data.get("cells"), list)
    finally:
        runtime_config.patch({"RISK_FAST_CELL_KMH": 40.0, "RISK_STATIONARY_BOOST": 0.8})
