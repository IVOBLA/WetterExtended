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
    assert set(payload) == {"zusammenfassung", "fehler", "loesungen", "verbesserungen", "prompts"}


def test_reject_result_without_object(rla):
    with pytest.raises(ValueError):
        rla.extract_payload(_outer("nur Prosa ohne JSON-Objekt"))


def test_outer_non_json_still_reported(rla):
    with pytest.raises(ValueError):
        rla.extract_payload("kein json auf stdout")
