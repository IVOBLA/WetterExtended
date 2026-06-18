import json
import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pytest.importorskip("flask")
    import app as app_module
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def test_motion_pipeline_health_endpoint(client, tmp_path):
    eval_dir = tmp_path / "train_data" / "evaluation"
    eval_dir.mkdir(parents=True, exist_ok=True)
    (eval_dir / "motion_pipeline_health.json").write_text(json.dumps({"of_available_pct": 12.5}), encoding="utf-8")
    r = client.get('/api/motion_pipeline_health')
    assert r.status_code == 200
    assert r.get_json()["of_available_pct"] == 12.5


def test_motion_pipeline_health_endpoint_missing(client):
    r = client.get('/api/motion_pipeline_health')
    assert r.status_code == 200
    assert r.get_json()["status"] in {"missing", "ok"}
