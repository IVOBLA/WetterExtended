from pathlib import Path

import pytest

from tools.publish_latest_debug_export_branch import (
    DEFAULT_BRANCH,
    DEFAULT_TARGET_PATH,
    PublisherError,
    validate_relative_path,
)


def test_default_branch_is_debug_export_latest():
    assert DEFAULT_BRANCH == "debug-export-latest"


def test_default_target_path_is_latest_last24h_zip():
    assert DEFAULT_TARGET_PATH == "debug_exports/wetterextended_debug_latest_last24h.zip"


def test_validate_relative_path_accepts_default_path():
    assert validate_relative_path(DEFAULT_TARGET_PATH).as_posix() == DEFAULT_TARGET_PATH


@pytest.mark.parametrize(
    "bad_path",
    [
        "/tmp/export.zip",
        "../export.zip",
        "debug_exports/not_zip.txt",
        ".git/export.zip",
    ],
)
def test_validate_relative_path_rejects_unsafe_paths(bad_path):
    with pytest.raises(PublisherError):
        validate_relative_path(bad_path)


def test_timer_runs_daily_at_2359():
    timer = Path("wetterprojekt-debug-export-branch.timer").read_text(encoding="utf-8")
    assert "OnCalendar=*-*-* 23:59:00" in timer


def test_service_sets_default_debug_export_branch():
    service = Path("wetterprojekt-debug-export-branch.service").read_text(encoding="utf-8")
    assert "WETTER_DEBUG_EXPORT_BRANCH=debug-export-latest" in service


def test_install_sh_uses_check_only_for_write_test():
    install_sh = Path("install.sh").read_text(encoding="utf-8")
    assert "--check-only" in install_sh


def test_install_sh_enables_only_debug_export_timer():
    install_sh = Path("install.sh").read_text(encoding="utf-8")
    assert "sudo systemctl enable --now wetterprojekt-debug-export-branch.timer" in install_sh
