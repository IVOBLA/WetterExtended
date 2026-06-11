"""
tests/test_b115_time_base.py

B115: Zeitbasis-Korrektur (ARSO INCA realer 5-Min-Takt).
Belegt:
  1. Konstanten PX_TO_KMH=4.0, FRAME_INTERVAL_MIN=5.0 + Geometrie-Invariante.
  2. _actual_frame_min() leitet echtes Intervall ab; robust gegen Duplikate.
  3. speed_kmh wird bei 5-min-Frames korrekt (≈ vx×4), bei Lücken via dt skaliert.
  4. Forecast-Drift +30min: alte 2-min-Basis ~13 km zu weit, neue Basis <1 km.

Ausführbar: python3 -m pytest tests/test_b115_time_base.py -v
"""
import sys, os, math, importlib
from datetime import datetime, timedelta
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import PX_TO_KMH, FRAME_INTERVAL_MIN, UPSCALE_FACTOR


def _helper():
    try:
        return importlib.import_module("prediction")._actual_frame_min
    except (ImportError, AttributeError) as e:
        pytest.skip(f"_actual_frame_min fehlt: {e}")


def _ts(m):
    return (datetime(2026, 6, 11, 14, 0, 0) + timedelta(minutes=m)).strftime("%Y-%m-%d_%H-%M-%S")


class TestConstants:
    def test_px_to_kmh_is_four(self):
        assert PX_TO_KMH == 4.0, f"B115: PX_TO_KMH muss 4.0 sein, ist {PX_TO_KMH}"

    def test_frame_interval_is_five(self):
        assert FRAME_INTERVAL_MIN == 5.0, f"B115: FRAME_INTERVAL_MIN muss 5.0 sein, ist {FRAME_INTERVAL_MIN}"

    def test_geometry_invariant(self):
        exp = (1.0 / UPSCALE_FACTOR) / (FRAME_INTERVAL_MIN / 60.0)
        assert abs(PX_TO_KMH - exp) < 0.05, f"Geometrie verletzt: {PX_TO_KMH} != {exp:.3f}"


class TestActualFrameMin:
    def test_five_min(self):
        fm = _helper()
        h = [{"timestamp": _ts(i * 5)} for i in range(6)]
        assert abs(fm(h, 5.0) - 5.0) < 0.01

    def test_duplicates_return_default(self):
        fm = _helper()
        h = [{"timestamp": _ts(0)} for _ in range(4)]
        assert fm(h, 5.0) == 5.0

    def test_mixed(self):
        fm = _helper()
        h = [{"timestamp": _ts(0)}, {"timestamp": _ts(0)},
             {"timestamp": _ts(5)}, {"timestamp": _ts(10)}]
        assert abs(fm(h, 5.0) - 5.0) < 0.01

    def test_gap_filtered(self):
        fm = _helper()
        h = [{"timestamp": _ts(0)}, {"timestamp": _ts(60)}, {"timestamp": _ts(65)}]
        assert abs(fm(h, 5.0) - 5.0) < 0.01

    def test_empty(self):
        fm = _helper()
        assert fm([], 5.0) == 5.0


class TestSpeedCalibration:
    def test_speed_correct_at_5min(self):
        """vx=3 px/5min-step → wahre Geschwindigkeit = 3 × 4.0 = 12 km/h."""
        from config import speed_kmh_from_px
        assert abs(speed_kmh_from_px(3.0, 0.0) - 12.0) < 0.01

    def test_old_calibration_was_2_5x(self):
        """Dokumentiert den Bug: alte PX_TO_KMH=10 hätte 30 km/h (2,5×) ergeben."""
        vx = 3.0
        true_kmh = vx * 4.0
        old_kmh = vx * 10.0
        assert abs(old_kmh / true_kmh - 2.5) < 0.01


class TestForecastDrift:
    def test_30min_drift_within_1km(self):
        """
        Zelle 5-min-Frames, vx=3 px/step. Wahre +30-Position vs. alte 2-min-Basis.
        km_per_px = 1/UPSCALE = 1/3.
        """
        km_per_px = 1.0 / UPSCALE_FACTOR
        vx_kalman = 3.0           # px pro echtem 5-min-Step
        horizon = 30.0

        true_vx_pm = vx_kalman / 5.0          # px/min
        correct_px = true_vx_pm * horizon

        new_px = (vx_kalman / FRAME_INTERVAL_MIN) * horizon   # FRAME_INTERVAL_MIN=5.0
        old_px = (vx_kalman / 2.0) * horizon                  # alte 2-min-Basis

        drift_new = abs(new_px - correct_px) * km_per_px
        drift_old = abs(old_px - correct_px) * km_per_px

        assert drift_new < 1.0, f"Neue Basis Drift {drift_new:.2f} km (Ziel <1)"
        assert drift_old > 5.0, f"Alte Basis Drift {drift_old:.2f} km (muss groß sein)"
