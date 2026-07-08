"""
B321: compute_radar_ingest_gaps() ordnet Erwartungsslots per Naechste-Nachbar-
Zuordnung (Toleranz interval_min/2) statt per exaktem Set-Vergleich zu, und
coverage_ratio ist auf [0.0, 1.0] geklammert.
"""
import os
from datetime import datetime, timedelta

import pytest

db = pytest.importorskip("dataset_builder")


def _touch(path, dt):
    path.touch()
    ts = dt.timestamp()
    os.utime(path, (ts, ts))


def test_phase_shifted_frames_are_not_falsely_missing(monkeypatch, tmp_path):
    radar_dir = tmp_path / "radar"
    radar_dir.mkdir()
    monkeypatch.setitem(db.SAVE_PATHS, "radar", str(radar_dir))

    now = datetime.utcnow().replace(second=0, microsecond=0)
    # Reale Frames auf Phase :05/:20/:35/:50 relativ zur vollen Stunde, ueber 2h.
    base = now.replace(minute=0) - timedelta(hours=2)
    offsets = [5, 20, 35, 50, 65, 80, 95, 110]
    for off in offsets:
        ts = base + timedelta(minutes=off)
        _touch(radar_dir / f"{ts.strftime('%Y-%m-%d_%H-%M-%S')}.png", ts)

    result = db.compute_radar_ingest_gaps(15, hours=3)
    # Bei korrekter Toleranz-Zuordnung sollten kaum/keine der vorhandenen
    # Frame-Zeitpunkte selbst als Luecke erscheinen.
    missing_set = set(result["missing_timestamps"])
    for off in offsets:
        ts = base + timedelta(minutes=off)
        slot_str = ts.strftime("%Y-%m-%dT%H:%M")
        assert slot_str not in missing_set, f"{slot_str} faelschlich als missing markiert"


def test_coverage_ratio_never_exceeds_one(monkeypatch, tmp_path):
    radar_dir = tmp_path / "radar"
    radar_dir.mkdir()
    monkeypatch.setitem(db.SAVE_PATHS, "radar", str(radar_dir))

    now = datetime.utcnow().replace(second=0, microsecond=0)
    base = now - timedelta(hours=1)
    # Sehr feine Kadenz (alle 2 Minuten) gegen ein grobes 15-min-Erwartungsraster.
    for i in range(30):
        ts = base + timedelta(minutes=2 * i)
        _touch(radar_dir / f"{ts.strftime('%Y-%m-%d_%H-%M-%S')}.png", ts)

    result = db.compute_radar_ingest_gaps(15, hours=2)
    assert result["coverage_ratio"] is not None
    assert result["coverage_ratio"] <= 1.0


def test_real_gap_still_detected(monkeypatch, tmp_path):
    radar_dir = tmp_path / "radar"
    radar_dir.mkdir()
    monkeypatch.setitem(db.SAVE_PATHS, "radar", str(radar_dir))

    now = datetime.utcnow().replace(second=0, microsecond=0)
    base = now.replace(minute=0) - timedelta(hours=3)
    # Frames in der ersten Stunde und danach erst wieder nach einer echten 2h-Luecke.
    for off in (5, 20, 35, 50, 180):
        ts = base + timedelta(minutes=off)
        _touch(radar_dir / f"{ts.strftime('%Y-%m-%d_%H-%M-%S')}.png", ts)

    result = db.compute_radar_ingest_gaps(15, hours=4)
    assert len(result["missing_timestamps"]) > 0
    assert result["longest_gap_min"] >= 60
