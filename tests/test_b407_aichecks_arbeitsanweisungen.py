"""B407: AIChecks.md enthält Arbeitsanweisungen, keine Befunde."""
from pathlib import Path

import pytest

import debug_export


def _txt():
    return Path("AIChecks.md").read_text(encoding="utf-8")


def test_aichecks_exists_and_declares_purpose():
    t = _txt()
    assert "Arbeitsanweisungen" in t
    assert "## Offen" in t and "## Erledigt" in t


def test_aichecks_has_no_measurement_tables():
    """KERNREGRESSION: Messwerte und Belege gehoeren in HAILO_INTEGRATION.md."""
    t = _txt()
    assert "**Befund:**" not in t, "AIChecks.md dokumentiert wieder Befunde statt anzuweisen"
    assert "| Lage |" not in t, "Messtabelle in AIChecks.md"
    assert "31.188" not in t and "15.143" not in t, "Messwerte in AIChecks.md"


def test_aichecks_entries_are_imperative():
    """Jede Anweisung beginnt mit einem Verb im Imperativ."""
    verbs = ("Prüfe", "Kalibriere", "Messe", "Suche", "Nimm", "Zähle", "Werte", "Führe", "Setze",
             "Vergleiche", "Bilde", "Sammle")
    heads = [l for l in _txt().splitlines() if l.startswith("### AC-")]
    assert len(heads) >= 8, f"Zu wenige Anweisungen: {len(heads)}"
    for h in heads:
        title = h.split("—", 1)[1].strip() if "—" in h else ""
        assert title.startswith(verbs), f"Keine Arbeitsanweisung: {h}"


def test_aichecks_entries_name_a_data_source():
    """Keine Anweisung ohne konkrete Datenquelle."""
    t = _txt()
    body = t.split("## Offen", 1)[1].split("## Erledigt", 1)[0]
    blocks = [b for b in body.split("### AC-") if b.strip()]
    for b in blocks:
        assert any(s in b for s in (".json", ".jsonl", "grep", "Log", "log", "Export", "Pi")), \
            f"Anweisung ohne Datenquelle: {b.splitlines()[0]}"


def test_own_export_zip_still_excluded():
    assert debug_export._is_excluded_from_export(
        Path("train_data/evaluation/latest_export/wetterextended_debug2.zip"))


def test_foreign_zip_no_longer_excluded():
    """B407: Nur latest_export wird gefiltert — andere ZIPs sind Nutzdaten."""
    assert not debug_export._is_excluded_from_export(
        Path("train_data/external_responses/radar_archive.zip"))


def test_suffix_filter_removed():
    import inspect
    src = inspect.getsource(debug_export)
    assert "_EXPORT_EXCLUDE_SUFFIXES" not in src, "Pauschaler Suffix-Filter noch vorhanden"


def test_exclude_dirs_unchanged():
    assert debug_export._EXPORT_EXCLUDE_DIRS == {"latest_export"}
