"""B429: Der automatisch erstellte Debug-Export muss im Admin-Panel ankommen."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tools" / "publish_latest_debug_export_branch.py"


@pytest.fixture
def publisher(monkeypatch):
    spec = importlib.util.spec_from_file_location("publish_latest_debug_export_branch_b429", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_publisher_persists_for_admin_panel(publisher):
    """Regressionsanker: ohne diesen Aufruf ist der automatische Export unauffindbar."""
    assert hasattr(publisher, "persist_for_admin_panel")
    source = TOOL_PATH.read_text(encoding="utf-8")
    assert "persist_for_admin_panel(parts, export_manifest, args.repo_dir)" in source


def test_persist_runs_before_push(publisher):
    """Der Push darf scheitern dürfen — der lokale Download muss dann schon existieren."""
    source = TOOL_PATH.read_text(encoding="utf-8")
    persist_at = source.index("persist_for_admin_panel(parts, export_manifest, args.repo_dir)")
    push_at = source.index('run_git(["push", "--force", "origin", refspec]')
    assert persist_at < push_at, "Persistenz muss vor dem Push stehen"


def test_export_reason_marks_scheduled_origin(publisher, monkeypatch, tmp_path):
    captured = {}

    def fake_create_volumes(**kwargs):
        captured.update(kwargs)
        return [(tmp_path / "wetterextended_debug1.zip", "wetterextended_debug1.zip")], {
            "created_at": "2026-07-17T23:59:00+00:00", "export_reason": "last_24h_debug_run", "part_count": 1}

    fake_config = type(sys)("config")
    fake_config.SAVE_PATHS = {"evaluation": "train_data/evaluation/"}
    fake_debug_export = type(sys)("debug_export")
    fake_debug_export.create_debug_export_volumes = fake_create_volumes
    fake_debug_export.persist_latest_export = lambda *a, **k: {}
    monkeypatch.setitem(sys.modules, "config", fake_config)
    monkeypatch.setitem(sys.modules, "debug_export", fake_debug_export)

    _parts, manifest = publisher.create_export(tmp_path, 24, 512, 90)
    assert manifest["export_reason"] == publisher.EXPORT_REASON_SCHEDULED == "scheduled_branch_publish"
    assert manifest["created_at"] == "2026-07-17T23:59:00+00:00", "übrige Manifest-Felder bleiben unberührt"


def test_persist_target_matches_app_resolution(publisher, monkeypatch, tmp_path):
    """Schreibt das Tool woanders hin als app.py liest, ist der Fix wirkungslos."""
    monkeypatch.delenv("WETTEREXTENDED_EXPORT_BASE_DIR", raising=False)
    assert publisher._export_base_dir(tmp_path) == tmp_path.resolve()
    other = tmp_path / "anders"
    other.mkdir()
    monkeypatch.setenv("WETTEREXTENDED_EXPORT_BASE_DIR", str(other))
    assert publisher._export_base_dir(tmp_path) == other.resolve()


def test_persist_failure_does_not_stop_push(publisher, monkeypatch, tmp_path):
    fake_config = type(sys)("config")
    fake_config.SAVE_PATHS = {"evaluation": "train_data/evaluation/"}
    fake_debug_export = type(sys)("debug_export")

    def boom(*_a, **_k):
        raise OSError("kein Platz auf dem Gerät")

    fake_debug_export.persist_latest_export = boom
    monkeypatch.setitem(sys.modules, "config", fake_config)
    monkeypatch.setitem(sys.modules, "debug_export", fake_debug_export)
    assert publisher.persist_for_admin_panel([], {}, tmp_path) is None


def test_persisted_export_is_readable_by_admin_route(tmp_path, monkeypatch):
    """Ende-zu-Ende auf Dateiebene: was der Publisher schreibt, muss die Route finden."""
    debug_export = pytest.importorskip("debug_export")
    save_paths = {"evaluation": "train_data/evaluation/"}
    part = tmp_path / "wetterextended_debug1.zip"
    part.write_bytes(b"PK\x05\x06" + b"\x00" * 18)
    meta = debug_export.persist_latest_export(
        [(part, "wetterextended_debug1.zip")],
        {"created_at": "2026-07-17T23:59:00+00:00", "export_reason": "scheduled_branch_publish"},
        save_paths=save_paths, base_dir=tmp_path)
    assert meta["export_reason"] == "scheduled_branch_publish"
    loaded = debug_export.load_latest_export_meta(save_paths=save_paths, base_dir=tmp_path)
    assert loaded and loaded["part_count"] == 1
    assert debug_export.latest_export_part_path(1, save_paths=save_paths, base_dir=tmp_path).exists()


def test_frontend_shows_origin():
    jsx = (REPO_ROOT / "frontend" / "src" / "pages" / "Logs.jsx").read_text(encoding="utf-8")
    assert "scheduled_branch_publish" in jsx, "Herkunft des angebotenen Exports muss sichtbar sein"
