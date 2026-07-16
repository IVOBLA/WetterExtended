import hydro_flood_ml as h

def test_model_integrity_signature_shape(tmp_path):
    d=tmp_path/'current'; d.mkdir()
    (d/'model.joblib').write_bytes(b'x')
    (d/'metadata.json').write_text('{}')
    sig=h.model_integrity_signature(d)
    assert sig['size'] == 1
    assert sig['model_sha256']
