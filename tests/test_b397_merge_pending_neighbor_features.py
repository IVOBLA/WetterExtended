"""B397: merge_pending darf B94-/ML-Nachbarfeatures nicht beeinflussen."""

from pathlib import Path

import pytest

import object_tracking as ot


_NEUTRAL = {
    "neighbor_count_ahead": 0.0,
    "neighbor_max_core_ahead": 0.0,
    "neighbor_min_dist_km_ahead": 999.0,
    "strat_area_ahead_px": 0.0,
}


def _obj(
    obj_id,
    *,
    lat=46.70,
    lon=14.30,
    vx=10.0,
    vy=0.0,
    core_ratio=0.20,
    strat_area_px=100.0,
    tracking_state="active",
    silent_tracking=False,
):
    return {
        "id": obj_id,
        "lat": lat,
        "lon": lon,
        "vx": vx,
        "vy": vy,
        "core_ratio": core_ratio,
        "strat_area_px": strat_area_px,
        "tracking_state": tracking_state,
        "silent_tracking": silent_tracking,
    }


def _features(subject, all_objects):
    return ot._compute_neighbor_ahead(
        subject,
        all_objects,
        range_km=20.0,
        half_angle_deg=45.0,
        min_speed_kmh=1.0,
        px_to_kmh=4.0,
        upscale=3.0,
    )


def test_merge_pending_is_not_eligible():
    pending = _obj(
        "PENDING",
        tracking_state="merge_pending",
        silent_tracking=True,
    )
    assert ot._is_neighbor_feature_eligible(pending) is False


def test_active_object_remains_eligible():
    assert ot._is_neighbor_feature_eligible(_obj("ACTIVE")) is True


def test_merge_pending_parent_is_not_counted_as_neighbor():
    active = _obj("ACTIVE")
    pending_ahead = _obj(
        "SECONDARY",
        lon=14.31,
        core_ratio=0.95,
        strat_area_px=5000.0,
        tracking_state="merge_pending",
        silent_tracking=True,
    )

    result = _features(active, [active, pending_ahead])

    assert result == _NEUTRAL


def test_visible_neighbor_is_still_counted():
    active = _obj("ACTIVE")
    visible_ahead = _obj(
        "VISIBLE",
        lon=14.31,
        core_ratio=0.80,
        strat_area_px=700.0,
    )

    result = _features(active, [active, visible_ahead])

    assert result["neighbor_count_ahead"] == 1.0
    assert result["neighbor_max_core_ahead"] == pytest.approx(0.80)
    assert result["neighbor_min_dist_km_ahead"] < 2.0
    assert result["strat_area_ahead_px"] == pytest.approx(700.0)


def test_pending_subject_gets_neutral_features():
    pending = _obj(
        "PENDING",
        tracking_state="merge_pending",
        silent_tracking=True,
    )
    visible = _obj("VISIBLE", lon=14.31)

    assert _features(pending, [pending, visible]) == _NEUTRAL


def test_pending_parent_cannot_inflate_visible_features():
    active = _obj("ACTIVE")
    visible_ahead = _obj(
        "VISIBLE",
        lon=14.31,
        core_ratio=0.40,
        strat_area_px=200.0,
    )
    pending_ahead = _obj(
        "PENDING",
        lon=14.305,
        core_ratio=0.99,
        strat_area_px=9000.0,
        tracking_state="merge_pending",
        silent_tracking=True,
    )

    result = _features(active, [active, visible_ahead, pending_ahead])

    assert result["neighbor_count_ahead"] == 1.0
    assert result["neighbor_max_core_ahead"] == pytest.approx(0.40)
    assert result["strat_area_ahead_px"] == pytest.approx(200.0)


def test_b94_pool_uses_central_eligibility_guard():
    src = Path("object_tracking.py").read_text(encoding="utf-8")

    assert "def _is_neighbor_feature_eligible" in src
    assert "if not _is_neighbor_feature_eligible(other):" in src
    assert "if _is_neighbor_feature_eligible(_o)" in src
