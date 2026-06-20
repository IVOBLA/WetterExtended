from radar_frame_selection import remember_valid_radar_path, select_optflow_prev_radar_path


def test_optflow_uses_last_valid_prev_when_immediate_prev_missing(tmp_path):
    last_valid = tmp_path / "radar_2026-06-20_10-00-00.png"
    last_valid.write_bytes(b"png")
    missing_immediate = tmp_path / "radar_2026-06-20_10-05-00.png"

    assert select_optflow_prev_radar_path(str(missing_immediate), str(last_valid)) == str(last_valid)


def test_remember_valid_radar_path_keeps_existing_last_valid_when_current_missing(tmp_path):
    last_valid = tmp_path / "radar_2026-06-20_10-00-00.png"
    last_valid.write_bytes(b"png")
    missing_current = tmp_path / "radar_2026-06-20_10-10-00.png"

    assert remember_valid_radar_path(str(missing_current), str(last_valid)) == str(last_valid)
