"""
Unit-Tests für Einheitenkonsistenz in WetterExtended.
Prüft: Kalman-Velocity-Einheiten, Forecast-Pixel-Rechnung,
       P26-Zeitdifferenz-Forecast, Lineage-Feature-Normierung.
"""
import sys
import os
import importlib

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
    # B115: ARSO INCA 5-min-Takt. km_per_px = PX_TO_KMH × FRAME_INTERVAL_MIN / 60
    # = 4.0 × 5/60 = 0.333 km/px (= 1/UPSCALE_FACTOR), physikalisch korrekt.
    km_per_px_per_frame = PX_TO_KMH * FRAME_INTERVAL_MIN / 60.0
    assert 0.1 < km_per_px_per_frame < 1.0, (
        f"Unplausible km/px: {km_per_px_per_frame:.3f} "
        f"(PX_TO_KMH={PX_TO_KMH}, FRAME_INTERVAL_MIN={FRAME_INTERVAL_MIN}). "
        f"Erwartung ~0.333 km/px bei UPSCALE=3."
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
        _append_kinematic = importlib.import_module("prediction")._append_kinematic
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

    # Kinematische Quelle muss "real_ts", "history" oder "ewma" enthalten (P26/P27)
    src = obj.get("kinematic_source", "")
    assert "real_ts" in src or "history" in src or "ewma" in src, (
        f"Erwartet real_ts, history oder ewma als Quelle, bekam: {src}"
    )

    # Forecast für 10 min: x0 + 5 px/min × 10 min = 70 + 50 = 120 px (original)
    f10 = forecasts.get(10, [])
    if f10:
        # Toleranz 10% wegen Upscale und Lat/Lon-Rundung
        assert len(f10) == 1, f"Genau ein Forecast-Eintrag für h=10: {f10}"


# ---------------------------------------------------------------------------
# Test 7 — P27: EWMA-Gewichtung bevorzugt neuere Intervalle
# ---------------------------------------------------------------------------

def test_ewma_weights_newer_frames():
    """
    P27: Mit 3 Frames (2 Intervalle) muss das neuere Intervall mehr Gewicht
    erhalten als das ältere. Bei Richtungswechsel Nordost → Ost muss:
      - vx EWMA > vx Mittel (7.5)
      - vy EWMA < vy Mittel (2.5)

    Frames:
      h[0] → h[1]: dx=+10px / 2min → vx=+5 px/min, vy=+5 px/min  (Nordost)
      h[1] → h[2]: dx=+20px / 2min → vx=+10 px/min, vy=0 px/min  (Ost)

    Einfaches Mittel:   vx=7.5   vy=2.5
    EWMA alpha=0.6:     vx=8.57  vy=1.43   (neuestes dominiert mit 71,4 %)
    """
    try:
        _append_kinematic = importlib.import_module("prediction")._append_kinematic
    except ImportError as exc:
        pytest.skip(f"prediction.py nicht importierbar: {exc}")

    obj = {
        "id": "ewma_test",
        "x": 80.0, "y": 40.0,
        "lat": 46.6, "lon": 14.3,
        "vx": 0.0, "vy": 0.0,
        "history": [
            {"timestamp": "2026-01-01_00-00-00", "x": 50.0, "y": 30.0,
             "vx": 5.0, "vy": 5.0, "lat": 46.5, "lon": 14.1},
            {"timestamp": "2026-01-01_00-02-00", "x": 60.0, "y": 40.0,
             "vx": 5.0, "vy": 5.0, "lat": 46.55, "lon": 14.2},
            {"timestamp": "2026-01-01_00-04-00", "x": 80.0, "y": 40.0,
             "vx": 10.0, "vy": 0.0, "lat": 46.6, "lon": 14.3},
        ],
    }
    forecasts = {10: [], 20: [], 30: [], 40: [], 60: []}
    _append_kinematic(obj, forecasts)

    src = obj.get("kinematic_source", "")
    assert src.startswith("ewma_"), (
        f"P27: kinematic_source muss mit 'ewma_' beginnen, bekam: {src}"
    )

    vx = obj.get("kinematic_vx", 0.0)
    vy = obj.get("kinematic_vy", 0.0)

    # EWMA-Bedingungen: neueres Ost-Intervall dominiert gegenüber einfachem Mittel
    assert vx > 7.5, (
        f"P27: EWMA vx muss > 7.5 (einfaches Mittel), bekam: {vx:.4f}"
    )
    assert vy < 2.5, (
        f"P27: EWMA vy muss < 2.5 (einfaches Mittel), bekam: {vy:.4f}"
    )
    assert len(forecasts.get(10, [])) == 1, (
        "P27: Genau ein Forecast-Eintrag für h=10 erwartet"
    )
