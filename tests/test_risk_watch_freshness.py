"""
Tests für die Codex-Review-Fixes in risk_watch:
  - Auto-Load persistierter IR-Tracks wenn ir_tracks is None (Skip-Pfad)
  - Frische-Gate: veraltete Daten erzwingen KEINEN kurzen Intervall
Dependency-arm: kein Netzwerk, kein Server.
"""
import sys
import types

sys.modules.setdefault(
    "debug_utils", types.SimpleNamespace(debug_log=lambda *a, **k: None)
)

import runtime_config
import risk_watch


def _cfg(values):
    def _g(name, default=None):
        return values.get(name, default)
    return _g


def _getter(status_code=200, cells=None):
    class _Resp:
        def __init__(self):
            self.status_code = status_code

        def json(self):
            return {"cells": cells or []}
    return lambda url, timeout=5: _Resp()


def test_stale_data_blocks_precursor_trigger(monkeypatch):
    # Frische CB-IR-Vorläuferzelle vorhanden, aber Daten veraltet → False.
    monkeypatch.setattr(
        runtime_config, "get",
        _cfg({"RISK_WATCH_ENABLED": True, "RISK_WATCH_MAX_DATA_AGE_MIN": 20.0}),
    )
    assert risk_watch.risk_watch_active(
        ir_tracks=[{"ir_only_precursor": 1.0}], data_age_min=999.0
    ) is False


def test_stale_data_blocks_grid_trigger(monkeypatch):
    monkeypatch.setattr(
        runtime_config, "get",
        _cfg({"RISK_WATCH_ENABLED": True, "RISK_WATCH_MIN_RISK_LEVEL": 2,
              "RISK_WATCH_MAX_DATA_AGE_MIN": 20.0}),
    )
    assert risk_watch.risk_watch_active(
        ir_tracks=[], http_get=_getter(200, [{"risk": 3}]), data_age_min=999.0
    ) is False


def test_fresh_precursor_triggers(monkeypatch):
    monkeypatch.setattr(
        runtime_config, "get",
        _cfg({"RISK_WATCH_ENABLED": True, "RISK_WATCH_MAX_DATA_AGE_MIN": 20.0}),
    )
    assert risk_watch.risk_watch_active(
        ir_tracks=[{"ir_only_precursor": 1.0}], data_age_min=5.0
    ) is True


def test_auto_loads_ir_tracks_when_none(monkeypatch):
    # ir_tracks is None → load_active_ir_tracks wird genutzt (Skip-Pfad).
    monkeypatch.setattr(
        runtime_config, "get",
        _cfg({"RISK_WATCH_ENABLED": True, "RISK_WATCH_MAX_DATA_AGE_MIN": 20.0}),
    )
    import ir_cell_tracking
    monkeypatch.setattr(
        ir_cell_tracking, "load_active_ir_tracks",
        lambda: [{"ir_only_precursor": 1.0}],
    )

    def _boom(*a, **k):
        raise AssertionError("HTTP darf bei geladenem IR-Vorläufer nicht nötig sein")

    assert risk_watch.risk_watch_active(
        http_get=_boom, data_age_min=0.0
    ) is True
