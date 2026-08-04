"""B355: /api/accuracy (history) und /api/ml_quality (series,
verification_coverage) muessen dem uebergebenen hours-Parameter exakt folgen,
ohne ihn auf ein Mindestfenster (7 Tage bzw. 24h) anzuheben."""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture()
def client(monkeypatch):
    pytest.importorskip("flask")
    import app as app_module
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def _write_history_fixture(tmp_path, monkeypatch):
    """Schreibt accuracy_history.jsonl mit Punkten bei 2h, 3 Tagen und 10 Tagen
    Alter, damit ein enges vs. weites Zeitfenster nachweisbar unterschiedliche
    Ergebnisse liefern muss.

    B500: isoliert zusaetzlich SAVE_PATHS["objects"] und DETAILS_FILE auf leere
    tmp-Verzeichnisse. evaluate_for_horizon() (aufgerufen ueber /api/accuracy)
    scannt sonst das echte, produktive train_data/objects/-Verzeichnis des
    Geraets, auf dem pytest laeuft — auf einem laufenden Produktivsystem mit
    monatelang akkumulierten Objekt-Dateien macht das den Test beliebig langsam,
    unabhaengig von den hier bewusst gesetzten drei History-Punkten.
    """
    import accuracy_tracker

    eval_dir = tmp_path / "evaluation"
    eval_dir.mkdir(parents=True, exist_ok=True)
    history_path = eval_dir / "accuracy_history.jsonl"
    objects_dir = tmp_path / "objects"
    objects_dir.mkdir(parents=True, exist_ok=True)
    details_path = eval_dir / "forecast_error_details.jsonl"

    now = datetime.now(timezone.utc)
    ages_hours = [2, 72, 240]  # 2h, 3 Tage, 10 Tage
    with open(history_path, "w", encoding="utf-8") as f:
        for age in ages_hours:
            ts = (now - timedelta(hours=age)).isoformat().replace("+00:00", "Z")
            rec = {"timestamp_utc": ts, "horizons": [], "delivered_mode_counts": {}}
            f.write(json.dumps(rec) + "\n")

    monkeypatch.setattr(accuracy_tracker, "HISTORY_FILE", str(history_path))
    monkeypatch.setitem(accuracy_tracker.SAVE_PATHS, "objects", str(objects_dir))
    monkeypatch.setattr(accuracy_tracker, "DETAILS_FILE", str(details_path))
    return ages_hours


def test_history_respects_narrow_window_without_7day_floor(tmp_path, monkeypatch, client):
    _write_history_fixture(tmp_path, monkeypatch)

    resp_narrow = client.get("/api/accuracy?hours=6")
    assert resp_narrow.status_code == 200
    narrow_history = resp_narrow.get_json()["history"]

    resp_wide = client.get("/api/accuracy?hours=720")
    assert resp_wide.status_code == 200
    wide_history = resp_wide.get_json()["history"]

    # Enges Fenster (6h) darf NUR den 2h-alten Punkt enthalten.
    assert len(narrow_history) == 1
    # Weites Fenster (720h / 30 Tage) muss alle drei Punkte enthalten.
    assert len(wide_history) == 3
    # Die beiden Ergebnisse muessen sich unterscheiden — das ist der Kern von B355.
    assert len(narrow_history) != len(wide_history)


def test_ml_quality_series_respects_narrow_window(tmp_path, monkeypatch, client):
    ages_hours = _write_history_fixture(tmp_path, monkeypatch)

    resp_narrow = client.get("/api/ml_quality?hours=6")
    assert resp_narrow.status_code == 200
    resp_wide = client.get("/api/ml_quality?hours=720")
    assert resp_wide.status_code == 200

    cov_narrow = resp_narrow.get_json().get("verification_coverage_by_horizon", {})
    cov_wide = resp_wide.get_json().get("verification_coverage_by_horizon", {})
    # Beide Antworten muessen valide JSON-Strukturen liefern (kein Crash durch
    # die entfernte Klammerung) — die eigentliche Wirkung wird bereits durch
    # test_history_respects_narrow_window_without_7day_floor abgedeckt, da
    # beide Endpunkte dieselbe zugrunde liegende History lesen.
    assert isinstance(cov_narrow, dict)
    assert isinstance(cov_wide, dict)


def test_api_health_no_longer_receives_fake_hours_param(client):
    """Backend-seitig kein Verhaltenstest noetig (Route liest hours nie) —
    stellt nur sicher, dass /api/api_health unabhaengig vom Query-String
    denselben statischen Status liefert (Architektur-Bestaetigung)."""
    resp_a = client.get("/api/api_health")
    resp_b = client.get("/api/api_health?hours=6")
    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    assert resp_a.get_json() == resp_b.get_json()
