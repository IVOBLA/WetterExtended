"""P48: Tests für den reinen Helfer _risk_score01_and_drivers (score01 + drivers).
Kein Flask-Client, kein Netzwerk — direkter Import des Helfers."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import _risk_score01_and_drivers


def test_score01_normalisierung_und_cap():
    s, _ = _risk_score01_and_drivers({"score": 1.25, "dominant": "atm"}, 2.5)
    assert s == 0.5
    s2, _ = _risk_score01_and_drivers({"score": 9.9, "dominant": "cell"}, 2.5)
    assert s2 == 1.0
    s3, _ = _risk_score01_and_drivers({"score": 0.0}, 2.5)
    assert s3 == 0.0


def test_score01_norm_guard():
    # norm <= 0 → Fallback 2.5
    s, _ = _risk_score01_and_drivers({"score": 2.5}, 0)
    assert s == 1.0


def test_drivers_cell_dominant_zuerst():
    info = {
        "score": 2.6, "dominant": "cell",
        "cell_id": 42, "cell_dist_km": 7.3,
        "in_forecast_track": True,
        "lightning_count": 3,
        "li": -2.4,
    }
    _, drivers = _risk_score01_and_drivers(info, 2.5)
    sources = [d["source"] for d in drivers]
    assert sources[0] == "cell"
    assert set(sources) == {"cell", "track", "lightning", "atm"}
    cell = next(d for d in drivers if d["source"] == "cell")
    assert "7.3 km" in cell["label"] and "#42" in cell["label"]


def test_drivers_atm_only():
    _, drivers = _risk_score01_and_drivers(
        {"score": 0.8, "dominant": "atm", "li": -3.1}, 2.5)
    assert len(drivers) == 1 and drivers[0]["source"] == "atm"
    assert "LI -3.1" in drivers[0]["label"]


def test_drivers_ir_und_ship_fallback():
    # kein LI < -1, aber SHIP >= 1 → atm via SHIP; zusätzlich IR-Vorläufer
    info = {"score": 1.2, "dominant": "ir_cell",
            "ir_cell_id": 9, "ir_bt_min_k": 212.0, "ship": 1.6, "li": 0.5}
    _, drivers = _risk_score01_and_drivers(info, 2.5)
    sources = [d["source"] for d in drivers]
    assert sources[0] == "ir_cell"
    assert "ir_cell" in sources and "atm" in sources
    atm = next(d for d in drivers if d["source"] == "atm")
    assert "SHIP 1.6" in atm["label"]


def test_drivers_leer_wenn_keine_quelle():
    _, drivers = _risk_score01_and_drivers({"score": 0.31, "dominant": "atm"}, 2.5)
    assert drivers == []
