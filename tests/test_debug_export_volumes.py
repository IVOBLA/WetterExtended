"""B126: Verlustfreie Aufteilung des Debug-Exports in <= volume_max-Volumes."""
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

import debug_export
from debug_export import ExportCandidate


def _candidates_with_big_payload(tmp_path):
    files = []
    # 5 kleine Textdateien (Priorität 0)
    for k in range(5):
        p = tmp_path / f"objects_2026-06-14_18-{10+k:02d}-00.json"
        p.write_text('{"ok": true}\n', encoding="utf-8")
        files.append(ExportCandidate(p, "evaluation", Path("evaluation") / p.name, True))
    # 6 Binärdateien je 2 MB (Priorität 1) → mit volume_max=3MB mehrere Volumes
    for k in range(6):
        p = tmp_path / f"radar_2026-06-14_18-{10+k:02d}-00.png"
        p.write_bytes(b"\x01" * (2 * 1024 * 1024))
        files.append(ExportCandidate(p, "radar", Path("radar") / p.name, False))
    return files


@pytest.fixture(autouse=True)
def _no_api_logs(monkeypatch):
    monkeypatch.setattr(
        debug_export, "_write_api_logs_to_zip",
        lambda *a, **k: {
            "files_count": 0,
            "total_bytes": 0,
            "redacted_files": [],
            "included": False,
            "unavailable_reason": None,
            "nginx_logs_included": False,
        },
    )


def _all_entries(parts):
    names = set()
    for p, _n in parts:
        with zipfile.ZipFile(p) as zf:
            names.update(zf.namelist())
    return names


def test_splits_into_multiple_volumes_without_loss(tmp_path, monkeypatch):
    cands = _candidates_with_big_payload(tmp_path)
    monkeypatch.setattr(
        debug_export, "_build_candidates_with_diagnostics",
        lambda base_dir, save_paths: (cands, {"candidates_count": len(cands), "scanned_roots": [], "excluded_files_count": 0}),
    )
    out = tmp_path / "vol"
    parts, manifest = debug_export.create_debug_export_volumes(
        base_dir=tmp_path, save_paths={}, hours=24, now=datetime(2026, 6, 14, 18, 30, tzinfo=timezone.utc),
        volume_max_bytes=3 * 1024 * 1024, out_dir=out,
    )
    # 1) Mehrere Teile entstanden
    assert manifest["part_count"] == len(parts) >= 2
    # 2) Jedes Volume <= Limit (unkomprimiert gepackt → komprimiert garantiert kleiner)
    for p, _n in parts:
        assert p.stat().st_size <= 3 * 1024 * 1024
    # 3) KEINE Datei verloren: alle Quell-Dateinamen tauchen in irgendeinem Teil auf
    entries = _all_entries(parts)
    for c in cands:
        assert any(c.src.name in e for e in entries), f"{c.src.name} fehlt in allen Volumes"
    # 4) Benennung partNNofMM korrekt
    for i, (_p, n) in enumerate(parts, start=1):
        assert f"_part{i:02d}of{len(parts):02d}.zip" in n


def test_single_volume_when_small(tmp_path, monkeypatch):
    p = tmp_path / "objects_2026-06-14_18-20-00.json"
    p.write_text("{}", encoding="utf-8")
    cands = [ExportCandidate(p, "evaluation", Path("evaluation") / p.name, True)]
    monkeypatch.setattr(
        debug_export, "_build_candidates_with_diagnostics",
        lambda base_dir, save_paths: (cands, {"candidates_count": len(cands), "scanned_roots": [], "excluded_files_count": 0}),
    )
    out = tmp_path / "vol1"
    parts, manifest = debug_export.create_debug_export_volumes(
        base_dir=tmp_path, save_paths={}, hours=24, now=datetime(2026, 6, 14, 18, 30, tzinfo=timezone.utc),
        volume_max_bytes=80 * 1024 * 1024, out_dir=out,
    )
    assert manifest["part_count"] == 1
    assert len(parts) == 1


def test_never_raises_export_limit(tmp_path, monkeypatch):
    cands = _candidates_with_big_payload(tmp_path)
    monkeypatch.setattr(
        debug_export, "_build_candidates_with_diagnostics",
        lambda base_dir, save_paths: (cands, {"candidates_count": len(cands), "scanned_roots": [], "excluded_files_count": 0}),
    )
    out = tmp_path / "vol2"
    try:
        debug_export.create_debug_export_volumes(
            base_dir=tmp_path, save_paths={}, hours=24,
            volume_max_bytes=1024, out_dir=out,
        )
    except debug_export.ExportLimitExceeded as exc:
        pytest.fail(f"ExportLimitExceeded darf nie geworfen werden: {exc}")
