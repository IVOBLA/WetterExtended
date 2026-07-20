"""B433: Der Zustand der Hochwasserbewertung überlebt einen Cache-Treffer.

Live-Befund 2026-07-17: hydro_status.json meldete
{"ok": true, "from_cache": true, "error": null} — 37 Sekunden nach dem letzten von
178 DatabaseError. `_mark_cache` baut den Status aus latest_hydro.json["status"] neu
auf; dort stehen die Eval-Schlüssel nie, weil LATEST_FILE vor dem Eval-Block
geschrieben wird.
"""
import json

import pytest

import hydro_fetch


@pytest.fixture()
def _live_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(hydro_fetch, "_LIVE_DIR", tmp_path)
    monkeypatch.setattr(hydro_fetch, "STATUS_FILE", tmp_path / "hydro_status.json")
    monkeypatch.setattr(hydro_fetch, "LATEST_FILE", tmp_path / "latest_hydro.json")
    monkeypatch.setattr(hydro_fetch, "FLOOD_EVAL_STATUS_FILE", tmp_path / "hydro_flood_eval_status.json")
    return tmp_path


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_fehlerstatus_wird_geschrieben(_live_dir):
    hydro_fetch._write_flood_eval_status("error", error="DatabaseError: database disk image is malformed")
    doc = _read(_live_dir / "hydro_flood_eval_status.json")
    assert doc["hydro_flood_eval_status"] == "error"
    assert "malformed" in doc["error"]
    assert doc["hydro_flood_eval_at"]


def test_erfolgsfall_wird_ebenfalls_geschrieben(_live_dir):
    """Ohne Erfolgseintrag ist 'kein Eintrag' nicht von 'lief gut' unterscheidbar."""
    hydro_fetch._write_flood_eval_status("ok", mode="evaluated", station_count=85,
                                         sample_store_status="ok")
    doc = _read(_live_dir / "hydro_flood_eval_status.json")
    assert doc["hydro_flood_eval_status"] == "ok"
    assert doc["station_count"] == 85
    assert doc["sample_store_status"] == "ok"


def test_none_felder_werden_nicht_geschrieben(_live_dir):
    hydro_fetch._write_flood_eval_status("ok", mode="evaluated", deferred_reason=None)
    doc = _read(_live_dir / "hydro_flood_eval_status.json")
    assert "deferred_reason" not in doc


def test_cache_treffer_loescht_den_evalstatus_nicht(_live_dir):
    """Der eigentliche Regressionstest gegen den Live-Befund."""
    hydro_fetch._write_flood_eval_status("error", error="DatabaseError: database disk image is malformed")

    cached = {"fetched_at": "2026-07-17T21:44:00Z", "stations": [{"station_id": "2001049"}],
              "status": {"ok": True, "from_cache": False, "station_count": 1, "error": None}}
    result = hydro_fetch._mark_cache(cached)
    hydro_fetch._write_status(result["status"])

    status = _read(_live_dir / "hydro_status.json")
    assert status["from_cache"] is True
    assert status["error"] is None
    doc = _read(_live_dir / "hydro_flood_eval_status.json")
    assert doc["hydro_flood_eval_status"] == "error"
    assert "malformed" in doc["error"]


def test_mark_cache_kennt_die_evaldatei_nicht(_live_dir):
    """_mark_cache darf keine Eval-Schlüssel erfinden oder tilgen."""
    cached = {"stations": [], "status": {"ok": True, "station_count": 0, "error": None}}
    result = hydro_fetch._mark_cache(cached)
    assert "hydro_flood_eval_status" not in result["status"]
    assert "hydro_flood_eval_error" not in result["status"]


def test_schreibfehler_bricht_den_abruf_nicht_ab(_live_dir, monkeypatch):
    def _boom(*_a, **_k):
        raise OSError("Read-only file system")
    monkeypatch.setattr(hydro_fetch, "_atomic_write_json", _boom)
    hydro_fetch._write_flood_eval_status("error", error="egal")
