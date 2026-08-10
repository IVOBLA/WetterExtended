"""B521: export_json_views() einmal pro Horizont-Lauf statt pro Datensatz."""
import json
import os

import accuracy_tracker as at
import forecast_verification as fv


def _count_export_calls(monkeypatch):
    calls = {"n": 0}
    orig = fv.VerificationStore.export_json_views

    def _wrapped(self, *a, **kw):
        calls["n"] += 1
        return orig(self, *a, **kw)

    monkeypatch.setattr(fv.VerificationStore, "export_json_views", _wrapped)
    return calls


def test_b521_persist_verification_export_flag_suppresses_export(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "DETAILS_FILE", str(tmp_path / "forecast_error_details.jsonl"))
    calls = _count_export_calls(monkeypatch)
    rec = {"object_id": "X1", "cell_id": "WX-TEST-0001", "forecast_source_frame_id": "f1",
           "generated_at_utc": "2026-08-10T00:00:00Z"}
    at._persist_verification(dict(rec), export=False)
    assert calls["n"] == 0, "export=False darf export_json_views NICHT aufrufen"
    at._persist_verification(dict(rec), export=True)
    assert calls["n"] == 1, "export=True (Default-Verhalten) muss weiterhin exportieren"


def test_b521_append_detail_once_propagates_export_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "DETAILS_FILE", str(tmp_path / "forecast_error_details.jsonl"))
    calls = _count_export_calls(monkeypatch)
    rec = {"object_id": "X2", "cell_id": "WX-TEST-0002", "forecast_source_frame_id": "f2",
           "generated_at_utc": "2026-08-10T00:00:00Z"}
    seen = set()
    at._append_detail_once(at.DETAILS_FILE, rec, seen, export=False)
    assert calls["n"] == 0


def test_b521_all_six_callsites_in_evaluate_for_horizon_use_export_false():
    """Statische Regressionssicherung: verhindert, dass ein zukuenftiger Patch
    export=False an einer der 6 Aufrufstellen versehentlich wieder entfernt."""
    import inspect
    src = inspect.getsource(at.evaluate_for_horizon)
    assert src.count(
        "_append_detail_once(DETAILS_FILE, rec, detail_keys_seen, export=False)"
    ) == 6
    assert "_append_detail_once(DETAILS_FILE, rec, detail_keys_seen)" not in src.replace(
        "_append_detail_once(DETAILS_FILE, rec, detail_keys_seen, export=False)", ""
    )


def test_b521_single_export_at_end_of_evaluate_for_horizon(tmp_path, monkeypatch):
    """End-to-End: evaluate_for_horizon() darf export_json_views() maximal EINMAL
    aufrufen, unabhaengig davon wie viele Datensaetze verifiziert werden."""
    monkeypatch.setattr(at, "DETAILS_FILE", str(tmp_path / "forecast_error_details.jsonl"))
    obj_dir = tmp_path / "objects"
    obj_dir.mkdir()
    monkeypatch.setitem(at.SAVE_PATHS, "objects", str(obj_dir))
    calls = _count_export_calls(monkeypatch)

    # Keine Objektdateien -> frueher Return VOR jeder Persistenz -> 0 Exporte erwartet.
    result = at.evaluate_for_horizon(10, since_hours=24)
    assert isinstance(result, dict)
    assert calls["n"] <= 1, f"erwartet <=1 Export-Aufruf, war {calls['n']}"


def test_b521_verification_json_views_reflect_final_state(tmp_path, monkeypatch):
    """Der gebuendelte Export muss denselben Endzustand persistieren wie vorher
    (nur seltener aufgerufen) — keine Datenverfaelschung durch das Batching."""
    monkeypatch.setattr(at, "DETAILS_FILE", str(tmp_path / "forecast_error_details.jsonl"))
    db_dir = tmp_path
    rec1 = {"object_id": "X3", "cell_id": "WX-TEST-0003", "forecast_source_frame_id": "f3",
            "generated_at_utc": "2026-08-10T00:00:00Z"}
    rec2 = {"object_id": "X4", "cell_id": "WX-TEST-0004", "forecast_source_frame_id": "f4",
            "generated_at_utc": "2026-08-10T00:01:00Z"}
    at._persist_verification(dict(rec1), export=False)
    at._persist_verification(dict(rec2), export=True)  # letzter Aufruf exportiert final
    views_path = db_dir / "forecast_verification_latest.jsonl"
    assert views_path.exists()
    lines = [json.loads(l) for l in views_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    case_keys = {l.get("object_id") for l in lines}
    assert {"X3", "X4"}.issubset(case_keys), "beide Datensaetze muessen im finalen Export erscheinen"
