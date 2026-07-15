"""B384: Die angepassten Bestandstests müssen die NEUE Architektur prüfen."""
import math

import pytest


def test_scaled_pixel_to_km_factor_matches_config():
    """Der im B365-Test verwendete Massstab muss aus der Config ableitbar sein."""
    from config import PX_TO_KMH, UPSCALE_FACTOR
    km_per_orig_px = PX_TO_KMH * (5.0 / 60.0)
    km_per_scaled_px = km_per_orig_px / float(UPSCALE_FACTOR)
    assert km_per_scaled_px == pytest.approx(0.111, abs=0.005), (
        f"Massstab abweichend: {km_per_scaled_px:.4f} km/skaliertem px — "
        "der Mock in test_b365 ist entsprechend nachzuziehen."
    )


def test_ninety_scaled_px_is_about_ten_km():
    """90 skalierte px (Testdistanz in B365) muessen ~10 km ergeben."""
    from config import PX_TO_KMH, UPSCALE_FACTOR
    km = 90.0 * (PX_TO_KMH * (5.0 / 60.0) / float(UPSCALE_FACTOR))
    assert 8.0 < km < 12.0, f"90 skalierte px = {km:.1f} km — ausserhalb des erwarteten Bereichs"


def test_weak_cap_gates_ten_km_but_not_zero():
    """Der Schwach-Cap muss bei 10 km greifen und bei 0 km korrekterweise nicht."""
    from tracking.association import DetectionCandidate, TrackCandidate, passes_physical_gate
    weak = TrackCandidate(track_id="W", pred_x_km=0.0, pred_y_km=0.0,
                          vx_kmh=0.0, vy_kmh=0.0, area_px=8100.0, core_ratio=0.0, age_frames=5)
    ok_far, _ = passes_physical_gate(weak, DetectionCandidate(index=0, x_km=10.0, y_km=0.0, area_px=8100.0),
                                     dt_minutes=5.0, max_speed_kmh=150.0)
    ok_same, _ = passes_physical_gate(weak, DetectionCandidate(index=1, x_km=0.0, y_km=0.0, area_px=8100.0),
                                      dt_minutes=5.0, max_speed_kmh=150.0)
    assert not ok_far, "10 km muessen fuer eine schwache Zelle gegatet werden"
    assert ok_same, "0 km Distanz darf nicht gegatet werden — genau das mass der alte Mock"


def test_transition_confirm_frames_is_two():
    """Die Testerwartung 'Ereignis in Frame 3' haengt an diesem Wert."""
    from tracking.transition_resolver import _cfg
    assert int(_cfg("TRANSITION_CONFIRM_FRAMES")) == 2


def test_b365_mock_is_position_dependent():
    """Regression: ein konstanter Geo-Mock darf nicht zurueckkehren."""
    src = open("tests/test_b365_stage2_weak_cell_match_cap.py", encoding="utf-8").read()
    assert 'lambda x, y: (46.7, 14.3)' not in src, (
        "Konstanter Geo-Mock wieder vorhanden — jedes km-Distanzgate waere wirkungslos"
    )
    assert "_KM_PER_SCALED_PX" in src


def test_b117_checks_confirmed_merge_in_frame3():
    src = open("tests/test_b117_track_continuity.py", encoding="utf-8").read()
    assert "00-10-00" in src, "Frame 3 (Bestaetigung) fehlt im B117-Test"
    assert 'm3.get("lineage") == "merged"' in src
