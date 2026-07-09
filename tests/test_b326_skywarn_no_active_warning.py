"""B326: skywarn.at liefert bei fehlender Warnlage `null`/kein Dict — das ist
KEIN Fehler, sondern der reguläre Zustand "keine Warnlage" und muss als
status='ok', data_available=False abgebildet werden (nicht status='error')."""
import json

import pytest


def test_none_payload_ist_ok_ohne_warnlage():
    mod = pytest.importorskip("skywarn_export_snapshot")

    snap = mod.build_success_snapshot(None)

    assert snap["status"] == "ok"
    assert snap["data_available"] is False
    assert snap["valid_from"] is None
    assert snap["valid_to"] is None
    assert snap["features_inside_kaernten_bbox"]["features"] == []
    assert snap["error"] is None


def test_echte_warnlage_bleibt_ok_mit_data_available_true():
    mod = pytest.importorskip("skywarn_export_snapshot")

    payload = {
        "start": "2026-07-08T10:00:00+02:00",
        "end": "2026-07-08T18:00:00+02:00",
        "text": "<p>Testwarnung</p>",
        "polygon": None,
    }
    snap = mod.build_success_snapshot(payload)

    assert snap["status"] == "ok"
    assert snap["data_available"] is True
    assert snap["valid_from"] == payload["start"]
    assert snap["error"] is None


def test_echter_http_fehler_bleibt_status_error():
    """Regression: ein echter Abruf-Fehler (nicht 'keine Warnlage') muss
    weiterhin status='error' liefern — B326 betrifft ausschliesslich den
    None/Nicht-Dict-Payload-Fall."""
    mod = pytest.importorskip("skywarn_export_snapshot")

    snap = mod._error_snapshot("http_error", "HTTP 500", 500)

    assert snap["status"] == "error"
    assert snap["error"]["type"] == "http_error"


def test_todays_snapshot_had_real_data_true_bei_echter_warnlage(tmp_path):
    mod = pytest.importorskip("skywarn_export_snapshot")

    now = mod._now_vienna()
    snap = mod.build_success_snapshot(
        {"start": "2026-07-08T10:00:00", "end": "2026-07-08T12:00:00", "polygon": None}, now
    )
    p = tmp_path / "skywarn_export.json"
    p.write_text(json.dumps(snap), encoding="utf-8")

    assert mod._todays_snapshot_had_real_data(p, now) is True


def test_todays_snapshot_had_real_data_false_bei_keiner_warnlage(tmp_path):
    mod = pytest.importorskip("skywarn_export_snapshot")

    now = mod._now_vienna()
    snap = mod.build_success_snapshot(None, now)
    p = tmp_path / "skywarn_export.json"
    p.write_text(json.dumps(snap), encoding="utf-8")

    assert mod._todays_snapshot_had_real_data(p, now) is False


def test_no_warning_ueberschreibt_frueheres_no_warning_vom_selben_tag(monkeypatch, tmp_path):
    """Zwei aufeinanderfolgende 'keine Warnlage'-Ergebnisse am selben Tag
    duerfen sich gegenseitig ueberschreiben (kein Datenverlust, da beide
    keine echten Daten enthalten)."""
    mod = pytest.importorskip("skywarn_export_snapshot")

    snap_path = tmp_path / "skywarn_export.json"
    monkeypatch.setattr(mod, "_snapshot_path", lambda: snap_path)
    now = mod._now_vienna()
    first = mod.build_success_snapshot(None, now)
    snap_path.write_text(json.dumps(first), encoding="utf-8")

    class _FakeResponse:
        status = 200

        def read(self):
            return b"null"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda *a, **k: _FakeResponse())

    result = mod.fetch_and_store_skywarn_export_snapshot(force=True)

    assert result["status"] == "ok"
    assert result["data_available"] is False
    persisted = json.loads(snap_path.read_text(encoding="utf-8"))
    assert persisted["data_available"] is False
