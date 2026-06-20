import json
import zipfile
from datetime import datetime, timezone

import debug_export


def test_debug_export_includes_hydro_live_impact_status_and_external_responses(tmp_path):
    base = tmp_path
    live = base / "train_data/hydro/live"
    impact = base / "train_data/hydro/impact"
    generated = base / "train_data/hydro/static/generated"
    source = base / "train_data/hydro/static/source"
    external = base / "train_data/external_responses/hydro"
    for p in (live, impact, generated, source, external):
        p.mkdir(parents=True)
    (live / "hydro_status.json").write_text(json.dumps({"ok": False, "error": "offline"}), encoding="utf-8")
    (impact / "latest_hydro_impacts.json").write_text("[]", encoding="utf-8")
    (generated / "hydro_static_status.json").write_text(json.dumps({"status": "hydro_static_missing"}), encoding="utf-8")
    (external / "failed_response.json").write_text(json.dumps({"service": "hydro", "error": "timeout"}), encoding="utf-8")
    (source / "huge_basins.geojson").write_text("{}", encoding="utf-8")

    zpath, _, manifest = debug_export.create_debug_export_zip(base_dir=base, now=datetime.now(timezone.utc))
    with zipfile.ZipFile(zpath) as zf:
        names = zf.namelist()
    joined = "\n".join(names)
    assert "external_responses/hydro/hydro_status.json" in joined
    assert "hydro_impact/latest_hydro_impacts.json" in joined
    assert "hydro_static/hydro_static_status.json" in joined
    assert "external_responses/hydro/failed_response.json" in joined
    assert "huge_basins.geojson" not in joined
    assert "hydro" in manifest["external_sources_detected"]



def _zip_names_and_root(zpath):
    with zipfile.ZipFile(zpath) as zf:
        names = zf.namelist()
    root = names[0].split('/')[0]
    return names, root


def test_hydro_live_is_mirrored_to_train_data_hydro_live(tmp_path):
    live = tmp_path / "train_data/hydro/live"
    live.mkdir(parents=True)
    (live / "latest_hydro.json").write_text('{"ok": true}', encoding="utf-8")
    (live / "hydro_status.json").write_text('{"ok": true}', encoding="utf-8")
    zpath, _, _ = debug_export.create_debug_export_zip(base_dir=tmp_path, now=datetime.now(timezone.utc))
    names, _ = _zip_names_and_root(zpath)
    joined = "\n".join(names)
    assert "external_responses/hydro/latest_hydro.json" in joined
    assert "external_responses/hydro/hydro_status.json" in joined
    assert "train_data/hydro/live/latest_hydro.json" in joined
    assert "train_data/hydro/live/hydro_status.json" in joined
    assert "train_data/hydro/status/hydro_export_status.json" in joined


def test_no_hydro_impacts_writes_empty_marker(tmp_path):
    (tmp_path / "train_data/hydro/impact").mkdir(parents=True)
    zpath, _, _ = debug_export.create_debug_export_zip(base_dir=tmp_path, now=datetime.now(timezone.utc))
    with zipfile.ZipFile(zpath) as zf:
        status_name = next(n for n in zf.namelist() if n.endswith("train_data/hydro/impact/hydro_impact_status.json"))
        status = json.loads(zf.read(status_name))
        names = zf.namelist()
    assert status["available"] is False
    assert status["impact_count"] == 0
    assert status["reason"] == "no_hydro_impacts_in_export_window"
    assert not any(n.endswith("train_data/hydro/impact/latest_hydro_impacts.json") for n in names)


def test_hydro_impacts_are_exported_with_status(tmp_path):
    impact = tmp_path / "train_data/hydro/impact"
    impact.mkdir(parents=True)
    (impact / "latest_hydro_impacts.json").write_text('[{"id": 1}]', encoding="utf-8")
    (impact / "hydro_impact_state.json").write_text('{"ok": true}', encoding="utf-8")
    (impact / "hydro_impact_events.jsonl").write_text('{"id": 1}\n', encoding="utf-8")
    zpath, _, _ = debug_export.create_debug_export_zip(base_dir=tmp_path, now=datetime.now(timezone.utc))
    with zipfile.ZipFile(zpath) as zf:
        joined = "\n".join(zf.namelist())
        status = json.loads(zf.read(next(n for n in zf.namelist() if n.endswith("train_data/hydro/status/hydro_export_status.json"))))
    assert "train_data/hydro/impact/latest_hydro_impacts.json" in joined
    assert "train_data/hydro/impact/hydro_impact_state.json" in joined
    assert status["hydro_impact_available"] is True


def test_missing_static_data_does_not_abort(tmp_path):
    zpath, _, _ = debug_export.create_debug_export_zip(base_dir=tmp_path, now=datetime.now(timezone.utc))
    with zipfile.ZipFile(zpath) as zf:
        status = json.loads(zf.read(next(n for n in zf.namelist() if n.endswith("train_data/hydro/static/hydro_static_status.json"))))
    assert status["available"] is False


def test_invalid_hydro_json_is_documented(tmp_path):
    impact = tmp_path / "train_data/hydro/impact"
    impact.mkdir(parents=True)
    (impact / "latest_hydro_impacts.json").write_text('{bad', encoding="utf-8")
    zpath, _, _ = debug_export.create_debug_export_zip(base_dir=tmp_path, now=datetime.now(timezone.utc))
    with zipfile.ZipFile(zpath) as zf:
        errors = json.loads(zf.read(next(n for n in zf.namelist() if n.endswith("train_data/hydro/status/hydro_export_errors.json"))))
    assert errors["ok"] is False
    assert errors["errors"]


def test_full_hydro_export_has_external_and_train_data(tmp_path):
    live = tmp_path / "train_data/hydro/live"
    live.mkdir(parents=True)
    (live / "latest_hydro.json").write_text('{"ok": true}', encoding="utf-8")
    zpath, _, _ = debug_export.create_debug_export_zip(base_dir=tmp_path, now=datetime.now(timezone.utc))
    names, _ = _zip_names_and_root(zpath)
    joined = "\n".join(names)
    assert "external_responses/hydro/" in joined
    assert "train_data/hydro/" in joined
