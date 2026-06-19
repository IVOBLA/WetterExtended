from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _install_sh() -> str:
    return (ROOT / "install.sh").read_text(encoding="utf-8")


def test_install_creates_hydro_directory_tree():
    src = _install_sh()
    for rel in (
        "train_data/hydro/static",
        "train_data/hydro/static/source",
        "train_data/hydro/static/generated",
        "train_data/hydro/live",
        "train_data/hydro/impact",
    ):
        assert rel in src


def test_full_install_preserves_hydro_and_statistics():
    src = _install_sh()
    delete_block = src.split("FULL_DELETE_DIRS=(", 1)[1].split(")", 1)[0]
    assert "train_data/hydro" not in delete_block
    assert "train_data/statistics" not in delete_block
    assert "train_data/hydro/       (Hydro-Live-/Impactdaten" in src


def test_missing_static_hydro_data_is_warned_not_fatal():
    src = _install_sh()
    assert "Hydro-Impact benötigt lokale Gewässer-/Einzugsgebietsdaten." in src
    assert "Installation wird fortgesetzt" in src
    assert "exit 1" not in src.split("Hydro-Impact benötigt lokale Gewässer-/Einzugsgebietsdaten.", 1)[1].split("INITIAL_MODEL_SOURCE", 1)[0]
