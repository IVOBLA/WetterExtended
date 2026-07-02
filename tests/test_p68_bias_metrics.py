"""P68: Signierte Bias-Metriken aus synthetischen Forecast-Error-Zeilen."""
import forecast_error_diagnosis as fed


def _row(h, flat, flon, alat, alon, fspeed, aspeed, fdir, adir):
    return {
        "horizon_min": h, "forecast_lat": flat, "forecast_lon": flon,
        "actual_lat": alat, "actual_lon": alon,
        "forecast_speed_kmh": fspeed, "actual_speed_kmh": aspeed,
        "forecast_direction_deg": fdir, "actual_direction_deg": adir,
    }


def _rows(n, east_offset_deg=0.01):
    return [_row(30, 46.6, 14.3, 46.6, 14.3 + east_offset_deg, 20.0, 25.0, 90.0, 95.0) for _ in range(n)]


def test_east_offset_detected_as_positive_dlon():
    out = fed.compute_signed_bias_by_horizon(_rows(25), min_samples=20)
    assert out["30"]["mean_dlon_deg"] > 0
    assert out["30"]["sample_count"] == 25


def test_insufficient_samples_flagged():
    out = fed.compute_signed_bias_by_horizon(_rows(5), min_samples=20)
    assert out["30"]["insufficient_data"] is True


def test_speed_bias_is_signed_not_absolute():
    out = fed.compute_signed_bias_by_horizon(_rows(25), min_samples=20)
    assert out["30"]["mean_speed_error_kmh"] > 0  # actual (25) - forecast (20) = +5


def test_outliers_do_not_dominate_bias(monkeypatch=None):
    rows = _rows(30)
    rows.append(_row(30, 46.6, 14.3, 46.6, 14.3 + 5.0, 20.0, 500.0, 90.0, 95.0))  # Ausreißer
    out = fed.compute_signed_bias_by_horizon(rows, min_samples=20)
    assert out["30"]["mean_dlon_deg"] < 1.0  # Ausreißer p10-p90-getrimmt


def test_write_and_load_bias_status(tmp_path):
    path = tmp_path / "forecast_bias_status.json"
    fed.write_forecast_bias_status({"30": {"mean_dlon_deg": 0.01}}, path=str(path))
    loaded = fed.load_forecast_bias_status(path=str(path))
    assert loaded["bias_by_horizon"]["30"]["mean_dlon_deg"] == 0.01
