from pathlib import Path


def _source():
    return Path("main.py").read_text(encoding="utf-8")


def _no_cells_block():
    src = _source()
    start = src.index("no_cells_handled = False")
    end = src.index("if radar_ok and image is not None and objects:", start)
    return src[start:end]


def test_no_cells_save_forecast_kmz_called_once():
    assert _no_cells_block().count("save_forecast_as_kmz(") == 1


def test_no_cells_latest_objects_empty():
    assert "json.dump([], _eof" in _no_cells_block()


def test_no_cells_forecast_empty():
    assert "_empty_forecasts = {h: []" in _no_cells_block()


def test_no_cells_empty_object_file_written():
    assert "Leeres Object-File gespeichert" in _no_cells_block()


def test_no_cells_empty_location_hits_written():
    assert "Leere Location-Hits gespeichert" in _no_cells_block()


def test_no_cells_log_contains_no_cells_kmz():
    assert "[NO-CELLS] Leeres KMZ gespeichert" in _no_cells_block()


def test_no_cells_log_not_contains_keine_vollstaendigen_daten():
    assert "Keine vollständigen Daten" not in _no_cells_block()


def test_no_cells_overlay_and_ftp_not_skipped():
    src = _source()
    assert "continue" not in _no_cells_block()
    assert "create_movement_gif" in src and "upload_file_ftp" in src


def test_previous_active_cell_not_reactive_after_no_cells():
    src = _source()
    no_cells_start = src.index("no_cells_handled = False")
    else_start = src.index("elif not no_cells_handled", no_cells_start)
    assert else_start > no_cells_start
    assert "save_forecast_as_kmz({}, {})" not in src[else_start:else_start + 200]
