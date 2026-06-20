from pathlib import Path


def _read(path):
    return Path(path).read_text(encoding="utf-8")


def test_hydro_frontend_accepts_envelope_and_direct_feature_collection():
    src = "\n".join(_read(path) for path in [
        "frontend/src/pages/MapView.jsx",
        "frontend/src/pages/MapFullscreen.jsx",
        "frontend/src/pages/Configuration.jsx",
        "frontend/src/utils/hydro.js",
    ])
    assert "response?.data || response" in src
    assert "Array.isArray(fc.features)" in src


def test_hydro_frontend_lines_require_station_and_cell_coordinates():
    src = _read("frontend/src/pages/MapView.jsx") + _read("frontend/src/pages/MapFullscreen.jsx") + _read("frontend/src/utils/hydro.js")
    assert "hasValidHydroImpactLine(impact)" in src
    assert "isFiniteCoordinate(impact.cell_lat)" in src
    assert "isFiniteCoordinate(impact.cell_lon)" in src
    assert "isFiniteCoordinate(impact.station_lat)" in src
    assert "isFiniteCoordinate(impact.station_lon)" in src


def test_admin_lists_all_hydro_runtime_keys():
    src = _read("frontend/src/pages/Configuration.jsx")
    for key in [
        "HYDRO_ENABLED", "HYDRO_API_TTL_SECONDS", "HYDRO_MIN_OVERLAP_AREA_KM2",
        "HYDRO_MIN_OVERLAP_RATIO_CELL", "HYDRO_MIN_DURATION_MIN", "HYDRO_RELEVANT_INTENSITIES",
        "HYDRO_DEFAULT_LAG_MIN", "HYDRO_LAG_WINDOW_MIN", "HYDRO_VERIFY_MIN_DELTA_Q_M3S",
        "HYDRO_VERIFY_MIN_DELTA_W_CM", "HYDRO_VERIFY_MIN_RELATIVE_DELTA_PCT",
        "HYDRO_VERIFY_MAX_GAP_MIN", "HYDRO_STATION_OVERRIDES",
    ]:
        assert key in src
