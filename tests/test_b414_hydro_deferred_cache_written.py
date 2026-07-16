import json
import sys
import types

import hydro_fetch
import hydro_flood_ml


class _Response:
    status_code = 200
    headers = {"content-type": "application/json"}

    def __init__(self, q):
        self.q = q

    def json(self):
        return {"stations": [{"id": "A", "name": "A", "lat": 46.7, "lon": 14.0, "q": self.q}]}


def _prepare_fetch(tmp_path, monkeypatch, q):
    monkeypatch.setattr(hydro_fetch, "_LIVE_DIR", tmp_path)
    monkeypatch.setattr(hydro_fetch, "LATEST_FILE", tmp_path / "latest_hydro.json")
    monkeypatch.setattr(hydro_fetch, "STATUS_FILE", tmp_path / "hydro_status.json")
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_RISK_PATH", tmp_path / "latest_hydro_flood_risk.json")
    monkeypatch.setattr(hydro_flood_ml, "append_hydro_history", lambda live: 0)
    monkeypatch.setitem(sys.modules, "http_retry", types.SimpleNamespace(retry_get=lambda *a, **k: _Response(q)))
    monkeypatch.setitem(
        sys.modules,
        "debug_utils",
        types.SimpleNamespace(log_api_call=lambda *a, **k: None, log_api_failure=lambda *a, **k: None, debug_log=lambda *a, **k: None),
    )


def test_fetch_without_cell_frame_writes_fresh_public_deferred_cache(tmp_path, monkeypatch):
    _prepare_fetch(tmp_path, monkeypatch, q=7.25)
    risk_path = hydro_flood_ml.HYDRO_RISK_PATH
    risk_path.write_text(json.dumps({"stations": [{"station_id": "A", "current_q_m3s": 1.0}]}), encoding="utf-8")
    monkeypatch.setattr(hydro_flood_ml, "load_latest_cell_frame", lambda: (None, {"status": "missing"}))

    result = hydro_fetch.fetch_hydro_live(force=True)

    assert risk_path.exists()
    doc = json.loads(risk_path.read_text(encoding="utf-8"))
    assert result["stations"][0]["q_m3s"] == 7.25
    assert doc["stations"][0]["current_q_m3s"] == 7.25
    assert doc["forecast_evaluation_stale"] is True
    assert doc["payload_scope"] == "public"


def test_fetch_with_cell_frame_uses_regular_path_and_writes_cache(tmp_path, monkeypatch):
    _prepare_fetch(tmp_path, monkeypatch, q=8.5)
    risk_path = hydro_flood_ml.HYDRO_RISK_PATH
    monkeypatch.setattr(
        hydro_flood_ml,
        "load_latest_cell_frame",
        lambda: ([], {"status": "ok", "raw_cell_count": 0, "cell_count": 0}),
    )
    monkeypatch.setattr(hydro_flood_ml, "record_pending_samples", lambda *a, **k: {"pending_added": 0})
    monkeypatch.setattr(hydro_flood_ml, "materialize_pending_samples", lambda *a, **k: {"labeled_added": 0})
    monkeypatch.setitem(
        sys.modules,
        "hydro_api",
        types.SimpleNamespace(
            station_features=lambda include_disabled=False: {
                "features": [{"properties": {"station_id": "A", "mark_q_m3s": 10}}]
            }
        ),
    )

    hydro_fetch.fetch_hydro_live(force=True)

    assert risk_path.exists()
    doc = json.loads(risk_path.read_text(encoding="utf-8"))
    assert doc["stations"][0]["current_q_m3s"] == 8.5
