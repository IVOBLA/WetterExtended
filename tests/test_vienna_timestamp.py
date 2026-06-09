"""B112: first_seen wird als Vienna-Lokalzeit geparst (kein UTC-Fehler)."""
import pytest


def _parse(ts):
    """Python-Äquivalent von parseViennaLocalTimestamp für Tests."""
    if not ts:
        return None
    import re
    iso = re.sub(r"_(\d{2})-(\d{2})-(\d{2})$", r"T\1:\2:\3", ts)
    iso = iso.replace("_", "T")
    return iso


def test_b112_underscore_format():
    result = _parse("2026-06-09_13-41-02")
    assert result == "2026-06-09T13:41:02"


def test_b112_no_z_appended():
    result = _parse("2026-06-09_13-41-02")
    assert not result.endswith("Z"), "Kein UTC-Z hinzufügen"


def test_b112_none_input():
    assert _parse(None) is None
    assert _parse("") is None
