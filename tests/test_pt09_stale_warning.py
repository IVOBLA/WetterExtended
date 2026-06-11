"""
P-T09 — Tests: veraltete Radardaten (stale) in der Warnlogik.

Abgedeckt:
  - annotate_locations setzt stale=True wenn radar_age_min >= Horizont
  - annotate_locations setzt stale=False wenn radar_age_min < Horizont
  - effective_lead_min wird korrekt berechnet
  - Warn-E-Mail enthält den Radaralter-Hinweis bei stale-Treffer
  - Warn-E-Mail enthält den Hinweis NICHT bei frischem Treffer
  - WhatsApp-Nachricht enthält den Hinweis bei stale-Treffer
"""
import pytest


def _import_lc():
    try:
        import importlib
        return importlib.import_module("locations_check")
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"locations_check nicht importierbar: {exc}")


def _fast_growing_obj(radar_age_min):
    """Schnelle, wachsende Zelle (keine P-T06-Unterdrückung), Forecast am Ort."""
    return {
        "id": "stale-1", "lat": 46.60, "lon": 14.20,
        "forecast_mode": "kinematic",
        "vx": 6.0, "vy": 0.0, "speed_kmh": 40.0,
        "intensity_tendency": "staerker", "size_tendency": "waechst",
        "radar_age_min": radar_age_min,
        "forecast_lat_20": 46.62, "forecast_lon_20": 14.30,
    }


def test_stale_true_when_radar_older_than_horizon():
    lc = _import_lc()
    obj = _fast_growing_obj(radar_age_min=25.0)   # 25 >= 20 → stale
    loc = [{"name": "Klagenfurt", "lat": 46.62, "lon": 14.30, "radius_km": 6.0}]
    out = lc.annotate_locations([obj], loc, [20], {20: "#f00"},
                                min_speed_kmh=5.0, slow_cell_max_kmh=15.0)
    assert len(out) == 1
    hit = out[0]["hits"].get(20)
    assert hit is not None, "Forecast-Treffer bei h=20 erwartet"
    assert hit["stale"] is True
    assert hit["effective_lead_min"] == pytest.approx(-5.0, abs=0.1)


def test_stale_false_when_radar_fresh():
    lc = _import_lc()
    obj = _fast_growing_obj(radar_age_min=5.0)    # 5 < 20 → nicht stale
    loc = [{"name": "Klagenfurt", "lat": 46.62, "lon": 14.30, "radius_km": 6.0}]
    out = lc.annotate_locations([obj], loc, [20], {20: "#f00"},
                                min_speed_kmh=5.0, slow_cell_max_kmh=15.0)
    hit = out[0]["hits"].get(20)
    assert hit is not None
    assert hit["stale"] is False
    assert hit["effective_lead_min"] == pytest.approx(15.0, abs=0.1)


def test_missing_radar_age_defaults_not_stale():
    """Ohne radar_age_min (alter Code-Pfad) → 0 → nie stale."""
    lc = _import_lc()
    obj = _fast_growing_obj(radar_age_min=0.0)
    obj.pop("radar_age_min")
    loc = [{"name": "Klagenfurt", "lat": 46.62, "lon": 14.30, "radius_km": 6.0}]
    out = lc.annotate_locations([obj], loc, [20], {20: "#f00"},
                                min_speed_kmh=5.0, slow_cell_max_kmh=15.0)
    hit = out[0]["hits"].get(20)
    assert hit is not None
    assert hit["stale"] is False


def test_email_contains_stale_note():
    import email_notifier

    captured = {}

    def fake_send_smtp(recipients, subject, html_body):
        captured["html"] = html_body
        return True

    email_notifier._SMTP_HOST = "smtp.example.test"
    email_notifier._SMTP_USER = "user@example.test"
    email_notifier._SMTP_PASS = "secret"
    email_notifier._send_smtp = fake_send_smtp
    email_notifier._cooldown_warning.clear()

    hits = {20: {
        "hit_type": "forecast", "cell_id": "X1",
        "distance_km": 2.0, "speed_kmh": 40.0,
        "stale": True, "radar_age_min": 25.0,
    }}
    ok = email_notifier.send_warning_email("TestOrt-stale", hits, "ops@example.test", "2026-06-10_16-45-51")
    assert ok is True
    assert "Position unsicher" in captured["html"]
    assert "25 min alt" in captured["html"]


def test_email_no_note_when_fresh():
    import email_notifier

    captured = {}
    email_notifier._SMTP_HOST = "smtp.example.test"
    email_notifier._SMTP_USER = "user@example.test"
    email_notifier._SMTP_PASS = "secret"
    email_notifier._send_smtp = lambda r, s, h: captured.update(html=h) or True
    email_notifier._cooldown_warning.clear()

    hits = {20: {
        "hit_type": "forecast", "cell_id": "X1",
        "distance_km": 2.0, "speed_kmh": 40.0,
        "stale": False, "radar_age_min": 5.0,
    }}
    email_notifier.send_warning_email("TestOrt-fresh", hits, "ops@example.test", "")
    assert "Position unsicher" not in captured.get("html", "")


def test_whatsapp_contains_stale_note(monkeypatch):
    import whatsapp_notifier

    captured = {}

    def fake_send(phone, apikey, message):
        captured["message"] = message
        return True

    monkeypatch.setattr(whatsapp_notifier, "_send_whatsapp", fake_send)
    whatsapp_notifier._cooldown_warning.clear()

    hits = {20: {
        "hit_type": "forecast", "cell_id": "X1",
        "distance_km": 2.0, "speed_kmh": 40.0,
        "stale": True, "radar_age_min": 25.0,
    }}
    ok = whatsapp_notifier.send_warning_wa("WA-stale", hits, "+4312345:APIKEY", "")
    assert ok is True
    assert "Position unsicher" in captured["message"]
    assert "25 min alt" in captured["message"]
