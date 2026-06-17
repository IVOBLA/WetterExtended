"""
B208: Der Optflow-Zweig in _append_kinematic nutzt die UNGEKÜRZTE History für das
Frame-Timing, auch wenn die Merge/Split-Glättung den letzten History-Eintrag entfernt.
"""
import prediction


def test_optflow_uses_full_history(monkeypatch):
    calls = []

    def fake_fm(history, default):
        calls.append(len(history))
        return float(len(history))   # Frame-Minuten = Länge (zum Nachweisen)

    monkeypatch.setattr(prediction, "_actual_frame_min", fake_fm)
    # Horizont-Schleife leeren → kein pixel_to_geo nötig (Test bleibt dependency-arm).
    monkeypatch.setattr(prediction, "_get_horizons", lambda: [])

    history = [
        {"timestamp": "2026-06-17_10-00-00", "x": 0.0, "y": 0.0, "vx": 1.0, "vy": 0.0},
        {"timestamp": "2026-06-17_10-05-00", "x": 1.0, "y": 0.0, "vx": 1.0, "vy": 0.0},
        {"timestamp": "2026-06-17_10-10-00", "x": 2.0, "y": 0.0, "vx": 1.0, "vy": 0.0},
        {"timestamp": "2026-06-17_10-25-00", "x": 3.0, "y": 0.0, "vx": 1.0, "vy": 0.0},
    ]
    obj = {
        "x": 3.0, "y": 0.0, "lat": 46.7, "lon": 14.0,
        "history": history,
        "merge_discontinuity": 1,        # erzwingt Merge-Kürzung (n>=3)
        "of_available": 1, "of_vx": 10.0, "of_vy": 0.0,
    }
    prediction._append_kinematic(obj, {})

    # Optflow-Zweig muss die VOLLE History (Länge 4) gesehen haben, nicht 3 (gekürzt):
    assert 4 in calls, f"Optflow nutzte gekürzte History: {calls}"
    # kinematic_source kodiert _fm_of = 4.0 (voll), nicht 3.0 (gekürzt):
    assert obj["kinematic_source"] == "optflow_fm4.0", obj.get("kinematic_source")
