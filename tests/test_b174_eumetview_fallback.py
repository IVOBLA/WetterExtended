"""B174: read_last_timestamp-Fallback mit Frische-Guard."""
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _mod():
    return pytest.importorskip("cloud_height_from_eumetview")


def _fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_fallback_returns_fresh(monkeypatch):
    mod = _mod()
    fresh = _fmt(datetime.utcnow() - timedelta(minutes=10))
    monkeypatch.setattr(mod, "read_last_timestamp", lambda: fresh)
    assert mod._caps_fallback("x") == fresh


def test_fallback_rejects_old(monkeypatch):
    mod = _mod()
    old = _fmt(datetime.utcnow() - timedelta(minutes=120))
    monkeypatch.setattr(mod, "read_last_timestamp", lambda: old)
    assert mod._caps_fallback("x") is None


def test_fallback_none_when_missing(monkeypatch):
    mod = _mod()
    monkeypatch.setattr(mod, "read_last_timestamp", lambda: None)
    assert mod._caps_fallback("x") is None


def test_fallback_none_when_unparsable(monkeypatch):
    mod = _mod()
    monkeypatch.setattr(mod, "read_last_timestamp", lambda: "not-a-timestamp")
    assert mod._caps_fallback("x") is None
