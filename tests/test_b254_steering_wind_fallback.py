"""B254 — Steuerwind-Fallback für IR-Vorläufer ohne Bewegungsableitung."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ir_cell_tracking as irt


def _forecast(track_overrides: dict) -> dict:
    base = {"lat": 46.36, "lon": 12.71, "vx_deg_min": 0.0, "vy_deg_min": 0.0}
    base.update(track_overrides)
    return irt._forecast_fields(base)


# ─── F9: Stationäre Prognose bei vx=vy=0 ohne Wind ──────────────────────────

def test_kein_wind_kein_steuerwind_forecast_mode_none():
    """Ohne vx/vy und ohne Wind bleibt forecast_mode='none'."""
    out = _forecast({})
    assert out["forecast_mode"] == "none"
    assert out["forecast_confidence"] == 0.2
    # Alle Horizonte identisch mit Ist-Position
    for m in (10, 20, 30, 40, 60):
        assert out[f"forecast_lat_{m}"] == 46.36
        assert out[f"forecast_lon_{m}"] == 12.71


# ─── B254: Steuerwind-Fallback aktiv ─────────────────────────────────────────

def test_steuerwind_fallback_aktiv():
    """Mit 700-hPa-Wind wird forecast_mode='steering_wind' gesetzt."""
    # Wind von Westen (270°): cos=0, sin=-1 → Zug nach Osten
    out = _forecast({
        "wind_speed_700hPa": 20.0,  # km/h
        "wind_dir_cos": 0.0,
        "wind_dir_sin": -1.0,  # West-Wind → Zug nach Osten (sin=-1 = Ostkomponente?)
    })
    assert out["forecast_mode"] == "steering_wind", (
        f"Erwartet steering_wind, erhalten: {out['forecast_mode']}"
    )
    assert out["forecast_confidence"] == 0.35
    # Prognose-Positionen sollen sich unterscheiden
    assert out["forecast_lat_60"] != 46.36 or out["forecast_lon_60"] != 12.71, (
        "Steuerwind-Prognose darf nicht stationär sein"
    )


def test_steuerwind_konfidenz_kleiner_als_ir_track():
    """Steuerwind-Konfidenz (0.35) < ir_track-Konfidenz (0.55)."""
    out_sw = _forecast({"wind_speed_700hPa": 15.0, "wind_dir_cos": 0.7, "wind_dir_sin": 0.7})
    out_it = _forecast({"vx_deg_min": 0.01, "vy_deg_min": 0.01})
    assert out_sw["forecast_confidence"] < out_it["forecast_confidence"]


# ─── Regressions-Test: vx/vy aus Kalman hat Vorrang ──────────────────────────

def test_kalman_vx_vy_hat_vorrang_vor_steuerwind():
    """Wenn vx/vy aus Kalman-Ableitung vorhanden, wird Steuerwind ignoriert."""
    out = _forecast({
        "vx_deg_min": 0.003,
        "vy_deg_min": -0.001,
        "wind_speed_700hPa": 30.0,
        "wind_dir_cos": 0.5,
        "wind_dir_sin": 0.5,
    })
    assert out["forecast_mode"] == "ir_track"
    assert out["forecast_confidence"] == 0.55


def test_schwache_wind_kein_steuerwind():
    """Wind < 0.1 km/h soll keinen Steuerwind-Fallback aktivieren."""
    out = _forecast({"wind_speed_700hPa": 0.05, "wind_dir_cos": 1.0, "wind_dir_sin": 0.0})
    assert out["forecast_mode"] == "none"


def test_horizonte_in_unterschiedlichen_positionen_mit_steuerwind():
    """Verschiedene Zeithorizonte sollen verschiedene Positionen liefern."""
    out = _forecast({"wind_speed_700hPa": 25.0, "wind_dir_cos": 0.8, "wind_dir_sin": 0.6})
    assert out["forecast_mode"] == "steering_wind"
    lats = [out[f"forecast_lat_{m}"] for m in (10, 20, 30, 40, 60)]
    lons = [out[f"forecast_lon_{m}"] for m in (10, 20, 30, 40, 60)]
    # Positionen sollen monoton wachsen (oder zumindest nicht alle gleich sein)
    assert len(set(lats)) > 1 or len(set(lons)) > 1, (
        "Zeithorizonte sollen unterschiedliche Positionen liefern"
    )
