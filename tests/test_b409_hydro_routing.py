import hydro_flood_ml as h
import hydro_impact


def test_routing_tau_source_from_station_value(monkeypatch):
    from shapely.geometry import Polygon
    catchment = Polygon([(0,0),(0.1,0),(0.1,0.1),(0,0.1),(0,0)])
    monkeypatch.setattr(h.runtime_config, "get", lambda name, default=None: 0.0 if name == "HYDRO_MIN_OVERLAP_AREA_KM2" else default)
    monkeypatch.setattr(hydro_impact, "load_station_catchment_index", lambda force_reload=False: {"S1": {"station_id":"S1", "geometry": catchment, "feature_count":1, "status":"ok", "area_km2": 1, "signature":"x", "properties":{}}})
    monkeypatch.setattr(hydro_impact, "catchment_diagnostics", lambda sid: {"catchment_geometry_available": True, "catchment_geometry_status":"ok", "catchment_feature_count":1, "catchment_area_geometry_km2": 1, "catchment_signature":"x"})
    cell = {"id":"C", "contour_geo":[[0.02,0.02],[0.08,0.02],[0.08,0.08],[0.02,0.08],[0.02,0.02]], "lat":0.05, "lon":0.05, "nowcast_rain_rate_1h": 20}
    fast = h._precip_from_cells({"station_id":"S1", "q_m3s":1, "routing_tau_min":10}, [cell])
    slow = h._precip_from_cells({"station_id":"S1", "q_m3s":1, "routing_tau_min":120}, [cell])
    assert fast["routing_tau_source"] == "station_routing_tau_min"
    assert slow["routing_tau_source"] == "station_routing_tau_min"
    assert fast["physical_predicted_q_delta_m3s"] > slow["physical_predicted_q_delta_m3s"]
