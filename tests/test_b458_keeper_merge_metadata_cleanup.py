"""B458: Nach der Umschluesselung traegt der Keeper keine Metadaten DIESES Merges mehr."""
import cell_lineage as cl


def _patch_env(monkeypatch, tmp_path):
    monkeypatch.setattr(cl, "_state_dir", lambda: tmp_path)
    monkeypatch.setattr(
        cl, "_cfg",
        lambda key, default=None: True if key == "CELL_LINEAGE_SPLIT_MERGE_ENABLED" else default,
    )


def test_keeper_metadata_of_this_merge_removed_old_history_kept(monkeypatch, tmp_path):
    _patch_env(monkeypatch, tmp_path)
    state = cl._empty_state()
    state.setdefault("radar_to_cell", {})["A"] = "WX-20260101-0001"
    state["radar_to_cell"]["C"] = "WX-20260101-0002"
    # ECHTE, aeltere Merge-Historie des Keepers -- muss ueberleben:
    state.setdefault("cells", {})["WX-20260101-0001"] = {
        "cell_id": "WX-20260101-0001",
        "merged_from_cell_ids": ["WX-20251231-0009"],
        "alias_cell_ids": ["WX-20251231-0009"],
        "lineage_events": [
            {"event_type": "cell_merge", "event_signature": "alte-signatur",
             "merged_from_cell_ids": ["WX-20251231-0009"]}
        ],
    }
    cl.save_lineage_state(state)

    prev = {
        "A": {"id": "A", "cell_id": "WX-20260101-0001", "first_seen": "2026-01-01_10-00-00"},
        "C": {"id": "C", "cell_id": "WX-20260101-0002", "first_seen": "2026-01-01_10-05-00"},
    }
    obj_a = {"id": "A", "lineage": "continued", "first_seen": "2026-01-01_10-00-00"}
    obj_b = {
        "id": "B", "lineage": "merged", "parents": ["A", "C"],
        "cell_id": "WX-20260101-0001", "first_seen": "2026-01-01_10-10-00",
    }

    cl.update_split_merge_lineage([obj_a, obj_b], previous_objects=prev,
                                  timestamp="2026-01-01_10-15-00")
    final = cl.load_lineage_state()

    keeper = final["cells"]["WX-20260101-0001"]
    # Metadaten DIESES Merges sind vom Keeper entfernt:
    assert "WX-20260101-0001" not in (keeper.get("merged_from_cell_ids") or [])
    assert "WX-20260101-0002" not in (keeper.get("merged_from_cell_ids") or [])
    assert "WX-20260101-0002" not in (keeper.get("alias_cell_ids") or [])
    assert not any(
        e.get("event_type") == "cell_merge"
        and set(e.get("merged_from_cell_ids") or []) == {"WX-20260101-0001", "WX-20260101-0002"}
        for e in keeper.get("lineage_events") or []
    ), "cell_merge-Event dieses Merges klebt noch am Keeper"
    # Aeltere, echte Historie bleibt unangetastet:
    assert "WX-20251231-0009" in keeper.get("merged_from_cell_ids", [])
    assert "WX-20251231-0009" in keeper.get("alias_cell_ids", [])
    assert any(e.get("event_signature") == "alte-signatur"
               for e in keeper.get("lineage_events") or [])
    # Der Survivor-Datensatz traegt die Merge-Metadaten dieses Merges:
    new_cell = final["cells"][obj_b["cell_id"]]
    assert set(new_cell.get("merged_from_cell_ids") or []) >= {"WX-20260101-0001", "WX-20260101-0002"}
