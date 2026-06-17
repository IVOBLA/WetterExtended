"""
Tests für risk_watch.risk_watch_active (Polling-Priorisierung).
Dependency-arm: kein Netzwerk, kein laufender Server — HTTP-Getter injiziert.
"""
import sys
import types

sys.modules.setdefault(
    "debug_utils", types.SimpleNamespace(debug_log=lambda *args, **kwargs: None)
)

import runtime_config
import risk_watch


class _Resp:
    def __init__(self, status_code, cells):
        self.status_code = status_code
        self._cells = cells

    def json(self):
        return {"cells": self._cells}


def _getter(status_code=200, cells=None):
    def _g(url, timeout=5):
        return _Resp(status_code, cells or [])
    return _g


def _cfg(values):
    def _g(name, default=None):
        return values.get(name, default)
    return _g


def test_cb_ir_precursor_triggers_without_http(monkeypatch):
    monkeypatch.setattr(runtime_config, "get", _cfg({"RISK_WATCH_ENABLED": True}))

    def _boom(*a, **k):
        raise AssertionError("HTTP darf bei IR-Treffer nicht aufgerufen werden")

    assert risk_watch.risk_watch_active(
        ir_tracks=[{"ir_only_precursor": 1.0}], http_get=_boom, data_age_min=0.0
    ) is True


def test_non_precursor_ir_does_not_trigger(monkeypatch):
    # IR-Track ohne ir_only_precursor (z. B. radar-gematcht) → kein IR-Trigger;
    # ohne Potenzial im Grid → False.
    monkeypatch.setattr(
        runtime_config, "get",
        _cfg({"RISK_WATCH_ENABLED": True, "RISK_WATCH_MIN_RISK_LEVEL": 2}),
    )
    assert risk_watch.risk_watch_active(
        ir_tracks=[{"ir_only_precursor": 0.0}], http_get=_getter(200, [{"risk": 1}])
    ) is False


def test_disabled_returns_false(monkeypatch):
    monkeypatch.setattr(runtime_config, "get", _cfg({"RISK_WATCH_ENABLED": False}))
    assert risk_watch.risk_watch_active(
        ir_tracks=[{"ir_only_precursor": 1.0}],
        http_get=_getter(200, [{"risk": 3}]),
    ) is False


def test_grid_level_meets_threshold(monkeypatch):
    monkeypatch.setattr(
        runtime_config, "get",
        _cfg({"RISK_WATCH_ENABLED": True, "RISK_WATCH_MIN_RISK_LEVEL": 2}),
    )
    assert risk_watch.risk_watch_active(
        ir_tracks=[],
        http_get=_getter(200, [{"risk": 2}, {"risk": 1}]),
        data_age_min=0.0,
    ) is True


def test_grid_level_below_threshold(monkeypatch):
    monkeypatch.setattr(
        runtime_config, "get",
        _cfg({"RISK_WATCH_ENABLED": True, "RISK_WATCH_MIN_RISK_LEVEL": 2}),
    )
    assert risk_watch.risk_watch_active(
        ir_tracks=[], http_get=_getter(200, [{"risk": 1}])
    ) is False


def test_grid_unreachable_returns_false(monkeypatch):
    monkeypatch.setattr(
        runtime_config, "get",
        _cfg({"RISK_WATCH_ENABLED": True, "RISK_WATCH_MIN_RISK_LEVEL": 2}),
    )
    assert risk_watch.risk_watch_active(
        ir_tracks=[], http_get=_getter(500, [])
    ) is False
