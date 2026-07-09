"""B327: _max_risk_level() toleriert 'Connection refused' kurz nach dem
Prozessstart (Startup-Race gegen den lokalen Flask-/API-Server) durch
kurze Retries mit Backoff, statt sofort auf Risikostufe 0 zu verzichten.
Nach Ablauf des Grace-Fensters bleibt das alte Verhalten (sofort 0) erhalten.

Wichtig: Dieser Test ist eigenstaendig und unabhaengig von
tests/test_b262_risk_watch_retry.py, welcher einen anderen Codepfad
(main.py::_risk_alert_check, E-Mail-Alert-Versand) prueft."""
import pytest


class _FakeResp:
    status_code = 200

    def json(self):
        return {"cells": [{"risk": 3}]}


def test_erfolg_nach_einem_fehlschlag_innerhalb_grace(monkeypatch):
    rw = pytest.importorskip("risk_watch")

    monkeypatch.setattr(rw, "_PROC_START_MONOTONIC", rw.time.monotonic())
    monkeypatch.setattr(rw.time, "sleep", lambda _s: None)
    monkeypatch.setattr(rw.runtime_config, "get", lambda key, default=None: default)

    calls = []

    def _get(url, timeout):
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionError("Connection refused")
        return _FakeResp()

    level = rw._max_risk_level(_get)

    assert level == 3, "Nach dem Retry innerhalb der Startup-Grace muss der echte Wert zurückkommen."
    assert len(calls) == 2, "Erwartet genau 1 Fehlschlag + 1 erfolgreicher Retry."


def test_dauerhafter_fehlschlag_innerhalb_grace_gibt_irgendwann_null(monkeypatch):
    rw = pytest.importorskip("risk_watch")

    monkeypatch.setattr(rw, "_PROC_START_MONOTONIC", rw.time.monotonic())
    monkeypatch.setattr(rw.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        rw.runtime_config, "get",
        lambda key, default=None: 2 if key == "RISK_WATCH_STARTUP_MAX_RETRIES" else default,
    )

    calls = []

    def _always_fail(url, timeout):
        calls.append(1)
        raise ConnectionError("Connection refused")

    level = rw._max_risk_level(_always_fail)

    assert level == 0
    assert len(calls) == 3, "1 Erstversuch + 2 Retries = 3 Aufrufe, danach 0."


def test_kein_retry_ausserhalb_startup_grace(monkeypatch):
    """Nach Ablauf des Grace-Fensters (regulärer Betrieb) zählt ein Fehler
    sofort als 0 — kein zusätzlicher Retry, keine zusätzliche Latenz im
    laufenden Polling-Betrieb."""
    rw = pytest.importorskip("risk_watch")

    # Prozessstart weit in der Vergangenheit simulieren -> außerhalb Grace-Fenster.
    monkeypatch.setattr(rw, "_PROC_START_MONOTONIC", rw.time.monotonic() - 3600.0)
    monkeypatch.setattr(rw.time, "sleep", lambda _s: None)
    monkeypatch.setattr(rw.runtime_config, "get", lambda key, default=None: default)

    calls = []

    def _fail(url, timeout):
        calls.append(1)
        raise ConnectionError("Connection refused")

    level = rw._max_risk_level(_fail)

    assert level == 0
    assert len(calls) == 1, "Außerhalb des Startup-Grace-Fensters darf kein Retry erfolgen."


def test_sofortiger_erfolg_ohne_jeden_retry(monkeypatch):
    """Regression: bei sofortigem Erfolg wird http_get nur einmal aufgerufen,
    unabhängig vom Grace-Fenster."""
    rw = pytest.importorskip("risk_watch")

    monkeypatch.setattr(rw, "_PROC_START_MONOTONIC", rw.time.monotonic())
    monkeypatch.setattr(rw.time, "sleep", lambda _s: None)
    monkeypatch.setattr(rw.runtime_config, "get", lambda key, default=None: default)

    calls = []

    def _get(url, timeout):
        calls.append(1)
        return _FakeResp()

    level = rw._max_risk_level(_get)

    assert level == 3
    assert len(calls) == 1
