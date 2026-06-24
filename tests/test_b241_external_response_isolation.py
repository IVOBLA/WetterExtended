"""B241: 'service t' / example.invalid landet im tmp, nicht im echten train_data."""
import os
import debug_utils


def test_log_api_call_does_not_write_repo_external_responses(tmp_path):
    debug_utils.log_api_call(
        "t", url="https://example.invalid", status_code=503, error="HTTPError: 503"
    )
    assert not os.path.exists(
        os.path.join(".", "train_data", "external_responses", "t")
    )


def test_persist_external_response_redirected_to_tmp(tmp_path):
    import external_response_logger as erl
    target = erl.persist_external_response(
        "t", url="https://example.invalid", status_code=0, fallback=True,
        error="HTTPError: 503",
    )
    assert target is not None
    assert str(tmp_path) in str(target)
    assert os.path.exists(target)
