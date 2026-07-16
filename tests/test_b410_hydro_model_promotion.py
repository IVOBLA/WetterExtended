import hydro_flood_ml as h

def test_model_signature_shape(tmp_path):
    d=tmp_path/'current'; d.mkdir()
    (d/'model.joblib').write_bytes(b'x')
    (d/'metadata.json').write_text('{}')
    sig=h.model_signature(d)
    assert sig['model_size'] == 1
    assert sig['model_sha256']
