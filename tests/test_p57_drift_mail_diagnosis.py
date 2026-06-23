"""P57: Drift-Mail enthält den diagnostizierten Grund statt der statischen Liste."""
import email_notifier as en


def _capture(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(en, "_is_configured", lambda: True)
    monkeypatch.setattr(en, "_get_all_drift_recipients", lambda: ["x@example.invalid"])
    monkeypatch.setattr(en, "_DRIFT_COOLDOWN_FILE", str(tmp_path / "cd.json"), raising=False)

    def _fake_smtp(recipients, subject, html_body):
        captured["subject"] = subject
        captured["body"] = html_body
        return True

    monkeypatch.setattr(en, "_send_smtp", _fake_smtp)
    return captured


def _status_absolute():
    return {
        "drift_detected": True,
        "drift_reason": "absolute",
        "mae_recent_km": 10.260346666666669,
        "mae_baseline_km": 20.147165,
        "mae_recent_short_km": 7.389958333333335,
        "short_horizon_max_min": 30.0,
        "abs_threshold_km": 1.0,
        "delta_km": -9.853,
        "threshold_km": 2.0,
        "diagnosis_summary": {
            "severity": "critical",
            "primary_findings": [
                "Forecast direction error probably dominates short-horizon drift.",
                "A few outlier forecasts probably dominate MAE.",
            ],
            "top_recommendation": "Bewegungsrichtung prüfen: Optical-Flow-Vektor ...",
        },
    }


def test_mail_contains_translated_findings_and_reason(monkeypatch, tmp_path):
    cap = _capture(monkeypatch, tmp_path)
    en.send_drift_alert(_status_absolute())
    body = cap["body"]
    # Deutsch übersetzter Finding statt englischem Roh-String
    assert "Richtungsfehler der Bewegung dominiert" in body
    assert "Forecast direction error probably dominates" not in body
    # Empfohlene Prüfung + Schweregrad sichtbar
    assert "Empfohlene Prüfung" in body
    assert "kritisch" in body
    # Lesbarer Drift-Grund
    assert "Kurzhorizont-Zielverletzung" in body


def test_negative_delta_not_shown_as_red_worsening(monkeypatch, tmp_path):
    cap = _capture(monkeypatch, tmp_path)
    en.send_drift_alert(_status_absolute())
    body = cap["body"]
    # Kein irreführendes "+-" und keine rote Verschlechterung bei negativem Delta
    assert "+-9" not in body
    assert "-9.85 km" in body
    assert "Verschlechterung (relativ)" not in body
    # km-Werte gerundet (kein langer Float)
    assert "10.260346666666669" not in body
    assert "10.26 km" in body


def test_positive_delta_keeps_red_worsening(monkeypatch, tmp_path):
    cap = _capture(monkeypatch, tmp_path)
    st = _status_absolute()
    st["drift_reason"] = "relative"
    st["delta_km"] = 3.5
    en.send_drift_alert(st)
    body = cap["body"]
    assert "Verschlechterung (relativ)" in body
    assert "+3.50 km" in body


def test_fallback_when_no_diagnosis(monkeypatch, tmp_path):
    cap = _capture(monkeypatch, tmp_path)
    st = _status_absolute()
    st.pop("diagnosis_summary")
    en.send_drift_alert(st)
    body = cap["body"]
    assert "Mögliche Ursachen" in body  # statischer Fallback bleibt
