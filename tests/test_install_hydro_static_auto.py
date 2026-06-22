from pathlib import Path


def test_install_full_delete_list_preserves_statistics_and_hydro_static():
    script = Path("install.sh").read_text(encoding="utf-8")
    start = script.index("FULL_DELETE_DIRS=(")
    end = script.index(")", start)
    block = script[start:end]
    assert "train_data/statistics" not in block
    assert "train_data/hydro" not in block
    assert "train_data/hydro/static" not in block


def test_install_full_hydro_phase_uses_auto_import_and_required_tools():
    script = Path("install.sh").read_text(encoding="utf-8")
    assert "HYDRO_STATIC_PKGS=(gdal-bin unzip curl jq)" in script
    assert "HYDRO_AUTO_ARGS=(--auto)" in script
    assert "HYDRO_AUTO_ARGS+=(--force)" in script
    assert "hydro_static_import.py" in script
    assert "note_manual" in script
