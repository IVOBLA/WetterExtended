import hydro_flood_ml as h


def _base(**kw):
    row={k:1.0 for k in h.HYDRO_REQUIRED_FEATURES}
    row.update({k:None for k in h.HYDRO_OPTIONAL_FEATURES})
    row.update({'station_id':'s','sample_start_time':'2026-01-01T00:00:00Z','sample_kind':h.SAMPLE_KIND_LIVE,'feature_schema_version':h.FEATURE_SCHEMA_VERSION,'feature_snapshot_complete':True,'target_q_delta_m3s':0.2,'target_missing':False})
    row['feature_schema_hash'] = h._feature_schema_hash()
    row.update(kw)
    features=h._feature_snapshot(row)
    row['features']=features
    row['missing_required_features']=h._missing_required_features({'features':features})
    row['feature_snapshot_complete']=not row['missing_required_features']
    return row


def test_optional_threshold_trend_and_cell_entry_are_imputed_trainable():
    row=_base(current_q_ratio_threshold=None,current_q_distance_to_threshold_m3s=None,q_trend_delta_m3s=None,q_trend_reference_window_min=None,first_entry_offset_min=None,last_exit_offset_min=None,data_age_min=None)
    assert row['feature_snapshot_complete'] is True
    assert row['features']['threshold_available_flag'] == 0.0
    assert row['features']['q_trend_available_flag'] == 0.0
    assert row['features']['cell_entry_available_flag'] == 0.0
    assert row['features']['data_age_available_flag'] == 0.0
    assert h._sample_is_trainable_live(row)


def test_required_none_keeps_snapshot_incomplete():
    row=_base(current_q_m3s=None)
    assert 'current_q_m3s' in row['missing_required_features']
    assert row['feature_snapshot_complete'] is False
