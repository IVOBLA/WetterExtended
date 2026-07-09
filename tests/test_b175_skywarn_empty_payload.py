"""B175: build_success_snapshot degradiert sauber bei None/Nicht-Dict-Payload."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

skywarn = pytest.importorskip("skywarn_export_snapshot")


def test_none_payload_ist_ok_ohne_warnlage_b326():
    """B326: None-Payload = regulaerer Zustand 'keine Warnlage', kein Fehler."""
    snap = skywarn.build_success_snapshot(None)
    assert snap["status"] == "ok"
    assert snap["data_available"] is False
    assert snap["error"] is None
    assert snap["valid_from"] is None
    assert snap["valid_to"] is None
    assert snap["features_inside_kaernten_bbox"]["features"] == []


def test_non_dict_payload_ist_ok_ohne_warnlage_b326():
    """B326: Nicht-Dict-Payload = regulaerer Zustand 'keine Warnlage', kein Fehler."""
    snap = skywarn.build_success_snapshot([])
    assert snap["status"] == "ok"
    assert snap["data_available"] is False
    assert snap["error"] is None
    assert snap["valid_to"] is None


import json as _json


def test_todays_snapshot_status_ok(tmp_path):
    p = tmp_path / "snap.json"
    now = skywarn._now_vienna()
    p.write_text(_json.dumps({"status": "ok", "fetched_at": now.isoformat(timespec="seconds")}), encoding="utf-8")
    assert skywarn._todays_snapshot_status(p, now) == "ok"


def test_todays_snapshot_status_error(tmp_path):
    p = tmp_path / "snap.json"
    now = skywarn._now_vienna()
    p.write_text(_json.dumps({"status": "error", "fetched_at": now.isoformat(timespec="seconds")}), encoding="utf-8")
    assert skywarn._todays_snapshot_status(p, now) == "error"


def test_todays_snapshot_status_none_for_missing_file(tmp_path):
    p = tmp_path / "missing.json"
    now = skywarn._now_vienna()
    assert skywarn._todays_snapshot_status(p, now) is None


def test_no_warning_status_does_not_overwrite_valid_snapshot(monkeypatch, tmp_path):
    """B297/B326: Echte Warndaten werden nicht durch 'keine Warnlage' ueberschrieben."""
    snap_path = tmp_path / "skywarn_export.json"
    monkeypatch.setattr(skywarn, "_snapshot_path", lambda: snap_path)
    now = skywarn._now_vienna()
    valid_snapshot = skywarn.build_success_snapshot(
        {"polygon": {"features": []}, "start": "2026-07-03T10:00:00", "end": "2026-07-03T14:00:00"}, now
    )
    snap_path.write_text(_json.dumps(valid_snapshot), encoding="utf-8")

    class _FakeResponse:
        status = 200
        def read(self):
            return b"null"
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(skywarn.urllib.request, "urlopen", lambda *a, **k: _FakeResponse())

    result = skywarn.fetch_and_store_skywarn_export_snapshot(force=True)

    assert result["status"] == "ok"
    assert result["data_available"] is False
    persisted = _json.loads(snap_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "ok"
    assert persisted["data_available"] is True
    assert persisted["valid_from"] == "2026-07-03T10:00:00"


def test_error_snapshot_from_today_allows_retry(monkeypatch, tmp_path):
    """B297: Ein Fehlerstatus von heute blockiert keinen erneuten Versuch mehr."""
    snap_path = tmp_path / "skywarn_export.json"
    monkeypatch.setattr(skywarn, "_snapshot_path", lambda: snap_path)
    now = skywarn._now_vienna()
    error_snapshot = skywarn._error_snapshot("empty_payload", "leer", None, now)
    snap_path.write_text(_json.dumps(error_snapshot), encoding="utf-8")

    class _FakeResponse:
        status = 200
        def read(self):
            return b'{"polygon": {"features": []}, "start": "2026-07-04T08:00:00", "end": "2026-07-04T12:00:00"}'
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(skywarn.urllib.request, "urlopen", lambda *a, **k: _FakeResponse())

    result = skywarn.fetch_and_store_skywarn_export_snapshot(force=False)

    assert result["status"] == "ok"
