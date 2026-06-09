import json
from datetime import datetime, timezone

import pytest

import app as app_module


def _ns(dt: datetime) -> int:
    return int(dt.timestamp() * 1_000_000_000)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    lightning_dir = tmp_path / "lightning"
    lightning_dir.mkdir()
    monkeypatch.setitem(app_module.SAVE_PATHS, "lightning", str(lightning_dir))
    monkeypatch.chdir(tmp_path)
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client(), lightning_dir, tmp_path


def test_lightning_uses_latest_file_and_vienna_radar_reference_for_utc_strikes(client):
    c, lightning_dir, tmp_path = client
    radar_dir = tmp_path / "data" / "radar"
    radar_dir.mkdir(parents=True)
    (radar_dir / "radar_2026-06-09_14-00-00.png").write_bytes(b"")

    recent_utc = datetime(2026, 6, 9, 11, 45, tzinfo=timezone.utc)
    old_utc = datetime(2026, 6, 9, 11, 20, tzinfo=timezone.utc)
    (lightning_dir / "latest_lightning.json").write_text(
        json.dumps([
            {"timestamp_ns": _ns(recent_utc), "timestamp": "recent", "lat": 46.7, "lon": 14.3, "pol": -1},
            {"timestamp_ns": _ns(old_utc), "timestamp": "old", "lat": 46.8, "lon": 14.4, "pol": 1},
        ]),
        encoding="utf-8",
    )

    resp = c.get("/api/lightning?max_age_min=30")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] == 1
    assert data["total_in_file"] == 2
    assert data["strikes"][0]["timestamp"] == "recent"


def test_lightning_missing_cache_returns_empty_list(client):
    c, _lightning_dir, _tmp_path = client

    resp = c.get("/api/lightning?max_age_min=30")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["strikes"] == []
    assert data["count"] == 0
    assert data["max_age_min"] == 30
