"""B244: mark_q_m3s null-Löschung persistiert korrekt (kein deep-merge Revert)."""
import json


def _setup_runtime_config(tmp_path, initial: dict):
    """Schreibt initial state in temporäres runtime_overrides.json."""
    import config as cfg
    path = str(tmp_path / "runtime_overrides.json")
    cfg.RUNTIME_OVERRIDES_PATH = path
    with open(path, "w") as f:
        json.dump(initial, f)
    import runtime_config as rc
    rc.reload_overrides()
    return rc


def test_patch_exact_key_removes_mark_q_m3s(tmp_path):
    rc = _setup_runtime_config(tmp_path, {
        "HYDRO_STATION_OVERRIDES": {"AT_001": {"enabled": True, "mark_q_m3s": 150.0}}
    })

    # Admin löscht mark_q_m3s (null-Wert):
    overrides = dict(rc.get("HYDRO_STATION_OVERRIDES", {}))
    cur = dict(overrides.get("AT_001", {}))
    cur.pop("mark_q_m3s", None)
    overrides["AT_001"] = cur
    rc.patch_exact_key("HYDRO_STATION_OVERRIDES", overrides)

    result = rc.get("HYDRO_STATION_OVERRIDES", {})
    assert "mark_q_m3s" not in result.get("AT_001", {}), \
        "mark_q_m3s wurde durch deep-merge zurückgeschrieben!"
    assert result["AT_001"]["enabled"] is True  # anderer Wert bleibt


def test_legacy_patch_still_reverts_mark_q_m3s(tmp_path):
    """Dokumentiert das Bug-Verhalten von patch() als Regression-Baseline."""
    rc = _setup_runtime_config(tmp_path, {
        "HYDRO_STATION_OVERRIDES": {"AT_001": {"enabled": True, "mark_q_m3s": 150.0}}
    })
    overrides = dict(rc.get("HYDRO_STATION_OVERRIDES", {}))
    cur = dict(overrides.get("AT_001", {}))
    cur.pop("mark_q_m3s", None)
    overrides["AT_001"] = cur
    rc.patch({"HYDRO_STATION_OVERRIDES": overrides})  # absichtlich alte API
    result = rc.get("HYDRO_STATION_OVERRIDES", {})
    # Bug: mark_q_m3s bleibt durch deep-merge erhalten
    assert "mark_q_m3s" in result.get("AT_001", {}), \
        "patch() verhält sich anders als erwartet — Test anpassen"


def test_patch_exact_key_preserves_other_top_level_keys(tmp_path):
    rc = _setup_runtime_config(tmp_path, {
        "HYDRO_STATION_OVERRIDES": {"AT_001": {"mark_q_m3s": 100.0}},
        "SOME_OTHER_KEY": "value",
    })
    rc.patch_exact_key("HYDRO_STATION_OVERRIDES", {"AT_001": {}})
    assert rc.get("SOME_OTHER_KEY") == "value"
