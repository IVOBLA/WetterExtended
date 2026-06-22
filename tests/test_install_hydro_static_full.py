from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def test_full_install_contains_hydro_static_auto_phase():
    s = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "Phase 6a — Hydro-Static automatisch installieren" in s
    assert 'hydro_static_import.py" --auto' in s
    assert "ogr2ogr --version" in s and "ogrinfo --version" in s


def test_full_install_runs_feldkirchen_coverage_check():
    s = open("install.sh", encoding="utf-8").read()
    assert 'hydro_static_import.py" --check-coverage feldkirchen' in s
