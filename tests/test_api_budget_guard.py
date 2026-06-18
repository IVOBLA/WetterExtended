"""1E / P49: api_budget_guard — Gruppen-Mapping, Tageszaehler, Reset, Durchsetzung.
Reine Logik mit isoliertem tmp-Budgetfile; kein Netzwerk, kein Flask.
"""
import pytest

import api_budget_guard as bg


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(bg, "_BUDGET_FILE", str(tmp_path / "api_budget.json"))
    monkeypatch.setattr(bg, "_budgets", lambda: {"openmeteo": 3})
    yield


def test_group_mapping():
    assert bg.group_for("openmeteo_icon_d2") == "openmeteo"
    assert bg.group_for("openmeteo_extended_15min") == "openmeteo"
    assert bg.group_for("geosphere_nowcast") == "geosphere_nowcast"
    assert bg.group_for("") == ""


def test_counting_and_enforcement():
    assert bg.over_budget("openmeteo_icon_d2") is False
    bg.record_request("openmeteo_icon_d2")
    bg.record_request("openmeteo_icon_global")   # gleiche Gruppe
    assert bg.over_budget("openmeteo_icon_d2") is False  # 2 < 3
    bg.record_request("openmeteo_synoptic_500")
    assert bg.over_budget("openmeteo_icon_d2") is True   # 3 >= 3 (gruppenweit)


def test_no_limit_group_never_blocks():
    for _ in range(50):
        bg.record_request("geosphere_nowcast")
    assert bg.over_budget("geosphere_nowcast") is False


def test_daily_reset(monkeypatch):
    monkeypatch.setattr(bg, "_today", lambda: "2026-06-17")
    for _ in range(3):
        bg.record_request("openmeteo_icon_d2")
    assert bg.over_budget("openmeteo_icon_d2") is True
    monkeypatch.setattr(bg, "_today", lambda: "2026-06-18")   # neuer Tag -> Reset
    assert bg.over_budget("openmeteo_icon_d2") is False
    snap = bg.snapshot()
    assert snap["date"] == "2026-06-18"
    assert snap["groups"]["openmeteo"]["count"] == 0


def test_snapshot_shape():
    bg.record_request("openmeteo_icon_d2")
    g = bg.snapshot()["groups"]["openmeteo"]
    assert g["budget"] == 3
    assert g["count"] == 1
    assert g["remaining"] == 2
    assert g["over"] is False
