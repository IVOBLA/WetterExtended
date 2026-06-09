"""P2-2: Stiller runtime_config-Ladefehler wird im Health-Status sichtbar."""
import importlib
import json
import pytest


def _rc():
    try:
        return importlib.import_module("runtime_config")
    except Exception as exc:
        pytest.skip(f"runtime_config nicht importierbar: {exc}")


def test_valid_json_clears_error(tmp_path, monkeypatch):
    rc = _rc()
    valid = tmp_path / "runtime_overrides.json"
    valid.write_text(json.dumps({"SLOW_CELL_MAX_KMH": 20}), encoding="utf-8")
    monkeypatch.setattr(rc, "_get_path", lambda: str(valid))
    rc.reload_overrides()
    assert rc.get_load_error() is None
    assert rc.get("SLOW_CELL_MAX_KMH", 15) == 20


def test_invalid_json_sets_load_error(tmp_path, monkeypatch):
    rc = _rc()
    bad = tmp_path / "runtime_overrides.json"
    bad.write_text("{UNGÜLTIGES JSON", encoding="utf-8")
    monkeypatch.setattr(rc, "_get_path", lambda: str(bad))
    rc.reload_overrides()
    err = rc.get_load_error()
    assert err is not None
    assert "JSON" in err


def test_missing_file_has_no_error(tmp_path, monkeypatch):
    rc = _rc()
    monkeypatch.setattr(rc, "_get_path", lambda: str(tmp_path / "nonexistent.json"))
    rc.reload_overrides()
    assert rc.get_load_error() is None


def test_check_runtime_config_reports_invalid(tmp_path, monkeypatch):
    rc = _rc()
    ahc = pytest.importorskip("api_health_check")
    bad = tmp_path / "runtime_overrides.json"
    bad.write_text("{BAD", encoding="utf-8")
    monkeypatch.setattr(rc, "_get_path", lambda: str(bad))
    rc.reload_overrides()
    result = ahc._check_runtime_config()
    assert result["ok"] is False
    assert result["note"]
