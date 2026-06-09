"""B105/P0-1: Geschwindigkeits-Einheiten — vx/vy sind ORIGINAL-px/Frame."""
import math
import pytest

pytest.importorskip("numpy")


def test_speed_helper_no_upscale_division():
    from config import speed_kmh_from_px, PX_TO_KMH
    # 1 Original-px/Frame in x → speed == PX_TO_KMH (NICHT PX_TO_KMH/UF)
    assert speed_kmh_from_px(1.0, 0.0) == pytest.approx(float(PX_TO_KMH))
    assert speed_kmh_from_px(0.0, 0.0) == 0.0
    assert speed_kmh_from_px(3.0, 4.0) == pytest.approx(5.0 * float(PX_TO_KMH))


def test_px_to_kmh_matches_geometry():
    # PX_TO_KMH = km/h pro Original-px/Frame muss zur Geometrie passen:
    # 1 Original-px = 1/UF km; pro Frame (FRAME_INTERVAL_MIN) → km/h.
    from config import PX_TO_KMH, UPSCALE_FACTOR, FRAME_INTERVAL_MIN
    km_per_orig_px = 1.0 / float(UPSCALE_FACTOR)
    expected = km_per_orig_px / (float(FRAME_INTERVAL_MIN) / 60.0)
    assert float(PX_TO_KMH) == pytest.approx(expected, rel=0.05), (
        f"PX_TO_KMH={PX_TO_KMH} passt nicht zur Geometrie (erwartet ~{expected:.2f})"
    )


def test_clamp_uses_original_px_units():
    """_clamp_kalman_velocity darf nicht durch UPSCALE_FACTOR teilen:
    eine vx knapp unter MAX_CELL_SPEED_KMH/PX_TO_KMH darf NICHT geklemmt werden."""
    import importlib
    ot = importlib.import_module("object_tracking")
    from config import PX_TO_KMH, MAX_CELL_SPEED_KMH

    class _KF:
        def __init__(self, vx):
            self.x = [0.0, 0.0, vx, 0.0]

    # vx so wählen, dass speed knapp UNTER dem Limit liegt (Original-px-Annahme):
    vx_just_under = (float(MAX_CELL_SPEED_KMH) / float(PX_TO_KMH)) * 0.9
    kf = _KF(vx_just_under)
    ot._clamp_kalman_velocity(kf, vx_just_under, 0.0)
    # Darf NICHT geklemmt worden sein (bei falscher /UF-Logik wäre Limit 3× höher,
    # ebenfalls nicht geklemmt — daher zweiter Fall:)
    assert kf.x[2] == pytest.approx(vx_just_under, rel=1e-6)

    # vx klar ÜBER dem Limit → muss geklemmt werden (Original-px-Annahme).
    vx_over = (float(MAX_CELL_SPEED_KMH) / float(PX_TO_KMH)) * 1.5
    kf2 = _KF(vx_over)
    ot._clamp_kalman_velocity(kf2, vx_over, 0.0)
    speed_after = abs(kf2.x[2]) * float(PX_TO_KMH)
    assert speed_after <= float(MAX_CELL_SPEED_KMH) + 1e-6, (
        "Clamp greift nicht bei Original-px-Einheiten → /UF-Fehler noch vorhanden"
    )
