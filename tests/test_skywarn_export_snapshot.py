import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import zipfile

import pytest
import skywarn_export_snapshot as skywarn

try:
    from shapely.geometry import shape, box
except Exception as exc:
    pytest.skip(f"shapely geometry helpers unavailable: {exc}", allow_module_level=True)
from config import BBOX_KAERNTEN_EXTENDED
from debug_export import create_debug_export_zip
from scheduler import create_scheduler


def _poly(w, s, e, n):
    return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


def _feature(geom, severity=1, **props):
    p = {"severity": severity}
    p.update(props)
    return {"type": "Feature", "properties": p, "geometry": geom}


def _payload(features):
    return {
        "text": "<p>Gewitter <b>möglich</b><br>Zeile 2</p>",
        "start": "2026-06-14 12:00:00",
        "end": "2026-06-15 12:00:00",
        "name": "Forecaster Must Not Persist",
        "polygon": {"type": "FeatureCollection", "features": features},
    }


@pytest.fixture
def skywarn_tmp(monkeypatch, tmp_path):
    out = tmp_path / "train_data" / "external_responses" / "skywarn"
    monkeypatch.setattr(skywarn, "SKYWARN_EXPORT_DIR", str(out))
    return out


def test_parsing_properties_and_severity_values():
    b = BBOX_KAERNTEN_EXTENDED
    payload = _payload([
        _feature(_poly(b["west"] + 0.1, b["south"] + 0.1, b["west"] + 0.2, b["south"] + 0.2), 2, name="hidden", foo="bar"),
        _feature(_poly(b["west"] + 0.3, b["south"] + 0.1, b["west"] + 0.4, b["south"] + 0.2), 3, forecaster="hidden"),
    ])

    snapshot = skywarn.build_success_snapshot(payload, datetime(2026, 6, 14, 12, tzinfo=ZoneInfo("Europe/Vienna")))

    assert snapshot["status"] == "ok"
    assert snapshot["text"] == "Gewitter möglich Zeile 2"
    assert snapshot["valid_from"] == "2026-06-14 12:00:00"
    assert snapshot["valid_to"] == "2026-06-15 12:00:00"
    dumped = json.dumps(snapshot)
    assert "Forecaster" not in dumped
    assert "forecaster" not in dumped
    assert "foo" not in dumped
    for feature in snapshot["features_inside_kaernten_bbox"]["features"]:
        assert set(feature["properties"].keys()) == {"severity"}
    assert snapshot["severity_values_inside_kaernten_bbox"] == [2, 3]
    assert snapshot["max_severity_inside_kaernten_bbox"] == 3
    assert snapshot["kaernten_bbox_relevant"] is True


def test_bbox_clipping_inside_outside_partial_multipolygon_geometrycollection():
    b = BBOX_KAERNTEN_EXTENDED
    bbox_geom = box(b["west"], b["south"], b["east"], b["north"])
    inside = _feature(_poly(b["west"] + 0.1, b["south"] + 0.1, b["west"] + 0.2, b["south"] + 0.2), 1)
    outside = _feature(_poly(b["east"] + 1, b["north"] + 1, b["east"] + 2, b["north"] + 2), 2)
    partial = _feature(_poly(b["west"] - 1, b["south"] + 0.1, b["west"] + 0.2, b["south"] + 0.2), 3)
    multipolygon = _feature({"type": "MultiPolygon", "coordinates": [inside["geometry"]["coordinates"], outside["geometry"]["coordinates"]]}, 4)
    collection = _feature({"type": "GeometryCollection", "geometries": [inside["geometry"], outside["geometry"]]}, 5)

    assert len(skywarn.clip_feature_to_bbox(inside)) == 1
    assert skywarn.clip_feature_to_bbox(outside) == []
    partial_features = skywarn.clip_feature_to_bbox(partial)
    assert len(partial_features) == 1
    clipped_geom = shape(partial_features[0]["geometry"])
    assert bbox_geom.covers(clipped_geom)
    assert clipped_geom.bounds[0] >= b["west"]
    assert len(skywarn.clip_feature_to_bbox(multipolygon)) == 1
    assert len(skywarn.clip_feature_to_bbox(collection)) == 1
    assert skywarn.clip_feature_to_bbox({"type": "Feature", "properties": {}, "geometry": {"type": "GeometryCollection", "geometries": []}}) == []


def test_no_relevant_features_sets_bbox_relevant_false():
    b = BBOX_KAERNTEN_EXTENDED
    snapshot = skywarn.build_success_snapshot(_payload([_feature(_poly(b["east"] + 1, b["north"] + 1, b["east"] + 2, b["north"] + 2), 9)]))
    assert snapshot["features_inside_kaernten_bbox"]["features"] == []
    assert snapshot["severity_values_inside_kaernten_bbox"] == []
    assert snapshot["max_severity_inside_kaernten_bbox"] is None
    assert snapshot["kaernten_bbox_relevant"] is False


class _Response:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status = status_code
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def getcode(self):
        return self.status_code

    def read(self):
        if isinstance(self._payload, Exception):
            return b"{bad json"
        return json.dumps(self._payload).encode("utf-8")


def test_http_403_timeout_and_invalid_json_create_sanitized_error_snapshots(monkeypatch, skywarn_tmp):
    for func, expected in [
        (lambda *a, **k: _Response(403, {}), "http_error"),
        (lambda *a, **k: (_ for _ in ()).throw(TimeoutError("slow")), "timeout"),
        (lambda *a, **k: _Response(200, ValueError("bad json")), "json_parse_error"),
    ]:
        monkeypatch.setattr(skywarn.urllib.request, "urlopen", func)
        result = skywarn.fetch_and_store_skywarn_export_snapshot(force=True)
        assert result["status"] == "error"
        assert result["error"]["type"] == expected
        saved = (skywarn_tmp / "skywarn_export.json").read_text(encoding="utf-8")
        assert "Cookie" not in saved
        assert "Authorization" not in saved


def test_fresh_snapshot_skips_request_and_force_allows_manual_fetch(monkeypatch, skywarn_tmp):
    path = skywarn_tmp / "skywarn_export.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"fetched_at": datetime.now(ZoneInfo("Europe/Vienna")).isoformat(), "status": "ok"}), encoding="utf-8")

    calls = {"count": 0}
    class FakeUrlopenResponse:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def getcode(self):
            return 200
        def read(self):
            return json.dumps(_payload([])).encode("utf-8")

    def fake_urlopen(*args, **kwargs):
        calls["count"] += 1
        return FakeUrlopenResponse()
    monkeypatch.setattr(skywarn.urllib.request, "urlopen", fake_urlopen)

    assert skywarn.fetch_and_store_skywarn_export_snapshot(force=False)["status"] == "skipped_fresh"
    assert calls["count"] == 0
    assert skywarn.fetch_and_store_skywarn_export_snapshot(force=True)["status"] == "ok"
    assert calls["count"] == 1


def test_scheduler_contains_daily_skywarn_job():
    sched = create_scheduler()
    try:
        job = sched.get_job("skywarn_export_snapshot")
        assert job is not None
        assert job.max_instances == 1
        assert job.coalesce is True
        assert str(job.trigger.timezone) == "Europe/Vienna"
        fields = {field.name: str(field) for field in job.trigger.fields}
        assert fields["hour"] == "12"
        assert fields["minute"] == "0"
    finally:
        try:
            sched.shutdown(wait=False)
        except Exception:
            pass


def test_debug_export_includes_existing_skywarn_without_live_fetch(monkeypatch, tmp_path):
    base = tmp_path
    sky_dir = base / "train_data" / "external_responses" / "skywarn"
    sky_dir.mkdir(parents=True)
    (sky_dir / "skywarn_export.json").write_text('{"source":"skywarn.at"}', encoding="utf-8")

    def fail_live_fetch(*args, **kwargs):
        raise AssertionError("debug export must not fetch Skywarn live")
    monkeypatch.setattr(skywarn, "fetch_and_store_skywarn_export_snapshot", fail_live_fetch)

    zip_path, _filename, manifest = create_debug_export_zip(base_dir=base, tmp_path=base / "out.zip")
    assert "skywarn" in manifest["external_sources_detected"]
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert any(name.endswith("external_responses/skywarn/skywarn_export.json") for name in names)
