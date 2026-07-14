"""B372: Lineage-Persistenz muss beweisbar sein — Erfolg wie Fehler."""
import json

import pytest

import cell_lineage as cl
import debug_export


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """Testisolation via monkeypatch + autouse (Muster: test_config_override_guard.py).

    Kein sys.modules-Stub — vgl. wiederkehrende Kontaminationsklasse B96/B160/B161/
    B334/B338/B364.
    """
    monkeypatch.chdir(tmp_path)
    state_dir = tmp_path / "cell_lineage"
    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(cl, "_state_dir", lambda: state_dir)
    yield state_dir


def test_event_is_written_and_status_ok(_isolate_state, tmp_path):
    cl.append_lineage_event({"event_type": "cell_merge", "cell_id": "C1"})
    ledger = _isolate_state / "cell_lineage_events.jsonl"
    assert ledger.exists(), "Eventledger wurde nicht geschrieben"
    status = json.loads((tmp_path / "train_data" / "system" / "cell_lineage_write_status.json").read_text())
    assert status["last_result"] == "ok"
    assert status["ok_count"] == 1
    assert status["error_count"] == 0


def test_resolved_path_is_absolute(_isolate_state, tmp_path):
    """Der aufgeloeste Pfad muss absolut sein — relative Pfade haengen vom CWD ab."""
    cl.append_lineage_event({"event_type": "cell_merge", "cell_id": "C1"})
    status = json.loads((tmp_path / "train_data" / "system" / "cell_lineage_write_status.json").read_text())
    assert status["resolved_events_path"].startswith("/"), "Pfad muss absolut aufgeloest sein"
    assert "cwd" in status


def test_write_failure_is_recorded_not_swallowed(_isolate_state, monkeypatch, tmp_path):
    """Ein Schreibfehler darf NICHT still verschwinden — genau der Defekt von B372."""
    def _boom():
        raise PermissionError("simulierter Schreibfehler")

    monkeypatch.setattr(cl, "_events_path", _boom)
    cl.append_lineage_event({"event_type": "cell_merge", "cell_id": "C1"})
    status_file = tmp_path / "train_data" / "system" / "cell_lineage_write_status.json"
    assert status_file.exists(), "Fehler wurde still verschluckt — keine Statusdatei"
    status = json.loads(status_file.read_text())
    assert status["last_result"] == "error"
    assert status["error_count"] == 1
    assert "PermissionError" in status["last_error"]


def test_status_marker_survives_uncreatable_lineage_dir(tmp_path, monkeypatch):
    """Der Fehlermarker liegt nicht im fehlschlagenden Ledger-Verzeichnis."""
    blocked = tmp_path / "blocked_lineage_parent"
    blocked.write_text("kein Verzeichnis", encoding="utf-8")
    monkeypatch.setattr(cl, "_state_dir", lambda: blocked / "cell_lineage")

    cl.append_lineage_event({"event_type": "cell_merge", "cell_id": "C1"})

    status_file = tmp_path / "train_data" / "system" / "cell_lineage_write_status.json"
    assert status_file.exists(), "Fehler wurde nicht unabhaengig vom Ledger-Verzeichnis exportierbar markiert"
    status = json.loads(status_file.read_text())
    assert status["last_result"] == "error"
    assert "NotADirectoryError" in status["last_error"]


def test_write_failure_does_not_raise(_isolate_state, monkeypatch):
    """Persistenzfehler duerfen den Radarzyklus nicht stoppen."""
    def _boom():
        raise OSError("read-only")

    monkeypatch.setattr(cl, "_events_path", _boom)
    cl.append_lineage_event({"event_type": "cell_merge", "cell_id": "C1"})  # darf nicht werfen


def test_lineage_artifacts_in_always_include():
    """Der Ledger muss unabhaengig vom 24h-mtime-Fenster exportiert werden."""
    always = debug_export._ALWAYS_INCLUDE_NAMES
    for name in ("cell_lineage_events.jsonl", "cell_lineage_state.json", "cell_lineage_write_status.json"):
        assert name in always, f"{name} fehlt in _ALWAYS_INCLUDE_NAMES"


def test_status_counters_accumulate(_isolate_state, tmp_path):
    for _ in range(3):
        cl.append_lineage_event({"event_type": "cell_merge", "cell_id": "C1"})
    status = json.loads((tmp_path / "train_data" / "system" / "cell_lineage_write_status.json").read_text())
    assert status["ok_count"] == 3
