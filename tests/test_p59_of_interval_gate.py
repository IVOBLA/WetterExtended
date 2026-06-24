"""P59: OF wird bei zu großem Frame-Intervall verworfen (EWMA-Fallback)."""
import pytest

prediction = pytest.importorskip("prediction")
config = pytest.importorskip("config")


def test_of_max_frame_interval_in_config():
    assert hasattr(config, "OF_MAX_FRAME_INTERVAL_MIN")
    assert 5.0 < config.OF_MAX_FRAME_INTERVAL_MIN <= 15.0


def _make_obj(of_vx=2.0, of_vy=3.0, of_avail=1, history_interval_min=5.0):
    """Minimales Objekt-Dict für _append_kinematic."""
    ts_base = "2026-06-01_12-00-00"
    import datetime as dt
    t0 = dt.datetime(2026, 6, 1, 12, 0, 0)
    history = []
    for i in range(3):
        ti = t0 + dt.timedelta(minutes=i * history_interval_min)
        history.append({
            "x": float(i * of_vx * history_interval_min),
            "y": float(i * of_vy * history_interval_min),
            "timestamp": ti.strftime("%Y-%m-%d_%H-%M-%S"),
            "vx": of_vx * history_interval_min,
            "vy": of_vy * history_interval_min,
        })
    return {
        "id": "test-1", "x": 100.0, "y": 200.0, "lat": 46.6, "lon": 14.3,
        "of_vx": of_vx, "of_vy": of_vy, "of_available": of_avail,
        "active_frames": 10, "history": history,
        "of_error_reason": None,
    }


def test_of_used_when_interval_small(monkeypatch):
    """Kleines Intervall (5 min) → OF wird genutzt."""
    obj = _make_obj(history_interval_min=5.0)
    forecasts = {h: [] for h in prediction._get_horizons()}
    prediction._append_kinematic(obj, forecasts)
    src = obj.get("kinematic_source", "")
    assert "optflow" in src, f"Erwartet optflow, got: {src}"


def test_of_rejected_when_interval_large(monkeypatch):
    """Großes Intervall (20 min) → OF wird verworfen, EWMA-Fallback."""
    obj = _make_obj(history_interval_min=20.0)
    forecasts = {h: [] for h in prediction._get_horizons()}
    prediction._append_kinematic(obj, forecasts)
    src = obj.get("kinematic_source", "")
    assert "optflow" not in src, f"OF sollte verworfen worden sein, src={src}"
    reason = obj.get("of_error_reason", "")
    assert "interval_too_large" in str(reason), f"of_error_reason fehlt: {reason}"
