from pathlib import Path

AI_SUGGESTIONS = Path("frontend/src/pages/AiSuggestions.jsx")


def test_tuning_values_are_filtered_against_defaults():
    source = AI_SUGGESTIONS.read_text(encoding="utf-8")

    assert "tunedEntries" in source
    assert "defaultValue !== undefined && String(defaultValue) !== String(value)" in source


def test_current_tuned_values_heading_is_not_duplicated():
    source = AI_SUGGESTIONS.read_text(encoding="utf-8")

    assert source.count("Aktuell getunte Werte") == 1
