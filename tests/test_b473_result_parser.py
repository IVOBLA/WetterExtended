"""B473 — extract_payload holt das Ergebnis-JSON auch aus umschlossenem Text."""
import importlib.util
import json
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parents[1] / "tools" / "run_local_analysis.py"


@pytest.fixture
def rla():
    spec = importlib.util.spec_from_file_location("rla_b473", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_GOOD = {"zusammenfassung": "ok", "fehler": [], "loesungen": [],
         "verbesserungen": [], "prompts": []}


def _outer(result_text):
    return json.dumps({"result": result_text, "is_error": False})


@pytest.mark.parametrize("result_text", [
    json.dumps(_GOOD),
    "```json\n" + json.dumps(_GOOD) + "\n```",
    "Hier die Analyse:\n```json\n" + json.dumps(_GOOD) + "\n```",
    "Analyse fertig. " + json.dumps(_GOOD) + " -- Ende",
])
def test_extract_from_wrapped_result(rla, result_text):
    payload = rla.extract_payload(_outer(result_text))
    assert payload["zusammenfassung"] == "ok"
    assert payload["fehler"] == [] and payload["loesungen"] == []
    assert payload["verbesserungen"] == [] and payload["prompts"] == []
    # B503: seit P105 reichert validate_payload() jede Antwort verbindlich um die
    # fuenf getrennten Verbesserungsbereiche (FINDING_FIELDS), tuning_proposals und
    # die Plateau-/Ursachenklassen-Felder an — auch wenn das Modell sie nicht
    # geliefert hat (Default-Werte). Das vollstaendige Schema wird hier aus den
    # Quell-Konstanten des Moduls abgeleitet statt hartcodiert, damit dieser Test
    # nicht erneut veraltet, sobald P105 oder ein Nachfolger weitere Pflichtfelder
    # mit eigenen Defaults ergaenzt.
    expected_keys = (
        {"zusammenfassung"}
        | set(rla.REQUIRED_LIST_FIELDS)
        | {"tuning_proposals"}
        | set(rla.FINDING_FIELDS)
        | {"quality_state", "previous_experiment_id", "previous_cause_class", "next_cause_class"}
    )
    assert set(payload) == expected_keys


def test_reject_result_without_object(rla):
    with pytest.raises(ValueError):
        rla.extract_payload(_outer("nur Prosa ohne JSON-Objekt"))


def test_outer_non_json_still_reported(rla):
    with pytest.raises(ValueError):
        rla.extract_payload("kein json auf stdout")
