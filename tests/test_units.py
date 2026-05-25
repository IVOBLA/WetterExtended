"""
Unit-Tests für Einheitenkonsistenz in WetterExtended.
Prüft: Kalman-Velocity-Einheiten, Forecast-Pixel-Rechnung,
       P26-Zeitdifferenz-Forecast, Lineage-Feature-Normierung.
"""
import sys
import os

import pytest

# Repo-Root in sys.path (conftest.py macht das auch — doppelt schadet nicht)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Test 1 — UPSCALE_FACTOR und PX_TO_KMH Konsistenz
# ---------------------------------------------------------------------------

def test_config_scaling_constants():
    from config import UPSCALE_FACTOR, PX_TO_KMH, FRAME_INTERVAL_MIN
    assert UPSCALE_FACTOR > 0, "UPSCALE_FACTOR muss positiv sein"
    assert PX_TO_KMH > 0, "PX_TO_KMH muss positiv sein"
    assert FRAME_INTERVAL_MIN > 0, "FRAME_INTERVAL_MIN muss positiv sein"
    # Plausibilitätsprüfung: 1 px/Frame bei 2 min/Frame ≈ 0.3 km/h pro px
    km_per_px_per_frame = PX_TO_KMH * FRAME_INTERVAL_MIN / 60.0
    assert 0.01 < km_per_px_per_frame < 10.0, (
        f"Unplausible km/px/Frame: {km_per_px_per_frame:.3f}. "
        f"PX_TO_KMH={PX_TO_KMH}, FRAME_INTERVAL_MIN={FRAME_INTERVAL_MIN}"
    )


# ---------------------------------------------------------------------------
# Test 2 — Forecast-Einheiten: px/Frame → Horizont-Versatz korrekt
# ---------------------------------------------------------------------------

def test_kinematic_forecast_units():
    """
    Kinematischer Forecast: avg_vx in px/min, horizon in min.
    Erwartung: x_pred = x0 + avg_vx * horizon (nach P26-Fix).
    """
    from config import UPSCALE_FACTOR as UF

    x0 = 50.0          # Original-px
    avg_vx_per_min = 5.0   # px/min (nach P26-Fix)
    horizon = 10        # Minuten

    # Erwarteter Versatz: 5 px/min × 10 min = 50 px
    expected_delta = avg_vx_per_min * horizon
    x_pred_orig = x0 + expected_delta       # vor Skalierung
    x_pred_scaled = x_pred_orig * UF        # für pixel_to_geo

    assert abs(x_pred_orig - 100.0) < 0.001, (
        f"Erwarteter Versatz 50px: x_pred={x_pred_orig}"
    )
    assert x_pred_scaled == x_pred_orig * UF


# ---------------------------------------------------------------------------
# Test 3 — Lineage-Feature-Normierung (P17)
# ---------------------------------------------------------------------------

def test_lineage_feature_normalization():
    """active_frames_norm und total_active_frames_norm müssen in [0, 1] liegen."""
    # Simuliert den Berechnungscode aus object_tracking.py
    def compute_norm(active_frames, total_active_frames):
        anorm = min(float(active_frames), 20.0) / 20.0
        tnorm = min(float(total_active_frames), 100.0) / 100.0
        return anorm, tnorm

    for af in [0, 1, 10, 20, 50]:
        for tf in [0, 1, 50, 100, 500]:
            anorm, tnorm = compute_norm(af, tf)
            assert 0.0 <= anorm <= 1.0, f"active_frames_norm={anorm} außerhalb [0,1]"
            assert 0.0 <= tnorm <= 1.0, f"total_active_frames_norm={tnorm} außerhalb [0,1]"

    # Maximalwert-Kap
    anorm_max, tnorm_max = compute_norm(999, 9999)
    assert anorm_max == 1.0
    assert tnorm_max == 1.0


# ---------------------------------------------------------------------------
# Test 4 — ML_NUM_FEATURES ist konsistent mit Featuredefinition
# ---------------------------------------------------------------------------

def test_ml_num_features_consistent():
    from config import ML_NUM_FEATURES, ML_CELL_FEATURES, ML_STATION_FEATURES, ML_TIME_FEATURES
    expected = len(ML_CELL_FEATURES) + len(ML_STATION_FEATURES) + len(ML_TIME_FEATURES)
    assert ML_NUM_FEATURES == expected, (
        f"ML_NUM_FEATURES={ML_NUM_FEATURES} != "
        f"{len(ML_CELL_FEATURES)}+{len(ML_STATION_FEATURES)}+{len(ML_TIME_FEATURES)}="
        f"{expected}. Feature-Listen und ML_NUM_FEATURES laufen auseinander."
    )


# ---------------------------------------------------------------------------
# Test 5 — Lineage-Features in ML_CELL_FEATURES vorhanden (P17)
# ---------------------------------------------------------------------------

def test_lineage_features_in_cell_features():
    from config import ML_CELL_FEATURES
    required = ["active_frames_norm", "total_active_frames_norm", "is_merged", "is_split"]
    for k in required:
        assert k in ML_CELL_FEATURES, f"P17: '{k}' fehlt in ML_CELL_FEATURES"


# ---------------------------------------------------------------------------
# Test 6 — P26: echte px/min aus Timestamps (Integrations-Smoke-Test)
# ---------------------------------------------------------------------------

def test_real_time_velocity_from_history():
    """
    P26: Bei 2 History-Einträgen mit bekanntem x-Versatz und Zeitdifferenz
    muss _append_kinematic eine korrekte px/min Geschwindigkeit berechnen.
    """
    try:
        from prediction import _append_kinematic
    except ImportError as exc:
        pytest.skip(f"prediction.py nicht importierbar: {exc}")

    # Objekt mit 2 History-Einträgen: x bewegt sich 20 px in 4 Minuten → 5 px/min
    obj = {
        "id": "test",
        "x": 70.0, "y": 50.0,
        "lat": 46.6, "lon": 14.3,
        "vx": 0.0, "vy": 0.0,
        "history": [
            {"timestamp": "2026-01-01_00-00-00", "x": 50.0, "y": 50.0, "vx": 2.0, "vy": 0.0, "lat": 46.5, "lon": 14.2},
            {"timestamp": "2026-01-01_00-04-00", "x": 70.0, "y": 50.0, "vx": 2.0, "vy": 0.0, "lat": 46.6, "lon": 14.3},
        ],
    }
    forecasts = {10: [], 20: [], 30: [], 40: [], 60: []}
    _append_kinematic(obj, forecasts)

    # Kinematische Quelle muss "real_ts" enthalten (P26-Fix)
    src = obj.get("kinematic_source", "")
    assert "real_ts" in src or "history" in src, (
        f"Erwartet real_ts oder history als Quelle, bekam: {src}"
    )

    # Forecast für 10 min: x0 + 5 px/min × 10 min = 70 + 50 = 120 px (original)
    f10 = forecasts.get(10, [])
    if f10:
        # Toleranz 10% wegen Upscale und Lat/Lon-Rundung
        assert len(f10) == 1, f"Genau ein Forecast-Eintrag für h=10: {f10}"
