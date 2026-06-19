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
