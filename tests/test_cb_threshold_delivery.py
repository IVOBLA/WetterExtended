"""
B204: /api/objects?include_ir=1 hängt CLOUD_HEIGHT_ALERT_THRESHOLD_M als
cb_alert_threshold_m an jedes IR-Objekt (für die öffentliche Karte).
"""
import sys
import types

sys.modules.setdefault("debug_utils", types.SimpleNamespace(
    debug_log=lambda *a, **k: None))


def test_threshold_attached_to_ir_objects(monkeypatch):
    import app as app_module
    import runtime_config

    # IR-Tracks mocken
    import ir_cell_tracking
    monkeypatch.setattr(
        ir_cell_tracking, "load_active_ir_tracks",
        lambda: [{"ir_id": "ir_0", "lat": 46.7, "lon": 14.0}],
    )
    # Schwelle via runtime override simulieren
    monkeypatch.setattr(
        runtime_config, "get",
        lambda name, default=None: 9000.0 if name == "CLOUD_HEIGHT_ALERT_THRESHOLD_M" else default,
    )
    # _objects_for_ts neutralisieren (leere Radarliste)
    monkeypatch.setattr(app_module, "_objects_for_ts", lambda ts: [])

    client = app_module.app.test_client()
    resp = client.get("/api/objects?include_ir=1")
    assert resp.status_code == 200
    data = resp.get_json()
    ir = [o for o in (data if isinstance(data, list) else data.get("objects", []))
          if o.get("_type") in ("ir_cell", "ir_precursor_cell")]
    assert ir, "IR-Objekt erwartet"
    assert ir[0]["cb_alert_threshold_m"] == 9000.0
