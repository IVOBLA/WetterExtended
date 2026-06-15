"""B144: Circuit-Breaker-Cooldown nutzt Wall-Clock und überlebt Prozess-Neustart."""
import importlib
import time
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("API_CIRCUIT_BREAKER_FILE", str(tmp_path / "cb.json"))
    import api_circuit_breaker
    mod = importlib.reload(api_circuit_breaker)
    mod._STATE.clear()
    return mod


def test_now_is_wall_clock(tmp_path, monkeypatch):
    cb = _fresh(tmp_path, monkeypatch)
    assert abs(cb._now() - time.time()) < 2


def test_open_then_reload_with_past_cooldown_auto_closes(tmp_path, monkeypatch):
    cb = _fresh(tmp_path, monkeypatch)
    cb.open_circuit("open_meteo_atmosphere", 60, "x")
    assert cb.is_open("open_meteo_atmosphere") is True
    # Cooldown in die Vergangenheit (Wall-Clock) setzen + persistieren = "Neustart später"
    cb._STATE["open_meteo_atmosphere"]["cooldown_until"] = cb._now() - 5
    cb._save()
    # Prozess-Neustart simulieren: Modul frisch laden (liest die persistierte Datei)
    import api_circuit_breaker
    cb2 = importlib.reload(api_circuit_breaker)
    assert cb2.is_open("open_meteo_atmosphere") is False


def test_future_cooldown_stays_open_after_reload(tmp_path, monkeypatch):
    cb = _fresh(tmp_path, monkeypatch)
    cb.open_circuit("svc", 3600, "x")  # 1h in der Zukunft
    cb._save()
    import api_circuit_breaker
    cb2 = importlib.reload(api_circuit_breaker)
    assert cb2.is_open("svc") is True
