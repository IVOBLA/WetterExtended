"""P101: Promotion pruefte nur eine Gesamt-Sample-Anzahl, nicht pro Horizont. Ein
Kandidat mit ausreichender Summe aber sehr duennem Einzelhorizont (typischerweise
+60 min, geringste Verifikationsabdeckung) konnte trotzdem promoted werden."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import model_training as mt  # noqa: E402


def test_min_samples_per_horizon_constant_exists_and_is_sane():
    assert hasattr(mt, "MIN_SAMPLES_PER_HORIZON_FOR_PROMOTION")
    assert 0 < mt.MIN_SAMPLES_PER_HORIZON_FOR_PROMOTION <= mt.MIN_SAMPLES_FOR_PROMOTION


def test_thin_horizon_detection_flags_only_horizons_in_km_average():
    paired = {"10": 45, "20": 40, "60": 3}
    mae_km_by_horizon = {"10": 1.0, "20": 1.2, "60": 5.0}
    thin = {h: n for h, n in paired.items()
            if h in mae_km_by_horizon and n < mt.MIN_SAMPLES_PER_HORIZON_FOR_PROMOTION}
    assert thin == {"60": 3}


def test_horizon_missing_from_km_average_is_not_flagged():
    """Ein Horizont ohne mae_km-Eintrag (z.B. weil evaluate_on_recent ihn mangels
    scaler_X komplett ausgelassen hat) darf die Promotion nicht wegen fehlender
    Samples blockieren — er fliesst ja gar nicht in _mae_new ein."""
    paired = {"10": 45, "60": 2}
    mae_km_by_horizon = {"10": 1.0}  # "60" fehlt bewusst
    thin = {h: n for h, n in paired.items()
            if h in mae_km_by_horizon and n < mt.MIN_SAMPLES_PER_HORIZON_FOR_PROMOTION}
    assert thin == {}


def test_status_text_exists_for_new_rejection_reason():
    src = Path(mt.__file__).read_text(encoding="utf-8")
    assert "rejected_low_samples_per_horizon" in src
