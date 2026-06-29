"""B256 — api_call_counts.jsonl: body_json/body_text werden bei Überschreitung
von LOG_API_RESPONSE_MAX_CHARS gekürzt; truncated=True gesetzt."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _import_debug_utils(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    import config as _cfg
    monkeypatch.setattr(_cfg, "LOG_API_RESPONSE_MAX_CHARS", 100, raising=False)
    monkeypatch.setattr(_cfg, "SAVE_PATHS", {"evaluation": str(tmp_path)}, raising=True)
    import debug_utils as du
    monkeypatch.setattr(du, "SAVE_PATHS", {"evaluation": str(tmp_path)}, raising=False)
    return du


def test_small_body_not_truncated(monkeypatch, tmp_path):
    du = _import_debug_utils(monkeypatch, tmp_path)
    du.log_api_call(
        service="test_svc",
        url="http://example.com/api",
        status_code=200,
        response_payload={"ok": True},
        content_type="application/json",
    )
    log_path = tmp_path / "api_call_counts.jsonl"
    assert log_path.exists()
    entry = json.loads(log_path.read_text().strip())
    resp = entry["response"]
    assert resp["truncated"] is False
    assert resp["body_json"] == {"ok": True}


def test_large_json_body_truncated(monkeypatch, tmp_path):
    du = _import_debug_utils(monkeypatch, tmp_path)
    # body > 100 chars → muss gekürzt werden
    big_body = [{"feature": i, "coords": [1.23456789, 46.7654321]} for i in range(50)]
    du.log_api_call(
        service="geosphere_cape",
        url="http://example.com/cape",
        status_code=200,
        response_payload={"type": "FeatureCollection", "features": big_body},
        content_type="application/json",
    )
    log_path = tmp_path / "api_call_counts.jsonl"
    entry = json.loads(log_path.read_text().strip())
    resp = entry["response"]
    assert resp["truncated"] is True
    # body_json ist jetzt ein String (gekürzte JSON-Serialisierung)
    assert len(resp["body_json"]) <= 100


def test_large_text_body_truncated(monkeypatch, tmp_path):
    du = _import_debug_utils(monkeypatch, tmp_path)
    big_text = "X" * 500
    du.log_api_call(
        service="eumetview_capabilities",
        url="http://example.com/wms",
        status_code=200,
        response_text=big_text,
        content_type="text/xml",
    )
    log_path = tmp_path / "api_call_counts.jsonl"
    entry = json.loads(log_path.read_text().strip())
    resp = entry["response"]
    assert resp["truncated"] is True
    assert len(resp["body_text"]) <= 100


def test_binary_body_never_truncated(monkeypatch, tmp_path):
    du = _import_debug_utils(monkeypatch, tmp_path)
    du.log_api_call(
        service="arso_radar",
        url="http://meteo.arso.gov.si/kmz",
        status_code=200,
        content_type="application/vnd.google-earth.kmz",
        content_length=50000,
        sha256="abc123",
    )
    log_path = tmp_path / "api_call_counts.jsonl"
    entry = json.loads(log_path.read_text().strip())
    resp = entry["response"]
    assert resp["truncated"] is False
    assert resp["binary"] is True


def test_zero_max_chars_disables_truncation(monkeypatch, tmp_path):
    du = _import_debug_utils(monkeypatch, tmp_path)
    import config as _cfg
    monkeypatch.setattr(_cfg, "LOG_API_RESPONSE_MAX_CHARS", 0)
    big_body = {"features": list(range(1000))}
    du.log_api_call(
        service="test_svc",
        url="http://example.com",
        status_code=200,
        response_payload=big_body,
        content_type="application/json",
    )
    log_path = tmp_path / "api_call_counts.jsonl"
    entry = json.loads(log_path.read_text().strip())
    assert entry["response"]["truncated"] is False
    assert entry["response"]["body_json"] == big_body
