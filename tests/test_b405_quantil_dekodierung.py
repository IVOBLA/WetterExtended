"""B405: q10/q90 müssen dieselbe ML-Dekodierung durchlaufen wie der Zentralwert."""
import inspect
import math

import pytest

import prediction


def test_decode_delta_adds_current_position():
    """P58-Konvention: bei 'delta' ist die Rohausgabe eine Verschiebung."""
    obj = {"x": 100.0, "y": 200.0}
    bx, by = prediction._decode_ml_position(obj, 5.0, -3.0, "delta")
    uf = float(prediction._UF or 1.0)
    assert bx == pytest.approx((100.0 + 5.0) * uf)
    assert by == pytest.approx((200.0 - 3.0) * uf)


def test_decode_absolute_ignores_current_position():
    obj = {"x": 100.0, "y": 200.0}
    bx, by = prediction._decode_ml_position(obj, 5.0, -3.0, "absolute")
    uf = float(prediction._UF or 1.0)
    assert bx == pytest.approx(5.0 * uf)
    assert by == pytest.approx(-3.0 * uf)


def test_delta_and_absolute_differ_massively():
    """Belegt die Fehlergroesse: 5 px Delta vs. Absolutposition bei x=100."""
    obj = {"x": 100.0, "y": 200.0}
    d = prediction._decode_ml_position(obj, 5.0, 5.0, "delta")
    a = prediction._decode_ml_position(obj, 5.0, 5.0, "absolute")
    assert abs(d[0] - a[0]) > 100.0, (
        "Testannahme: die beiden Encodings muessen weit auseinanderliegen — "
        "genau deshalb war die fehlende Dekodierung so folgenreich"
    )


def test_quantile_branch_uses_decode_helper():
    """KERNREGRESSION: der q10/q90-Zweig darf nicht mehr manuell mit _UF rechnen."""
    src = inspect.getsource(prediction.predict_positions_ml) \
        if hasattr(prediction, "predict_positions_ml") else inspect.getsource(prediction)
    assert "x_q10 = float(prediction_q10[idx * 2])     * _UF" not in src, (
        "Manuelle _UF-Multiplikation im q10-Zweig noch vorhanden — "
        "target_encoding wird ignoriert"
    )
    assert "y_q90 = float(prediction_q90[idx * 2 + 1]) * _UF" not in src
    assert "\"x_q10\": float(prediction_q10[idx * 2])     * _UF" not in src
    assert "\"y_q90\": float(prediction_q90[idx * 2 + 1]) * _UF" not in src


def test_quantile_branch_passes_target_encoding():
    src = inspect.getsource(prediction)
    i = src.find("if prediction_q10 is not None and prediction_q90 is not None:")
    assert i != -1, "q10/q90-Block nicht gefunden"
    block = src[i:i + 1400]
    assert "_decode_ml_position(" in block, "q10/q90 nutzt die Dekodierung nicht"
    assert block.count("_target_encoding") >= 2, (
        "target_encoding wird nicht an beide Quantile durchgereicht"
    )


def test_all_three_branches_decode_consistently():
    """Zentralwert, Schatten und Quantile muessen dieselbe Konvention nutzen."""
    src = inspect.getsource(prediction)
    assert "_decode_ml_position(obj, _x_raw, _y_raw, _target_encoding)" in src, \
        "Zentralwert-Zweig veraendert?"
    assert "_compute_ml_shadow(obj, horizon, _x_raw, _y_raw, _target_encoding)" in src, \
        "Schatten-Zweig veraendert?"
    i = src.find("if prediction_q10 is not None")
    assert "_decode_ml_position(" in src[i:i + 1400]


def test_quantiles_stay_near_center_with_delta_encoding():
    """Fachliche Kernpruefung: bei realistischen Deltas duerfen q10/q90 nicht
    hunderte Kilometer vom Zentralwert abweichen."""
    obj = {"x": 100.0, "y": 200.0}
    center = prediction._decode_ml_position(obj, 4.0, 1.0, "delta")
    q10 = prediction._decode_ml_position(obj, 2.0, 0.0, "delta")
    q90 = prediction._decode_ml_position(obj, 6.0, 2.0, "delta")
    for q in (q10, q90):
        assert math.hypot(q[0] - center[0], q[1] - center[1]) < 20.0, (
            "Quantil liegt unplausibel weit vom Zentralwert — Dekodierung falsch"
        )
