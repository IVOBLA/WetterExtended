import subprocess
import hydro_static_import as h

def test_convert_uses_bbox_and_layer(monkeypatch, tmp_path):
    out = tmp_path / "out.geojson"
    monkeypatch.setattr(h.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(h, "_extract_if_zip", lambda p: p)
    monkeypatch.setattr(h, "_ogr_layers", lambda p: ["Noise", "AT_DrainageBasin"])
    def fake_run(cmd, **kw):
        out.write_text('{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Polygon","coordinates":[[[13.8,46.62],[14.2,46.62],[14.2,46.88],[13.8,46.88],[13.8,46.62]]]},"properties":{"OBJECTID":1}}]}', encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(h.subprocess, "run", fake_run)
    assert h.convert_to_geojson("in.gml", str(out), "basins")
