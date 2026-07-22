"""B454: cell_id-Eindeutigkeit pro Frame; radar_to_cell-Hygiene bei Merges."""
import cell_lineage as cl


def _patch_env(monkeypatch, tmp_path):
    monkeypatch.setattr(cl, "_state_dir", lambda: tmp_path)
    monkeypatch.setattr(
        cl, "_cfg",
        lambda key, default=None: True if key == "CELL_LINEAGE_SPLIT_MERGE_ENABLED" else default,
    )


def test_collision_resolved_and_consumed_parent_mapping_removed(monkeypatch, tmp_path):
    _patch_env(monkeypatch, tmp_path)
    state = cl._empty_state()
    state.setdefault("radar_to_cell", {})["A"] = "WX-20260101-0001"
    state["radar_to_cell"]["C"] = "WX-20260101-0002"
    cl.save_lineage_state(state)

    prev = {
        "A": {"id": "A", "cell_id": "WX-20260101-0001", "first_seen": "2026-01-01_10-00-00"},
        "C": {"id": "C", "cell_id": "WX-20260101-0002", "first_seen": "2026-01-01_10-05-00"},
    }
    obj_a = {"id": "A", "lineage": "continued", "first_seen": "2026-01-01_10-00-00"}
    # Produktionsfall: der Merge-Survivor traegt die geerbte cell_id des
    # weiterlebenden Parents A bereits am Objekt.
    obj_b = {
        "id": "B",
        "lineage": "merged",
        "parents": ["A", "C"],
        "cell_id": "WX-20260101-0001",
        "first_seen": "2026-01-01_10-10-00",
    }

    events = cl.update_split_merge_lineage(
        [obj_a, obj_b], previous_objects=prev, timestamp="2026-01-01_10-15-00"
    )

    # Genau EIN lebendes Objekt traegt die urspruengliche cell_id -- der
    # weiterlebende Parent (continued) behaelt sie, der Merge-Survivor wird
    # umgeschluesselt.
    assert obj_a["cell_id"] == "WX-20260101-0001"
    assert obj_b["cell_id"] != "WX-20260101-0001"
    assert str(obj_b["cell_id"]).startswith("WX-")

    final = cl.load_lineage_state()
    r2c = final.get("radar_to_cell", {})
    assert r2c.get("A") == "WX-20260101-0001"
    assert r2c.get("B") == obj_b["cell_id"]
    # Konsumierter Parent C (nicht mehr im Frame) ist aus radar_to_cell entfernt.
    assert "C" not in r2c

    collisions = [e for e in events if e.get("event_type") == "cell_id_collision_resolved"]
    assert len(collisions) == 1
    assert collisions[0]["previous_cell_id"] == "WX-20260101-0001"
    assert collisions[0]["radar_track_id"] == "B"
    assert collisions[0]["kept_by_radar_track_id"] == "A"

    # Eltern-Verknuepfung darf durch die Umschluesselung NICHT verloren gehen:
    # 1) Objekt-Level: record_cell_merge hat merged_from_cell_ids gesetzt.
    assert set(obj_b.get("merged_from_cell_ids") or []) == {"WX-20260101-0001", "WX-20260101-0002"}
    # 2) Neuer Zellen-Datensatz traegt die Merge-Lineage.
    new_cell = final["cells"][obj_b["cell_id"]]
    assert set(new_cell.get("merged_from_cell_ids") or []) >= {"WX-20260101-0001", "WX-20260101-0002"}
    # 3) Konsumierter Parent C zeigt auf die NEUE Survivor-ID, nicht auf die
    #    beim lebenden Parent A verbliebene alte ID.
    assert final["cells"]["WX-20260101-0002"]["merged_into_cell_id"] == obj_b["cell_id"]
    # 4) Lebender Parent A wurde nicht als konsumiert markiert.
    #    Achtung: _ensure_cell_defaults setzt den Key immer (Default None) --
    #    daher auf None pruefen, nicht auf Key-Abwesenheit.
    assert final["cells"]["WX-20260101-0001"].get("merged_into_cell_id") is None
    # 5) Kollisionsevent traegt die Eltern-Referenz.
    assert set(collisions[0].get("merged_from_cell_ids") or []) == {"WX-20260101-0001", "WX-20260101-0002"}


def test_no_dedup_without_collision(monkeypatch, tmp_path):
    _patch_env(monkeypatch, tmp_path)
    cl.save_lineage_state(cl._empty_state())
    obj1 = {"id": "X1", "lineage": "continued", "cell_id": "WX-20260101-0011", "first_seen": "2026-01-01_10-00-00"}
    obj2 = {"id": "X2", "lineage": "continued", "cell_id": "WX-20260101-0012", "first_seen": "2026-01-01_10-00-00"}
    events = cl.update_split_merge_lineage([obj1, obj2], previous_objects={}, timestamp="2026-01-01_10-15-00")
    assert obj1["cell_id"] == "WX-20260101-0011"
    assert obj2["cell_id"] == "WX-20260101-0012"
    assert [e for e in events if e.get("event_type") == "cell_id_collision_resolved"] == []
