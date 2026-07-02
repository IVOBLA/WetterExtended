import orographic_module



def test_forecast_speed_factor_never_below_point_one():
    scores = orographic_module.compute_orographic_scores({
        "dem_barrier_ahead": 10000.0,
        "dem_slope_toward_cell": 100.0,
        "cape": 5000.0,
        "valley_confinement": 0.0,
        "vx": 0.0,
        "vy": 0.0,
    })
    assert scores["forecast_speed_factor"] >= 0.1
