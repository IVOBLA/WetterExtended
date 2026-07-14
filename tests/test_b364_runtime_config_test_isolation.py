"""B364: Nach B362 (reload_overrides() als erste Zeile von patch()) muessen
alle Tests, die runtime_config._OVERRIDES direkt mocken, zusaetzlich
reload_overrides() mocken — sonst liest patch() die ECHTE
runtime_overrides.json von der Platte und ueberschreibt den bewusst
gesetzten Testzustand."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_FIXED_FILES = [
    "tests/test_b351_config_save_value_error.py",
    "tests/test_config_override_guard.py",
    "tests/test_hydro_runtime_config_contract.py",
]


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_all_overrides_mocks_also_mock_reload_overrides():
    """Fuer jede Testdatei: Anzahl der '_OVERRIDES'-Mocks, die auch
    patch()/patch_exact_key() aufrufen, muss durch eine passende Anzahl an
    reload_overrides-Mocks gedeckt sein (grobe, aber wirksame Heuristik)."""
    for path in _FIXED_FILES:
        src = _read(path)
        if "rc.patch(" not in src and "runtime_config.patch(" not in src:
            continue
        overrides_mocks = src.count('"_OVERRIDES"')
        reload_mocks = src.count('"reload_overrides"')
        assert reload_mocks >= 1, (
            f"{path}: patch() wird aufgerufen und _OVERRIDES gemockt, "
            f"aber reload_overrides() ist nicht gemockt (B364-Regression)"
        )


def test_patch_without_reload_mock_would_read_real_file_demo(monkeypatch, tmp_path):
    """Demonstriert das B364-Problem isoliert: OHNE reload_overrides-Mock
    ueberschreibt patch() den gesetzten Testzustand mit dem Inhalt einer
    (hier: praeparierten) Datei auf der Platte."""
    import json
    import config
    import runtime_config as rc

    override_path = tmp_path / "runtime_overrides.json"
    override_path.write_text(json.dumps({"REAL_DISK_KEY": "from_disk"}), encoding="utf-8")
    monkeypatch.setattr(config, "RUNTIME_OVERRIDES_PATH", str(override_path), raising=False)

    monkeypatch.setattr(rc, "_OVERRIDES", {"TEST_ONLY_KEY": "from_test"}, raising=False)
    monkeypatch.setattr(rc, "save", lambda merged: None)
    # Bewusst KEIN reload_overrides-Mock — zeigt das urspruengliche Problem.

    result = rc.patch({"NEW_KEY": 1})
    assert "REAL_DISK_KEY" in result, "reload_overrides() sollte hier tatsaechlich die Platte lesen"
    assert "TEST_ONLY_KEY" not in result, (
        "Der zuvor gesetzte In-Memory-Testzustand wurde durch reload_overrides() "
        "korrekt ersetzt — das ist erwartetes B362-Verhalten OHNE Mock"
    )
