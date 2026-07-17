"""B424: Drift-Mails setzen Promotion und belegte ML-Auslieferung voraus."""

import json
import sys
import types

import drift_detector as drift


def _arrange(monkeypatch, tmp_path, *, current=False, delivered=None, detected=True):
    models = tmp_path / "models"
    models.mkdir()
    if current:
        (models / "current").mkdir()
    history = tmp_path / "accuracy_history.jsonl"
    if delivered is not None:
        history.write_text(json.dumps({"delivered_mode_counts": delivered}) + "\n")
    status_file = tmp_path / "drift_status.json"
    status = {"drift_detected": detected}
    sent = []
    monkeypatch.setattr(drift, "_MODELS_BASE", str(models))
    monkeypatch.setattr(drift, "_HISTORY_FILE", str(history))
    monkeypatch.setattr(drift, "_STATUS_FILE", str(status_file))
    monkeypatch.setattr(drift, "_EVAL_DIR", str(tmp_path))
    monkeypatch.setattr(drift, "check_drift", lambda: dict(status))
    monkeypatch.setitem(
        sys.modules,
        "email_notifier",
        types.SimpleNamespace(send_drift_alert=lambda value: sent.append(value)),
    )
    return models, status_file, sent


def _assert_suppressed(status_file, sent, reason):
    persisted = json.loads(status_file.read_text())
    assert sent == []
    assert persisted["drift_detected"] is True
    assert persisted["alert_suppressed"] is True
    assert persisted["alert_suppression_reason"] == reason


def test_rejected_version_directory_does_not_prove_delivery(monkeypatch, tmp_path):
    models, status_file, sent = _arrange(
        monkeypatch,
        tmp_path,
        delivered={"10": {"kinematic_fallback": 506}},
    )
    (models / "v_rejected_training_artifact").mkdir()
    drift.check_and_alert()
    _assert_suppressed(status_file, sent, "no_promoted_model")


def test_current_with_kinematic_delivery_suppresses(monkeypatch, tmp_path):
    _, status_file, sent = _arrange(
        monkeypatch,
        tmp_path,
        current=True,
        delivered={"10": {"kinematic_fallback": 506}},
    )
    drift.check_and_alert()
    _assert_suppressed(status_file, sent, "delivered_mode_kinematic_only")


def test_current_with_ml_delivery_sends(monkeypatch, tmp_path):
    _, status_file, sent = _arrange(
        monkeypatch, tmp_path, current=True, delivered={"10": {"ml": 1}}
    )
    result = drift.check_and_alert()
    assert sent == [result]
    assert not status_file.exists()


def test_ml_count_without_current_suppresses(monkeypatch, tmp_path):
    _, status_file, sent = _arrange(
        monkeypatch, tmp_path, delivered={"10": {"ml": 4}}
    )
    drift.check_and_alert()
    _assert_suppressed(status_file, sent, "no_promoted_model")


def test_missing_history_suppresses_without_crash(monkeypatch, tmp_path):
    _, status_file, sent = _arrange(monkeypatch, tmp_path, current=True)
    drift.check_and_alert()
    _assert_suppressed(status_file, sent, "delivered_mode_unreadable")


def test_unreadable_history_suppresses_without_crash(monkeypatch, tmp_path):
    _, status_file, sent = _arrange(monkeypatch, tmp_path, current=True)
    (tmp_path / "accuracy_history.jsonl").write_text("not-json\n")
    drift.check_and_alert()
    _assert_suppressed(status_file, sent, "delivered_mode_unreadable")


def test_missing_models_base_suppresses(monkeypatch, tmp_path):
    models, status_file, sent = _arrange(
        monkeypatch, tmp_path, delivered={"10": {"ml": 2}}
    )
    models.rmdir()
    drift.check_and_alert()
    _assert_suppressed(status_file, sent, "no_promoted_model")


def test_no_drift_is_not_marked_as_suppressed(monkeypatch, tmp_path):
    _, status_file, sent = _arrange(monkeypatch, tmp_path, detected=False)
    result = drift.check_and_alert()
    assert sent == []
    assert "alert_suppressed" not in result
    assert not status_file.exists()
