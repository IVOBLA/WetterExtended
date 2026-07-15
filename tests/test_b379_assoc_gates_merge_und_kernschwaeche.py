"""B379: Gates müssen Merge/Split zulassen und die Kernstärke berücksichtigen."""
import pytest

from tracking.association import (
    DetectionCandidate,
    TrackCandidate,
    _effective_max_speed,
    _max_area_ratio,
    passes_physical_gate,
    solve_global_assignment,
)


def _trk(tid, x, y, vx=0.0, vy=0.0, area=1000.0, core=0.3, age=5):
    return TrackCandidate(track_id=tid, pred_x_km=x, pred_y_km=y, vx_kmh=vx, vy_kmh=vy,
                          area_px=area, core_ratio=core, age_frames=age)


def _det(i, x, y, area=1000.0, core=0.3):
    return DetectionCandidate(index=i, x_km=x, y_km=y, area_px=area, core_ratio=core)


def test_merge_growth_is_not_gated():
    """Kernregression B117: 6.25x Wachstum (80x80 -> 200x200 px) muss zulaessig sein."""
    trk = _trk("A", 0.0, 0.0, area=6400.0)
    det = _det(0, 1.0, 0.0, area=40000.0)
    ok, reason = passes_physical_gate(trk, det, dt_minutes=5.0, max_speed_kmh=150.0)
    assert ok, f"Merge-Kontur wurde gegatet: {reason}"


def test_split_shrink_is_not_gated():
    """Umkehrfall: bei einem Split schrumpft die Kontur um denselben Faktor."""
    trk = _trk("A", 0.0, 0.0, area=40000.0)
    det = _det(0, 1.0, 0.0, area=6400.0)
    ok, reason = passes_physical_gate(trk, det, dt_minutes=5.0, max_speed_kmh=150.0)
    assert ok, f"Split-Kind wurde gegatet: {reason}"


def test_absurd_area_ratio_still_gated():
    """Das Gate muss absurde Verhaeltnisse weiterhin abfangen."""
    trk = _trk("A", 0.0, 0.0, area=100.0)
    det = _det(0, 1.0, 0.0, area=100000.0)   # 1000x
    ok, reason = passes_physical_gate(trk, det, 5.0, 150.0)
    assert not ok and "area_ratio" in reason


def test_area_ratio_base_applies_at_normal_takt():
    """Bei 5 min gilt exakt der Basisfaktor — kein Zeitzuschlag."""
    assert _max_area_ratio(5.0) == pytest.approx(10.0)


def test_area_ratio_grows_only_above_normal_takt():
    """Nur Radarluecken oberhalb des Normaltakts erweitern das Gate."""
    assert _max_area_ratio(15.0) == pytest.approx(10.0 * (1.25 ** 10))
    assert _max_area_ratio(3.0) == pytest.approx(10.0), "Kuerzerer Takt darf nicht verengen"


def test_weak_cell_gets_narrow_speed_cap():
    """B365-Kernidee: schwache Zelle -> enger Cap."""
    weak = _trk("W", 0.0, 0.0, core=0.01)
    assert _effective_max_speed(weak, 150.0) == pytest.approx(60.0)


def test_strong_cell_keeps_full_speed_cap():
    strong = _trk("S", 0.0, 0.0, core=0.40)
    assert _effective_max_speed(strong, 150.0) == pytest.approx(150.0)


def test_effective_speed_never_exceeds_configured_max():
    """Ein global engerer Cap darf durch den Schwach-Cap nicht aufgeweitet werden."""
    weak = _trk("W", 0.0, 0.0, core=0.01)
    assert _effective_max_speed(weak, 30.0) == pytest.approx(30.0)


def test_weak_cell_does_not_match_distant_contour():
    """B365-Regression: schwache Zelle darf sich nicht ueber 12.5 km fortsetzen."""
    weak = _trk("WEAKCELL", 0.0, 0.0, vx=100.0, vy=0.0, core=0.01)
    far = _det(0, 12.5, 0.0)      # bei 150 km/h/5min zulaessig, bei 60 km/h nicht
    ok, _ = passes_physical_gate(weak, far, 5.0, 150.0)
    assert not ok, "Schwache Zelle wurde faelschlich mit entfernter Kontur fortgesetzt"


def test_strong_cell_may_match_same_distance():
    """Gegenprobe: dieselbe Distanz ist fuer eine starke Zelle zulaessig."""
    strong = _trk("S", 0.0, 0.0, vx=100.0, vy=0.0, core=0.40)
    far = _det(0, 12.5, 0.0)
    ok, reason = passes_physical_gate(strong, far, 5.0, 150.0)
    assert ok, f"Starke Zelle wurde gegatet: {reason}"


def test_merge_contour_gets_matched_globally():
    """End-to-End: die Merge-Kontur darf nicht `unmatched` bleiben."""
    big = _trk("BIG", 0.0, 0.0, area=6400.0, core=0.3)
    small = _trk("SMALL", 9.0, 0.0, area=900.0, core=0.3)
    merged = _det(0, 3.0, 0.0, area=40000.0)
    res = solve_global_assignment([big, small], [merged], dt_minutes=5.0, max_speed_kmh=150.0)
    assert res.matches, "Merge-Kontur blieb unmatched -> neue ID, B117-Kontinuitaet gebrochen"
    assert res.matches.get(0) == "BIG", "Der dominante Parent muss die Kontur bekommen"
