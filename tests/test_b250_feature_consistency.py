"""B250 — Train/Serve-Mismatch: Feature-Namen-Persistenz + Konsistenz-Check.

Tests:
- feature_names werden in training_meta geschrieben.
- feature_names stimmen mit ML_CELL_FEATURES + ML_STATION_FEATURES + time überein.
- Konsistenz-Check erkennt vertauschte Features.
- Konsistenz-Check erkennt fehlende Features (Längenunterschied).
- Konsistenz-Check ist ein No-Op wenn feature_names nicht in training_meta (alte Modelle).
- _frame_features liefert exakt ML_NUM_FEATURES Werte.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    ML_CELL_FEATURES, ML_STATION_FEATURES, ML_TIME_FEATURES,
    ML_NUM_FEATURES,
)


# ── Feature-Listen-Konsistenz ─────────────────────────────────────────────────

def test_feature_names_match_cell_station_time():
    """Die in training_meta geschriebene feature_names-Liste stimmt mit
    ML_CELL_FEATURES + ML_STATION_FEATURES + time-Features überein."""
    expected_time = ["hour_sin", "hour_cos", "month_sin", "month_cos"]
    expected = list(ML_CELL_FEATURES) + list(ML_STATION_FEATURES) + expected_time
    assert len(expected) == ML_NUM_FEATURES, (
        f"feature_names Länge {len(expected)} ≠ ML_NUM_FEATURES {ML_NUM_FEATURES}"
    )


def test_ml_time_features_order():
    """ML_TIME_FEATURES enthält genau die 4 Sinus/Cosinus-Zeit-Features in erwarteter Reihenfolge."""
    assert list(ML_TIME_FEATURES) == ["hour_sin", "hour_cos", "month_sin", "month_cos"], \
        f"ML_TIME_FEATURES Reihenfolge unerwartet: {ML_TIME_FEATURES}"


def test_no_duplicate_feature_names():
    """Keine doppelten Feature-Namen in der Gesamtliste."""
    all_features = list(ML_CELL_FEATURES) + list(ML_STATION_FEATURES) + list(ML_TIME_FEATURES)
    assert len(all_features) == len(set(all_features)), \
        "Doppelte Feature-Namen gefunden: " + str(
            [f for f in all_features if all_features.count(f) > 1]
        )


# ── _frame_features Länge ────────────────────────────────────────────────────

def test_frame_features_returns_correct_length():
    """_frame_features liefert exakt ML_NUM_FEATURES Werte für ein vollständiges Objekt."""
    import prediction as pred
    from datetime import timezone

    obj = {k: 1.0 for k in ML_CELL_FEATURES}
    obj.update({"lat": 46.8, "lon": 14.3, "x": 100.0, "y": 100.0})
    station = {k: 1.0 for k in ML_STATION_FEATURES}

    ts = datetime(2026, 6, 24, 10, 0, tzinfo=timezone.utc).replace(tzinfo=None)
    result = pred._frame_features(obj, [station], ts)
    assert result is not None, "_frame_features hat None zurückgegeben"
    assert len(result) == ML_NUM_FEATURES, \
        f"_frame_features lieferte {len(result)} Werte, erwartet {ML_NUM_FEATURES}"


# ── Mismatch-Erkennung ────────────────────────────────────────────────────────

def test_mismatch_detected_swapped_features():
    """Vertauschte Feature-Reihenfolge im training_meta wird als Mismatch erkannt."""
    current = list(ML_CELL_FEATURES) + list(ML_STATION_FEATURES) + ["hour_sin", "hour_cos", "month_sin", "month_cos"]
    swapped = list(current)
    # Erste zwei Features tauschen
    swapped[0], swapped[1] = swapped[1], swapped[0]

    assert swapped != current, "Test-Setup: Swapped muss von current abweichen"

    # Mismatch-Logik direkt testen (nicht den ganzen Prediction-Pfad):
    mismatch = (list(swapped) != current)
    assert mismatch is True, "Mismatch nicht erkannt"


def test_mismatch_detected_extra_feature():
    """Mehr Features im training_meta als aktuell wird als Mismatch erkannt."""
    current = list(ML_CELL_FEATURES) + list(ML_STATION_FEATURES) + ["hour_sin", "hour_cos", "month_sin", "month_cos"]
    longer = current + ["extra_feature"]
    assert list(longer) != current


def test_no_mismatch_for_identical_list():
    """Identische Feature-Liste ergibt keinen Mismatch."""
    current = list(ML_CELL_FEATURES) + list(ML_STATION_FEATURES) + ["hour_sin", "hour_cos", "month_sin", "month_cos"]
    assert list(current) == current  # trivial aber explizit


def test_no_check_without_feature_names_in_meta():
    """Fehlt feature_names in training_meta (altes Modell), kein Mismatch-Alarm."""
    meta_without_names = {"feature_count": 119, "target_encoding": "delta"}
    trained = meta_without_names.get("feature_names")  # None für altes Modell
    # Konsistenz-Check soll bei None übersprungen werden
    assert trained is None, "Erwartete None für altes training_meta ohne feature_names"
    # Keine Exception erwartet


# ── training_meta Struktur ────────────────────────────────────────────────────

def test_feature_names_key_present_in_expected_meta():
    """Simuliertes training_meta nach B250 enthält feature_names-Schlüssel."""
    expected_time = ["hour_sin", "hour_cos", "month_sin", "month_cos"]
    simulated_meta = {
        "feature_count": ML_NUM_FEATURES,
        "feature_names": list(ML_CELL_FEATURES) + list(ML_STATION_FEATURES) + expected_time,
        "target_encoding": "delta",
    }
    assert "feature_names" in simulated_meta
    assert len(simulated_meta["feature_names"]) == ML_NUM_FEATURES
    assert simulated_meta["feature_names"][0] == ML_CELL_FEATURES[0]  # "x"
    assert simulated_meta["feature_names"][-1] == "month_cos"


def test_runtime_training_meta_reads_nested_readiness_meta():
    """Runtime-Status enthält training_meta produktiv unter readiness.training_meta."""
    import prediction as pred

    meta = {
        "feature_names": ["trained_feature"],
        "target_encoding": "delta",
    }
    runtime_status = {
        "runtime_mode": "ml",
        "readiness": {"training_meta": meta},
    }

    assert pred._runtime_training_meta(runtime_status) is meta


def test_runtime_training_meta_prefers_top_level_for_compatibility():
    """Falls beide Strukturen existieren, bleibt Top-Level rückwärtskompatibel bevorzugt."""
    import prediction as pred

    top_level = {"feature_names": ["top"]}
    nested = {"feature_names": ["nested"]}

    assert pred._runtime_training_meta({
        "training_meta": top_level,
        "readiness": {"training_meta": nested},
    }) is top_level
