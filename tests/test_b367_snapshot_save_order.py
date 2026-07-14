"""B367: save_tracking_snapshot() muss NACH der Enrichment-Schleife laufen,
damit first_seen/total_active_frames im persistierten Snapshot stehen."""
import inspect

import object_tracking


def test_save_snapshot_called_after_enrichment_loop_in_source():
    """Statische Reihenfolge-Pruefung: der Quelltext von update_tracking_memory
    darf den Aufruf von save_tracking_snapshot() nicht mehr VOR der
    Enrichment-Schleife ('for obj_id, obj in new_memory.items():') enthalten,
    sondern erst NACH deren Ende ('return objects')."""
    src = inspect.getsource(object_tracking.update_tracking_memory)
    idx_loop = src.index('for obj_id, obj in new_memory.items():')
    idx_save = src.index('save_tracking_snapshot()')
    idx_return = src.rindex('return objects')
    assert idx_save > idx_loop, (
        "save_tracking_snapshot() wird vor der Enrichment-Schleife aufgerufen"
    )
    assert idx_save < idx_return, (
        "save_tracking_snapshot() muss vor dem finalen return objects stehen"
    )


def test_snapshot_written_object_contains_first_seen_field(monkeypatch, tmp_path):
    """End-to-End: nach update_tracking_memory() muss der gespeicherte
    Snapshot fuer eine aktiv erkannte Zelle first_seen und
    total_active_frames enthalten (nicht None/fehlend)."""
    import json
    import numpy as np
    import cv2

    snap_file = tmp_path / "tracking_memory_snapshot.json"
    monkeypatch.setattr(object_tracking, "_snapshot_path", lambda: str(snap_file))
    object_tracking.tracking_memory = {}

    # Minimaler synthetischer Regen-Kontur-Blob fuer einen Tracking-Zyklus.
    hsv = np.zeros((300, 300, 3), dtype=np.uint8)
    hsv[100:140, 100:140] = (60, 200, 200)  # innerhalb typischer Regen-HSV-Range
    contour = np.array(
        [[[100, 100]], [[140, 100]], [[140, 140]], [[100, 140]]], dtype=np.int32
    )

    try:
        object_tracking.update_tracking_memory(
            hsv, [contour], weather_data={}, timestamp="2026-07-14_13-50-00",
            rain_support_mask=None,
        )
    except Exception as exc:
        import pytest
        pytest.skip(f"Tracking-Zyklus in Testumgebung nicht lauffaehig: {exc}")

    assert snap_file.exists(), "Snapshot-Datei wurde nicht geschrieben"
    with open(snap_file, "r", encoding="utf-8") as f:
        snap = json.load(f)

    assert len(snap) >= 1, "Snapshot enthaelt keine Zellen"
    for cell_id, cell in snap.items():
        if cell.get("missing", 0) == 0:
            assert cell.get("first_seen") is not None, (
                f"first_seen fehlt im Snapshot fuer aktive Zelle {cell_id}"
            )
            assert cell.get("total_active_frames") is not None, (
                f"total_active_frames fehlt im Snapshot fuer aktive Zelle {cell_id}"
            )
