"""Deduplication helpers for cell-lineage API/KMZ payloads."""

IR_TO_RADAR_FIELDS = {
    "ir_track_id": ("ir_track_id", "ir_id"),
    "ir_match_id": ("ir_match_id", "match_id", "ir_id"),
    "ir_bt_min_k": ("ir_bt_min_k", "bt_min_k"),
    "ir_bt_mean_k": ("ir_bt_mean_k", "bt_mean_k"),
    "ir_bt_trend_k_per_min": ("ir_bt_trend_k_per_min", "bt_trend_k_per_min"),
    "ir_cloud_top_m": ("ir_cloud_top_m", "cloud_top_m"),
    "ir_cloud_height_m": ("ir_cloud_height_m", "cloud_height_m"),
    "ir_cloud_height_trend_m_per_min": ("ir_cloud_height_trend_m_per_min", "cloud_height_trend_m_per_min"),
    "ir_area_growth_km2_per_min": ("ir_area_growth_km2_per_min", "area_growth_km2_per_min"),
    "ir_overshooting_top": ("ir_overshooting_top", "overshooting_top"),
    "ir_cloud_age_min": ("ir_cloud_age_min", "cloud_age_min"),
    "ir_precursor_status": ("ir_precursor_status", "precursor_status", "status"),
    "ir_semantics": ("ir_semantics", "semantics"),
    "lineage_match_score": ("lineage_match_score", "match_score"),
    "lineage_match_decision": ("lineage_match_decision", "match_decision"),
    "lineage_match_reason": ("lineage_match_reason", "match_reason"),
}


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_visible_ir_precursor(ir: dict) -> bool:
    if ir.get("display_as_precursor") is False:
        return False
    if ir.get("radar_confirmed") is True:
        return False
    return _as_float(ir.get("ir_only_precursor", 0.0), 0.0) == 1.0


def attach_ir_values_to_radar(radar: dict, ir: dict) -> None:
    """Copy IR lineage values onto a radar object without removing existing IDs."""
    if not isinstance(radar, dict) or not isinstance(ir, dict):
        return
    if ir.get("cell_id") and not radar.get("cell_id"):
        radar["cell_id"] = ir.get("cell_id")
    for target, sources in IR_TO_RADAR_FIELDS.items():
        if radar.get(target) is not None:
            continue
        for source in sources:
            if ir.get(source) is not None:
                radar[target] = ir.get(source)
                break
    if (ir.get("radar_confirmed") is True or ir.get("status") == "radar_confirmed") and not radar.get("lineage_status"):
        radar["lineage_status"] = "radar_confirmed"


def dedupe_ir_precursors_for_payload(objects: list[dict], ir_tracks: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return radar objects plus only IR precursors that should stay visibly separate."""
    radar_objects = [dict(o) if isinstance(o, dict) else o for o in (objects or [])]
    ir_tracks = [dict(t) for t in (ir_tracks or []) if isinstance(t, dict)]

    radar_by_cell_id = {}
    for obj in radar_objects:
        if not isinstance(obj, dict):
            continue
        cid = obj.get("cell_id") or obj.get("id")
        if cid:
            radar_by_cell_id[str(cid)] = obj

    visible_ir = []
    for ir in ir_tracks:
        cid = ir.get("cell_id")
        radar = radar_by_cell_id.get(str(cid)) if cid else None
        if radar is not None:
            attach_ir_values_to_radar(radar, ir)
        if not _is_visible_ir_precursor(ir):
            continue
        if cid and str(cid) in radar_by_cell_id:
            continue
        visible_ir.append(ir)
    return radar_objects, visible_ir
