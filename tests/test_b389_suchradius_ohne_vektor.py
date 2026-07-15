"""B389: Ohne bekannten Bewegungsvektor gilt der WEITERE Radius, nicht der engere."""
import pytest

from tracking.association import (
    DetectionCandidate,
    TrackCandidate,
    _search_radii_km,
    passes_physical_gate,
)


def _trk(tid="A", vx=0.0, vy=0.0, core=0.3, age=5, area=1000.0):
    return TrackCandidate(track_id=tid, pred_x_km=0.0, pred_y_km=0.0, vx_kmh=vx, vy_kmh=vy,
                          area_px=area, core_ratio=core, age_frames=age)


def _det(x, y=0.0, area=1000.0):
    return DetectionCandidate(index=0, x_km=x, y_km=y, area_px=area, core_ratio=0.3)


def test_isotropic_radius_uses_longitudinal_not_cross():
    """KERNREGRESSION: ohne Vektor muss a_km gelten (14.5 km), nicht b_km (7.62 km)."""
    a, b, ux, uy = _search_radii_km(_trk(vx=0.0, vy=0.0), dt_minutes=5.0, max_speed_kmh=150.0)
    assert a == b, "Ohne Vektor muss der Suchraum isotrop sein"
    assert a == pytest.approx(14.5, abs=0.1), f"Radius {a:.2f} km — erwartet 14.5 km (reach+base)"


def test_isotropic_radius_matches_configured_cap():
    """Der Radius darf nicht enger sein als der konfigurierte Geschwindigkeits-Cap."""
    reach = 150.0 * (5.0 / 60.0)
    a, _, _, _ = _search_radii_km(_trk(), dt_minutes=5.0, max_speed_kmh=150.0)
    assert a >= reach, f"Radius {a:.2f} km < Cap-Reichweite {reach:.2f} km — Zelle kann nicht folgen"


def test_moving_track_keeps_narrow_cross_radius():
    """Regression: MIT Vektor bleibt der Querradius eng (B373-Kernidee)."""
    a, b, ux, uy = _search_radii_km(_trk(vx=100.0, vy=0.0), dt_minutes=5.0, max_speed_kmh=150.0)
    assert b < a, "Mit bekanntem Vektor muss quer enger sein als laengs"
    assert b == pytest.approx(7.62, abs=0.1)
    assert (ux, uy) == pytest.approx((1.0, 0.0))


def test_stationary_strong_cell_matches_at_ten_km():
    """Eine stehende starke Zelle muss 10 km weit zugeordnet werden koennen."""
    ok, reason = passes_physical_gate(_trk(core=0.2), _det(10.0), dt_minutes=5.0, max_speed_kmh=150.0)
    assert ok, f"Starke Zelle ohne Vektor bei 10 km gegatet: {reason}"


def test_stationary_weak_cell_still_gated_at_ten_km():
    """B379-Schwach-Cap bleibt wirksam: 60 km/h -> 7.0 km Radius."""
    ok, reason = passes_physical_gate(_trk(core=0.0), _det(10.0), dt_minutes=5.0, max_speed_kmh=150.0)
    assert not ok, "Schwache Zelle wurde bei 10 km faelschlich zugeordnet"
    assert "outside_search_ellipse" in reason


def test_weak_isotropic_radius_is_seven_km():
    a, b, _, _ = _search_radii_km(_trk(core=0.0), dt_minutes=5.0, max_speed_kmh=60.0)
    assert a == b == pytest.approx(7.0, abs=0.1)


def test_absurd_distance_still_gated_without_vector():
    """Der Fix darf das Gate nicht aufheben."""
    ok, _ = passes_physical_gate(_trk(core=0.2), _det(50.0), dt_minutes=5.0, max_speed_kmh=150.0)
    assert not ok


def test_isotropic_radius_scales_with_real_dt():
    """Bei 15 min Radarluecke muss der Radius entsprechend wachsen."""
    a5, _, _, _ = _search_radii_km(_trk(), dt_minutes=5.0, max_speed_kmh=150.0)
    a15, _, _, _ = _search_radii_km(_trk(), dt_minutes=15.0, max_speed_kmh=150.0)
    assert a15 > a5
    assert a15 == pytest.approx(150.0 * 0.25 + 2.0, abs=0.1)


def test_direction_unit_vector_is_neutral_without_motion():
    _, _, ux, uy = _search_radii_km(_trk(), dt_minutes=5.0, max_speed_kmh=150.0)
    assert (ux, uy) == (1.0, 0.0), "Neutraler Richtungsvektor erwartet"
