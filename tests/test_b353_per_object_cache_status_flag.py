"""B353: /api/cache_status muss Per-Objekt-Namespaces (die nur bei aktiv
getrackten Sturmzellen einen Fetch ausloesen) mit per_object=True markieren,
damit das Frontend sie nicht faelschlich als "ueberfaellig" anzeigt."""
import pytest


@pytest.fixture()
def client(monkeypatch):
    pytest.importorskip("flask")
    import app as app_module
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


_EXPECTED_PER_OBJECT = {
    "geosphere_cape",
    "geosphere_nowcast",
    "openmeteo_icon_d2",
    "openmeteo_icon_eu_li",
    "openmeteo_icon_global",
    "openmeteo_synoptic_500",
    "openmeteo_extended_15min",
    "openmeteo_extended_pressure",
    "openmeteo_extended_lpi",
    "openmeteo_extended_gfs_conv",
}

_EXPECTED_NOT_PER_OBJECT = {
    "geosphere_tawes_all",
    "eumetview_capabilities",
    "eumetview_wms",
    "blitzortung_last_strikes",
}


def _by_namespace(payload):
    return {row["namespace"]: row for row in payload.get("services", [])}


def test_per_object_namespaces_flagged_true(client):
    resp = client.get("/api/cache_status")
    assert resp.status_code == 200
    rows = _by_namespace(resp.get_json())
    for ns in _EXPECTED_PER_OBJECT:
        assert ns in rows, f"Namespace {ns} fehlt in /api/cache_status"
        assert rows[ns]["per_object"] is True, f"{ns} sollte per_object=True sein"


def test_continuously_scheduled_namespaces_flagged_false(client):
    resp = client.get("/api/cache_status")
    rows = _by_namespace(resp.get_json())
    for ns in _EXPECTED_NOT_PER_OBJECT:
        if ns in rows:
            assert rows[ns]["per_object"] is False, f"{ns} sollte per_object=False sein"


def test_existing_fields_unchanged(client):
    """B353 darf keine bestehenden Felder oder die Statuslogik veraendern."""
    resp = client.get("/api/cache_status")
    payload = resp.get_json()
    assert "services" in payload
    assert "cache_dir" in payload
    for row in payload["services"]:
        for field in ("namespace", "last_fetch_ts", "age_s", "ttl_s",
                      "next_allowed_in_s", "next_fetch_ts", "status", "per_object"):
            assert field in row
        assert row["status"] in ("FRESH", "STALE", "MISSING")
