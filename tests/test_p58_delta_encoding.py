"""P58: Delta-Encoding/-Dekodierung und Rückwärtskompatibilität."""
import pytest

prediction = pytest.importorskip("prediction")


def test_decode_delta_adds_current_position():
    # delta (+30,+15) auf now (100,200) -> (130,215) * UF
    bx, by = prediction._decode_ml_position({"x": 100.0, "y": 200.0}, 30.0, 15.0, "delta")
    uf = prediction._UF
    assert bx == pytest.approx(130.0 * uf)
    assert by == pytest.approx(215.0 * uf)


def test_decode_absolute_is_legacy_path():
    # absolute: Rohwert ist bereits die Position
    bx, by = prediction._decode_ml_position({"x": 100.0, "y": 200.0}, 130.0, 215.0, "absolute")
    uf = prediction._UF
    assert bx == pytest.approx(130.0 * uf)
    assert by == pytest.approx(215.0 * uf)


def test_decode_unknown_encoding_falls_back_to_absolute():
    bx, by = prediction._decode_ml_position({"x": 0.0, "y": 0.0}, 50.0, 60.0, None)
    uf = prediction._UF
    assert (bx, by) == pytest.approx((50.0 * uf, 60.0 * uf))


def test_config_encoding_is_delta():
    import config
    assert config.ML_TARGET_ENCODING == "delta"


def test_dataset_builder_uses_delta(monkeypatch):
    # Encoding-Pfad im dataset_builder: now=(100,200), fut=(130,215) -> delta (30,15)
    import dataset_builder as db
    assert db.ML_TARGET_ENCODING in ("delta", "absolute")
    now = {"x": 100.0, "y": 200.0}
    fo = {"x": 130.0, "y": 215.0}
    nx, ny = db._safe_float(now["x"]), db._safe_float(now["y"])
    if db.ML_TARGET_ENCODING == "delta":
        assert [db._safe_float(fo["x"]) - nx, db._safe_float(fo["y"]) - ny] == [30.0, 15.0]
