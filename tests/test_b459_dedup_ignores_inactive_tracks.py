"""B459: Inaktive/stille Tracks nehmen nicht am Frame-Dedup teil."""
import cell_lineage as cl


def _patch_env(monkeypatch, tmp_path):
    monkeypatch.setattr(cl, "_state_dir", lambda: tmp_path)
    monkeypatch.setattr(
        cl, "_cfg",
        lambda key, default=None: True if key == "CELL_LINEAGE_SPLIT_MERGE_ENABLED" else default,
    )


def test_inactive_track_does_not_steal_active_cell_id(monkeypatch, tmp_path):
    _patch_env(monkeypatch, tmp_path)
    state = cl._empty_state()
    # Korrupte Alt-Zuordnung: aktiver und inaktiver Track teilen dieselbe cell_id.
    state.setdefault("radar_to_cell", {})["ACT"] = "WX-20260101-0005"
    state["radar_to_cell"]["OLD"] = "WX-20260101-0005"
    cl.save_lineage_state(state)

    active = {"id": "ACT", "lineage": "continued",
              "first_seen": "2026-01-01_11-00-00", "is_active_cell": True}
    # Der inaktive Track ist AELTER -- ohne B459 gewaenne er den
    # first_seen-Tiebreak und die aktive Zelle wuerde umgeschluesselt.
    inactive = {"id": "OLD", "lineage": "continued",
                "first_seen": "2026-01-01_09-00-00",
                "is_active_cell": False, "silent_tracking": True,
                "tracking_state": "inactive_rain"}

    events = cl.update_split_merge_lineage(
        [active, inactive], previous_objects={}, timestamp="2026-01-01_11-05-00"
    )

    assert active["cell_id"] == "WX-20260101-0005", "Aktive Zelle wurde umgeschluesselt"
    assert inactive.get("cell_id") == "WX-20260101-0005", "Inaktiver Track wurde angefasst"
    assert [e for e in events if e.get("event_type") == "cell_id_collision_resolved"] == []
    final = cl.load_lineage_state()
    assert final["radar_to_cell"]["ACT"] == "WX-20260101-0005"


def test_two_active_cells_still_deduped(monkeypatch, tmp_path):
    """Regression: der B454-Kernfall bleibt intakt."""
    _patch_env(monkeypatch, tmp_path)
    state = cl._empty_state()
    state.setdefault("radar_to_cell", {})["X1"] = "WX-20260101-0006"
    state["radar_to_cell"]["X2"] = "WX-20260101-0006"
    cl.save_lineage_state(state)

    o1 = {"id": "X1", "lineage": "continued", "first_seen": "2026-01-01_10-00-00",
          "is_active_cell": True}
    o2 = {"id": "X2", "lineage": "continued", "first_seen": "2026-01-01_10-30-00",
          "is_active_cell": True}

    events = cl.update_split_merge_lineage(
        [o1, o2], previous_objects={}, timestamp="2026-01-01_11-05-00"
    )

    assert o1["cell_id"] == "WX-20260101-0006"          # aelterer Track behaelt
    assert o2["cell_id"] != "WX-20260101-0006"
    assert len([e for e in events if e.get("event_type") == "cell_id_collision_resolved"]) == 1
