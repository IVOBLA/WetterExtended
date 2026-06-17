"""B177: download_kmz()-Skip-Grund wird gesetzt und von main.py differenziert geloggt."""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def _read(rel):
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_circuit_open_sets_reason(monkeypatch):
    rd = pytest.importorskip("radar_download")
    cb = pytest.importorskip("api_circuit_breaker")
    monkeypatch.setattr(cb, "is_open", lambda svc: True)
    assert rd.download_kmz() is False
    assert rd.last_skip_reason() == "circuit_open"


def test_error_reasons_present_in_source():
    src = _read("radar_download.py")
    for reason in ("download_failed", "invalid_zip", "unzip_empty", "unzip_error"):
        assert f'_LAST_SKIP_REASON = "{reason}"' in src, f"Grund {reason} fehlt"
    assert '_LAST_SKIP_REASON = "not_new"' in src
    assert "_LAST_SKIP_REASON = None" in src


def test_main_uses_skip_reason():
    src = _read("main.py")
    assert "last_skip_reason" in src, "main.py liest den Skip-Grund nicht"
    assert "Radarbild nicht neu" in src
