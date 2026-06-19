import json
import re
from pathlib import Path

import pytest

from init_runtime_overrides import DEFAULTS, RuntimeOverridesInvalidError, init_overrides

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "install.sh"


def test_init_runtime_overrides_merge_only_preserves_existing_locations(tmp_path):
    path = tmp_path / "runtime_overrides.json"
    locations = [
        {
            "name": "Feldkirchen",
            "lat": 46.7233,
            "lon": 14.0992,
            "radius_km": 2,
            "email": "a@example.com",
            "whatsapp": "+43699xxx:key",
        },
        {
            "name": "Poitschach",
            "lat": 46.75158,
            "lon": 14.09417,
            "radius_km": 2,
            "email": "b@example.com",
            "whatsapp": "+43664yyy:key2",
        },
    ]
    path.write_text(json.dumps({"LOCATIONS_WATCHLIST": locations}), encoding="utf-8")

    added = init_overrides(str(path))
    data = json.loads(path.read_text(encoding="utf-8"))

    assert data["LOCATIONS_WATCHLIST"] == locations
    assert data["LOCATIONS_WATCHLIST"][0]["email"] == "a@example.com"
    assert data["LOCATIONS_WATCHLIST"][0]["whatsapp"] == "+43699xxx:key"
    assert data["LOCATIONS_WATCHLIST"][1]["email"] == "b@example.com"
    assert data["LOCATIONS_WATCHLIST"][1]["whatsapp"] == "+43664yyy:key2"
    assert added
    for key in DEFAULTS:
        assert key in data


def test_init_runtime_overrides_invalid_json_never_overwrites(tmp_path):
    path = tmp_path / "runtime_overrides.json"
    invalid = '{"LOCATIONS_WATCHLIST": [invalid json]'
    path.write_text(invalid, encoding="utf-8")

    with pytest.raises(RuntimeOverridesInvalidError):
        init_overrides(str(path))

    assert path.read_text(encoding="utf-8") == invalid
    corrupt_files = list(tmp_path.glob("runtime_overrides.json.corrupt_*"))
    assert corrupt_files
    assert corrupt_files[0].read_text(encoding="utf-8") == invalid


def test_install_sh_uses_target_init_runtime_overrides_path():
    text = INSTALL_SH.read_text(encoding="utf-8")

    assert '"$TARGET/init_runtime_overrides.py" --path "$TARGET/train_data/runtime_overrides.json"' in text
    assert '"$_SCRIPT_DIR/init_runtime_overrides.py"' not in text
    assert not re.search(r'python3\s+"\$_SCRIPT_DIR/init_runtime_overrides\.py"(?!\s+--path)', text)


def test_install_sh_error_trap_restores_runtime_overrides():
    text = INSTALL_SH.read_text(encoding="utf-8")
    on_error = re.search(r'on_error\(\) \{(?P<body>.*?)\n\}', text, re.S)

    assert on_error is not None
    assert "restore_runtime_overrides" in on_error.group("body")
    assert text.count("restore_runtime_overrides") >= 3


def test_full_delete_dirs_do_not_include_runtime_overrides():
    text = INSTALL_SH.read_text(encoding="utf-8")
    full_delete_dirs = re.search(r'FULL_DELETE_DIRS=\((?P<body>.*?)\n\s*\)', text, re.S)

    assert full_delete_dirs is not None
    body = full_delete_dirs.group("body")
    assert "runtime_overrides.json" not in body
    assert not re.search(r"train_data/statistics(?:/|\")", body)
    assert not re.search(r"train_data/dem(?:/|\")", body)
    assert not re.search(r"train_data/cell_filters(?:/|\")", body)
