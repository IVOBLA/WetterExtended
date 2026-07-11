import sys
import types
from datetime import datetime, timezone


def _import_diagnose_module(monkeypatch):
    sys.modules.pop("tools.diagnose_forecast_quality", None)
    monkeypatch.setitem(sys.modules, "debug_utils", types.SimpleNamespace(debug_log=lambda *args, **kwargs: None))
    mod = __import__("tools.diagnose_forecast_quality", fromlist=["_model_usage_from_accuracy_history"])
    return mod


def _row(horizon, samples, verified, mae_km, hit_rate=None, coverage_rate=None, ts="2026-07-10T21:12:00+00:00"):
    return {
        "horizon": horizon,
        "samples": samples,
        "verified": verified,
        "mae_km": mae_km,
        "hit_rate": hit_rate,
        "coverage_rate": coverage_rate,
        "timestamp_utc": ts,
    }


def test_model_usage_excludes_horizon_without_verification(monkeypatch):
    """B336: samples>0 aber verified==0 darf NICHT im model_usage-Report landen,
    auch wenn mae_km (nach B335 korrekt None, in Altdaten evtl. noch 0.0) vorhanden ist."""
    mod = _import_diagnose_module(monkeypatch)

    rows = [
        _row(horizon=60, samples=64, verified=0, mae_km=None, hit_rate=None, coverage_rate=0.0),
        _row(horizon=10, samples=69, verified=3, mae_km=3.01, hit_rate=0.0435, coverage_rate=0.043),
    ]

    result = mod._model_usage_from_accuracy_history(rows)

    assert "60" not in result["by_horizon"], "Horizont ohne Verifikation darf nicht erscheinen"
    assert "10" in result["by_horizon"]
    assert result["by_horizon"]["10"]["verified"] == 3
    assert result["by_horizon"]["10"]["coverage_rate"] == 0.043
    assert result["by_horizon"]["10"]["mae_km"] == 3.01


def test_model_usage_excludes_stale_zero_mae_legacy_rows(monkeypatch):
    """Regressionsschutz fuer Altdaten aus der Zeit vor B335: verified==0 mit
    faelschlich mae_km=0.0 (statt None) muss ebenfalls ausgeschlossen werden."""
    mod = _import_diagnose_module(monkeypatch)

    rows = [_row(horizon=60, samples=64, verified=0, mae_km=0.0, hit_rate=None, coverage_rate=0.0)]

    result = mod._model_usage_from_accuracy_history(rows)

    assert result == {"status": "not_available"}


def test_model_usage_keeps_verified_horizon_with_true_zero_mae():
    """Ein echter Treffer mit MAE=0.0 bei verified>0 muss weiterhin erscheinen —
    der Filter darf nicht auf mae_km<=0 pruefen, nur auf verified<=0 / mae_km is None."""
    import tools.diagnose_forecast_quality as mod

    rows = [_row(horizon=10, samples=5, verified=5, mae_km=0.0, hit_rate=1.0, coverage_rate=1.0)]

    result = mod._model_usage_from_accuracy_history(rows)

    assert "10" in result["by_horizon"]
    assert result["by_horizon"]["10"]["mae_km"] == 0.0
    assert result["by_horizon"]["10"]["verified"] == 5


def test_model_usage_keeps_legacy_row_without_verified_field():
    """B337-Regressionsschutz: eine Zeile OHNE 'verified'-Feld (Legacy-/Test-Schema,
    z. B. tests/test_b294_model_usage_aggregation.py) darf NICHT wie verified=0
    behandelt werden. 'Feld fehlt' ist etwas anderes als 'explizit 0'."""
    import tools.diagnose_forecast_quality as mod

    rows = [{
        "timestamp_utc": "2026-07-01T20:00:00Z",
        "horizon": 10,
        "samples": 500,
        "mae_km": 4.6,
        "hit_rate": 0.11,
    }]

    result = mod._model_usage_from_accuracy_history(rows)

    assert result["status"] == "available"
    assert "10" in result["by_horizon"]
    assert result["by_horizon"]["10"]["samples"] == 500
    assert result["by_horizon"]["10"]["mae_km"] == 4.6
    assert result["by_horizon"]["10"]["verified"] is None
