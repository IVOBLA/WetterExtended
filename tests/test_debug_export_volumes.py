"""B128: Aufteilung nach KOMPRIMIERTER Größe (<= volume_max), unkomprimiert egal,
verlustfrei, Dateinamen wetterextended_debug{N}.zip."""
import os
import zipfile
from pathlib import Path

import pytest

import debug_export
from debug_export import ExportCandidate


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


def _diagnostics(cands):
    return {
        "candidates_count": len(cands),
        "scanned_roots": [],
        "excluded_files_count": 0,
    }


def _all_entries(parts):
    names = set()
    for p, _n in parts:
        with zipfile.ZipFile(p) as zf:
            names.update(zf.namelist())
    return names


def test_splits_by_compressed_size_without_loss(tmp_path, monkeypatch):
    """6 INKOMPRESSIBLE 2-MB-Dateien (os.urandom) → Aufteilung nach komprimierter
    Größe; jedes Volume <= Limit, keine Datei verloren."""
    cands = []
    for k in range(5):  # kleine Textdateien (Priorität 0)
        p = tmp_path / f"objects_2026-06-14_18-{10+k:02d}-00.json"
        p.write_text('{"ok": true}\n', encoding="utf-8")
        cands.append(ExportCandidate(p, "evaluation", Path("evaluation") / p.name, True))
    for k in range(6):  # inkompressible Binärdaten → komprimiert ~= 2 MB
        p = tmp_path / f"radar_2026-06-14_18-{10+k:02d}-00.bin"
        p.write_bytes(os.urandom(2 * 1024 * 1024))
        cands.append(ExportCandidate(p, "radar", Path("radar") / p.name, False))
    monkeypatch.setattr(
        debug_export, "_build_candidates_with_diagnostics",
        lambda base_dir, save_paths: (cands, _diagnostics(cands)),
    )
    out = tmp_path / "vol"
    limit = 3 * 1024 * 1024
    parts, manifest = debug_export.create_debug_export_volumes(
        base_dir=tmp_path, save_paths={}, hours=24,
        volume_max_bytes=limit, out_dir=out,
    )
    assert manifest["part_count"] == len(parts) >= 2
    for i, (p, n) in enumerate(parts, start=1):
        assert os.path.getsize(p) <= limit, f"{n}: {os.path.getsize(p)} > {limit}"
        assert n == f"wetterextended_debug{i}.zip", n
    entries = _all_entries(parts)
    for c in cands:
        assert any(c.src.name in e for e in entries), f"{c.src.name} fehlt in allen Volumes"


def test_uncompressed_size_is_irrelevant(tmp_path, monkeypatch):
    """Eine 8-MB-Datei aus Nullen (komprimiert wenige KB) bleibt EIN Volume,
    obwohl die unkomprimierte Größe das 1-MB-Limit weit übersteigt."""
    p = tmp_path / "objects_2026-06-14_18-20-00.json"
    # 8 MB stark komprimierbar (Nullen) → komprimiert << 1 MB
    p.write_bytes(b"\x00" * (8 * 1024 * 1024))
    cands = [ExportCandidate(p, "evaluation", Path("evaluation") / p.name, True)]
    monkeypatch.setattr(
        debug_export, "_build_candidates_with_diagnostics",
        lambda base_dir, save_paths: (cands, _diagnostics(cands)),
    )
    out = tmp_path / "vol_u"
    parts, manifest = debug_export.create_debug_export_volumes(
        base_dir=tmp_path, save_paths={}, hours=24,
        volume_max_bytes=1 * 1024 * 1024, out_dir=out,  # 1 MB Limit
    )
    assert manifest["part_count"] == 1, "komprimierbare Großdatei darf NICHT splitten"
    assert os.path.getsize(parts[0][0]) <= 1 * 1024 * 1024


def test_naming_scheme(tmp_path, monkeypatch):
    p = tmp_path / "objects_2026-06-14_18-20-00.json"
    p.write_text("{}", encoding="utf-8")
    cands = [ExportCandidate(p, "evaluation", Path("evaluation") / p.name, True)]
    monkeypatch.setattr(
        debug_export, "_build_candidates_with_diagnostics",
        lambda base_dir, save_paths: (cands, _diagnostics(cands)),
    )
    out = tmp_path / "vol_n"
    parts, _ = debug_export.create_debug_export_volumes(
        base_dir=tmp_path, save_paths={}, hours=24,
        volume_max_bytes=80 * 1024 * 1024, out_dir=out,
    )
    assert parts[0][1] == "wetterextended_debug1.zip"


def test_never_raises(tmp_path, monkeypatch):
    p = tmp_path / "x.bin"
    p.write_bytes(os.urandom(4 * 1024 * 1024))
    cands = [ExportCandidate(p, "radar", Path("radar") / p.name, True)]
    monkeypatch.setattr(
        debug_export, "_build_candidates_with_diagnostics",
        lambda base_dir, save_paths: (cands, _diagnostics(cands)),
    )
    out = tmp_path / "vol_r"
    try:
        debug_export.create_debug_export_volumes(
            base_dir=tmp_path, save_paths={}, hours=24,
            volume_max_bytes=1024, out_dir=out,
        )
    except debug_export.ExportLimitExceeded as exc:
        pytest.fail(f"ExportLimitExceeded darf nie geworfen werden: {exc}")
