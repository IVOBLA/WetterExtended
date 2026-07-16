import json
import hydro_flood_ml as h


def test_predict_integrity_error_falls_back(monkeypatch, tmp_path):
    monkeypatch.setattr(h, 'HYDRO_MODEL_CURRENT_DIR', tmp_path)
    (tmp_path/'metadata.json').write_text(json.dumps({'promoted': True, 'feature_schema_version':h.FEATURE_SCHEMA_VERSION, 'feature_names':h.HYDRO_FLOOD_ML_FEATURES, 'feature_schema_hash':h._feature_schema_hash()}))
    row={k:1.0 for k in h.HYDRO_FLOOD_ML_FEATURES}; row.update({'current_q_m3s':1,'physical_predicted_q_delta_m3s':0.5})
    pred=h.predict_q_delta(row)
    assert pred['prediction_source'] == 'physical_fallback'
    assert pred['model_rejection_reason'] == 'model_integrity_error'
