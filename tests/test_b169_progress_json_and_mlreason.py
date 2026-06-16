"""B169 — /api/progress liefert gültiges JSON (kein Infinity/NaN); _ml_block_reason
crasht nicht mehr an os.isdir.

Ausführbar: python3 -m pytest tests/test_b169_progress_json_and_mlreason.py -v
"""
import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _app():
    try:
        return importlib.import_module("app")
    except Exception as exc:  # Flask-/Import-Kontext auf manchen Umgebungen nicht da
        pytest.skip(f"app nicht importierbar: {exc}")


def test_json_finite_safe_replaces_inf_and_nan():
    app_mod = _app()
    fn = getattr(app_mod, "_json_finite_safe", None)
    assert fn is not None, "B169: _json_finite_safe fehlt"
    data = {
        "a": float("inf"),
        "b": float("-inf"),
        "c": float("nan"),
        "d": [1.0, float("inf"), {"e": float("nan")}],
        "f": "Infinity-als-Text-bleibt",
        "g": 3,
        "h": True,
    }
    out = fn(data)
    assert out["a"] is None and out["b"] is None and out["c"] is None
    assert out["d"][0] == 1.0 and out["d"][1] is None and out["d"][2]["e"] is None
    assert out["f"] == "Infinity-als-Text-bleibt"
    assert out["g"] == 3
    assert out["h"] is True


def test_progress_endpoint_emits_valid_json():
    app_mod = _app()
    client = app_mod.app.test_client()
    resp = client.get("/api/progress")
    assert resp.status_code == 200
    body = resp.get_json(silent=False)
    assert isinstance(body, dict) and "versions" in body
    # Die browser-brechenden Tokens dürfen im Rohtext NICHT mehr vorkommen.
    raw = resp.get_data(as_text=True)
    assert "Infinity" not in raw, "Antwort enthält noch 'Infinity' → ungültiges JSON"
    assert "NaN" not in raw, "Antwort enthält noch 'NaN' → ungültiges JSON"


def test_ml_block_reason_no_isdir_attribute_error():
    app_mod = _app()
    val = app_mod._ml_block_reason()
    assert val is None or isinstance(val, str)
    assert not (isinstance(val, str) and "has no attribute 'isdir'" in val), \
        "B169: _ml_block_reason crasht weiterhin an os.isdir (os.path.isdir nötig)"


if __name__ == "__main__":
    import traceback
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"FAIL {name}: {exc}")
                traceback.print_exc()
    sys.exit(1 if failed else 0)
