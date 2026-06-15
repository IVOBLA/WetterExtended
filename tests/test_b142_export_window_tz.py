"""B142: Export-24h-Fenster zeitzonensicher + keine Datenkürzung (kein B115-Pruning)."""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import debug_export


def _touch(path: Path, *, age_seconds: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    t = datetime.now(timezone.utc).timestamp() - age_seconds
    os.utime(path, (t, t))


def test_recent_vienna_named_frame_is_in_window(tmp_path):
    # Vienna-lokaler Name 2 h "in der Zukunft" relativ zu UTC, mtime aber JETZT.
    p = tmp_path / "radar" / "radar_2026-06-14_23-59-00.png"
    _touch(p, age_seconds=30)
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=24)
    assert debug_export._file_in_window(p, start, now, force=False) is True


def test_too_old_file_excluded(tmp_path):
    p = tmp_path / "objects" / "2026-06-13_10-00-00.json"
    _touch(p, age_seconds=26 * 3600)
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=24)
    assert debug_export._file_in_window(p, start, now, force=False) is False


def test_no_b115_pruning_keeps_all_weather_files(tmp_path):
    """Mehr als 3 Dateien je train_data-Unterverzeichnis bleiben erhalten."""
    base = tmp_path
    save_paths = {"weather": str(base / "train_data" / "weather")}
    weather_dir = base / "train_data" / "weather"
    for i in range(10):
        fp = weather_dir / f"weather_2026-06-14_{i:02d}-00-00.json"
        _touch(fp, age_seconds=120 + i)

    cands, diag = debug_export._build_candidates_with_diagnostics(base, save_paths)
    weather = [c for c in cands if "weather" in str(c.src)]
    assert len(weather) == 10, f"Wetterdaten dürfen nicht auf 3 gekürzt werden (war {len(weather)})"
