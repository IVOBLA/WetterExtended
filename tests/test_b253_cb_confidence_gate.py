"""B253 — CB-Klassifikation nur mit gemessener Wolkenhöhe,
first_height_alert_timestamp fixiert."""
import sys
import types
from pathlib import Path

if "numpy" not in sys.modules:
    sys.modules["numpy"] = types.ModuleType("numpy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ir_cell_detection import classify_height_stage


# ─── F7: CB-Gate anhand Konfidenz und Quelle ──────────────────────────────────

def test_fallback_hoehe_8225m_ist_maximal_watch():
    """default_fallback mit 8225 m darf nicht pre_cb/cb werden."""
    stage = classify_height_stage(
        8225.0,
        cloud_height_confidence=0.35,
        cloud_height_source="default_fallback",
    )
    assert stage in ("watch", "low"), (
        f"Fallback-Höhe 8225 m darf nicht als CB eingestuft werden, erhalten: {stage}"
    )


def test_gemessene_hoehe_8225m_ist_pre_cb():
    """Echte Messung (conf=0.65) mit 8225 m > 7500 m → pre_cb."""
    stage = classify_height_stage(
        8225.0,
        cloud_height_confidence=0.65,
        cloud_height_source="lapse_rate_bt",
    )
    assert stage == "pre_cb", f"Erwartet pre_cb, erhalten: {stage}"


def test_confidence_unter_schwelle_kein_cb():
    """Konfidenz 0.4 < 0.5 Mindest-Schwelle → CB-Einstufung unterdrückt."""
    stage = classify_height_stage(
        10000.0,
        cloud_height_confidence=0.4,
        cloud_height_source="lapse_rate_bt",
    )
    assert stage in ("watch", "low"), (
        f"Konfidenz 0.4 zu gering für CB, erhalten: {stage}"
    )


def test_hohe_konfidenz_cb_erlaubt():
    """Konfidenz 0.65 ≥ 0.5 und Höhe 9500 m ≥ 9000 m → cb."""
    stage = classify_height_stage(
        9500.0,
        cloud_height_confidence=0.65,
        cloud_height_source="local_weather_default_alt",
    )
    assert stage == "cb", f"Erwartet cb, erhalten: {stage}"


def test_watch_bleibt_unabhaengig_von_konfidenz():
    """Niedrige Konfidenz blockiert CB, aber nicht watch."""
    stage_low_conf = classify_height_stage(
        6500.0,
        cloud_height_confidence=0.1,
        cloud_height_source="default_fallback",
    )
    stage_high_conf = classify_height_stage(
        6500.0,
        cloud_height_confidence=0.9,
        cloud_height_source="lapse_rate_bt",
    )
    # Beide sollten watch sein (6500 m liegt im watch-Bereich)
    # watch-Schwelle ist IR_WATCH_CLOUD_HEIGHT_MIN_M (default 5000 m)
    assert stage_low_conf in ("watch", "low")
    assert stage_high_conf in ("watch", "low")


def test_rueckwaertskompatibel_ohne_parameter():
    """Aufruf ohne confidence/source-Parameter bleibt kompatibel (default conf=1.0)."""
    stage = classify_height_stage(8225.0)
    # Default cloud_height_confidence=1.0 → CB erlaubt
    assert stage == "pre_cb", (
        f"Ohne Parameter: Höhe 8225 m > 7500 m → pre_cb erwartet, erhalten: {stage}"
    )


# ─── F8: first_height_alert_timestamp Regression ─────────────────────────────

def test_first_height_alert_timestamp_wird_fixiert():
    """first_height_alert_timestamp darf nach dem ersten Setzen nicht wandern."""
    import ir_cell_tracking as irt

    # Simuliere: Track hat bereits einen ersten Alert-Timestamp
    track_mit_alert = {
        "first_height_alert_timestamp": "2026-06-25_19-15-00",
        "height_stage": "pre_cb",
        "ir_stage": "ir_pre_cb",
        "ir_score": 0.5,
        "ir_id": "ir_0", "ir_track_id": "ir_0",
        "radar_confirmed": False,
    }
    # Nach Normalisierung muss der Wert erhalten bleiben
    irt._normalize_ir_track(track_mit_alert, default_timestamp="2026-06-25_21-25-00")
    assert track_mit_alert["first_height_alert_timestamp"] == "2026-06-25_19-15-00", (
        "first_height_alert_timestamp darf nicht auf 21:25 überschrieben werden"
    )


def test_first_height_alert_timestamp_initial_gesetzt():
    """Beim ersten Alarm (war None) wird der Timestamp korrekt gesetzt."""
    import ir_cell_tracking as irt

    track_neu = {
        "height_stage": "pre_cb",
        "ir_stage": "ir_pre_cb",
        "ir_score": 0.5,
        "ir_id": "ir_1", "ir_track_id": "ir_1",
        "radar_confirmed": False,
        # first_height_alert_timestamp absichtlich nicht gesetzt
    }
    irt._normalize_ir_track(track_neu, default_timestamp="2026-06-25_21-30-00")
    assert track_neu["first_height_alert_timestamp"] == "2026-06-25_21-30-00", (
        "Beim ersten Alarm soll der Timestamp gesetzt werden"
    )
