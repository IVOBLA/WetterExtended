"""B299: dem_slope_barrier_status unterscheidet dem_unavailable/
no_movement_vector/computed statt eines nicht interpretierbaren 0.0-Defaults."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dem_feature as dem


def test_dem_unavailable_when_tiles_not_loaded(monkeypatch):
    monkeypatch.setattr(dem, "_ensure_dem", lambda: False)
    result = dem.get_dem_features(46.62, 14.30, vx=5.0, vy=3.0)
    assert result["dem_slope_barrier_status"] == "dem_unavailable"
    assert result["dem_slope_toward_cell"] == 0.0


def test_no_movement_vector_when_speed_too_low(monkeypatch):
    monkeypatch.setattr(dem, "_ensure_dem", lambda: True)
    monkeypatch.setattr(dem, "_height", lambda lat, lon: 450.0)
    result = dem.get_dem_features(46.62, 14.30, vx=0.0, vy=0.0)
    assert result["dem_slope_barrier_status"] == "no_movement_vector"
    assert result["dem_slope_toward_cell"] == 0.0
    assert result["dem_barrier_ahead"] == 0.0
    assert result["dem_elevation_m"] == 450.0  # Elevation bleibt trotzdem gueltig


def test_computed_when_movement_vector_present(monkeypatch):
    monkeypatch.setattr(dem, "_ensure_dem", lambda: True)
    heights = {
        (-0.0225, -0.0225): 400.0, (-0.0225, 0.0): 410.0, (-0.0225, 0.0225): 420.0,
        (0.0, -0.0225): 405.0, (0.0, 0.0): 415.0, (0.0, 0.0225): 425.0,
        (0.0225, -0.0225): 430.0, (0.0225, 0.0): 440.0, (0.0225, 0.0225): 450.0,
    }

    def _fake_height(lat, lon):
        for (dlat, dlon), h in heights.items():
            if abs(lat - (46.62 + dlat)) < 1e-6 and abs(lon - (14.30 + dlon)) < 1e-6:
                return h
        return 415.0  # "ahead"-Abfragen ausserhalb des 3x3-Rasters

    monkeypatch.setattr(dem, "_height", _fake_height)
    result = dem.get_dem_features(46.62, 14.30, vx=3.0, vy=2.0)
    assert result["dem_slope_barrier_status"] == "computed"


def test_dem_unavailable_when_no_heights_found(monkeypatch):
    monkeypatch.setattr(dem, "_ensure_dem", lambda: True)
    monkeypatch.setattr(dem, "_height", lambda lat, lon: None)
    result = dem.get_dem_features(46.62, 14.30, vx=5.0, vy=3.0)
    assert result["dem_slope_barrier_status"] == "dem_unavailable"


def test_dem_partial_coverage_when_slope_grid_incomplete(monkeypatch):
    """B300 (Codex-Review-Fix): fehlt ein Punkt im 3x3-Slope-Gitter, darf das
    nicht als 'computed' durchgehen, obwohl der Bewegungsvektor vorhanden ist."""
    monkeypatch.setattr(dem, "_ensure_dem", lambda: True)

    def _fake_height(lat, lon):
        # Zentrum liefert einen Wert (mean_elev berechenbar), einer der 9
        # Gitterpunkte liefert None (z.B. Kachel-Rand) -> Slope unvollstaendig.
        if abs(lat - 46.62) < 1e-6 and abs(lon - 14.30) < 1e-6:
            return None
        return 415.0

    monkeypatch.setattr(dem, "_height", _fake_height)
    result = dem.get_dem_features(46.62, 14.30, vx=3.0, vy=2.0)
    assert result["dem_slope_barrier_status"] == "dem_partial_coverage"


def test_dem_partial_coverage_when_barrier_lookahead_incomplete(monkeypatch):
    """B300 (Codex-Review-Fix): fehlt einer der 4 Lookahead-Punkte fuer
    dem_barrier_ahead, darf das ebenfalls nicht als 'computed' gelten."""
    monkeypatch.setattr(dem, "_ensure_dem", lambda: True)
    calls = {"n": 0}

    def _fake_height(lat, lon):
        calls["n"] += 1
        # Die ersten 9 Aufrufe (3x3-Gitter) liefern immer einen Wert,
        # der zweite Lookahead-Punkt (km=13.0) liefert None.
        if calls["n"] == 11:
            return None
        return 415.0

    monkeypatch.setattr(dem, "_height", _fake_height)
    result = dem.get_dem_features(46.62, 14.30, vx=3.0, vy=2.0)
    assert result["dem_slope_barrier_status"] == "dem_partial_coverage"
