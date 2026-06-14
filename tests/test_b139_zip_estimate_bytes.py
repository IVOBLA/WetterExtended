"""B139: ZIP-Overhead-Schätzung nutzt UTF-8-Bytelänge des Namens (nicht Zeichen),
sodass Volumes mit Sonderzeichen/Emoji im Pfad das Größenlimit nicht überschreiten."""
import os
import zipfile
from pathlib import Path

import pytest

import debug_export
from debug_export import ExportCandidate


def test_estimate_uses_utf8_byte_length():
    name = "äöü€/radar.png"          # 'äöü€' = 9 UTF-8-Bytes vs 4 Zeichen
    est = debug_export._estimated_zip_entry_bytes(b"x", name)
    n_bytes = len(name.encode("utf-8"))
    # Mindestens Overhead + 2× Bytelänge (lokaler Header + Central Directory)
    assert est >= debug_export._ZIP_ENTRY_OVERHEAD + 2 * n_bytes
    # Strikt größer als die frühere (fehlerhafte) Zeichen-Schätzung
    assert est > debug_export._ZIP_ENTRY_OVERHEAD + 2 * len(name)


def test_ascii_name_unchanged():
    name = "evaluation/objects_2026-06-14_18-20-00.json"
    est = debug_export._estimated_zip_entry_bytes(b"", name)
    # ASCII: Bytelänge == Zeichenanzahl → keine Verschlechterung
    assert est >= debug_export._ZIP_ENTRY_OVERHEAD + 2 * len(name)


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


def test_volumes_with_nonascii_names_respect_limit(tmp_path, monkeypatch):
    """Viele inkompressible Dateien mit Umlaut-Pfaden → jedes Volume <= Limit."""
    cands = []
    for k in range(8):
        # langer Nicht-ASCII-Pfad → maximaler Header-Byte-Effekt
        sub = tmp_path / f"kärnten_zellüberwachung_{k}"
        sub.mkdir()
        p = sub / f"radarüberlagerung_2026-06-14_18-{10+k:02d}-00_€.bin"
        p.write_bytes(os.urandom(1024 * 1024))  # 1 MB inkompressibel
        arc = Path("imäges") / sub.name / p.name
        cands.append(ExportCandidate(p, "images", arc, False))
    monkeypatch.setattr(
        debug_export, "_build_candidates_with_diagnostics",
        lambda base_dir, save_paths: (cands, {
            "candidates_count": len(cands),
            "scanned_roots": [],
            "excluded_files_count": 0,
        }),
    )
    out = tmp_path / "vol"
    limit = 2 * 1024 * 1024
    parts, _ = debug_export.create_debug_export_volumes(
        base_dir=tmp_path, save_paths={}, hours=24,
        volume_max_bytes=limit, out_dir=out,
    )
    for p, _n in parts:
        assert os.path.getsize(p) <= limit, f"{p.name}: {os.path.getsize(p)} > {limit}"
    # Verlustfrei: alle Quelldateien vorhanden
    seen = set()
    for p, _n in parts:
        with zipfile.ZipFile(p) as zf:
            seen.update(zf.namelist())
    for c in cands:
        assert any(c.src.name in s for s in seen)
