from argparse import Namespace
from pathlib import Path

import pytest

from tools.publish_latest_debug_export_branch import (
    DEFAULT_BRANCH,
    DEFAULT_MAX_SOURCE_TOTAL_MB,
    DEFAULT_MAX_ZIP_MB,
    DEFAULT_TARGET_PATH,
    PublisherError,
    parse_args,
    publish,
    validate_relative_path,
)


def test_default_branch_is_debug_export_latest():
    assert DEFAULT_BRANCH == "debug-export-latest"


def test_default_target_path_is_latest_last24h_zip():
    assert DEFAULT_TARGET_PATH == "debug_exports/wetterextended_debug_latest_last24h.zip"


def test_default_size_limits_are_separate_source_and_zip_limits():
    assert DEFAULT_MAX_SOURCE_TOTAL_MB == 512
    assert DEFAULT_MAX_ZIP_MB == 90


def test_parse_args_accepts_separate_source_and_zip_limits():
    args = parse_args(["--max-source-total-mb", "512", "--max-zip-mb", "90"])
    assert args.max_source_total_mb == 512
    assert args.max_zip_mb == 90


def test_parse_args_accepts_legacy_max_total_mb_as_source_limit(monkeypatch):
    monkeypatch.delenv("WETTER_DEBUG_EXPORT_MAX_SOURCE_TOTAL_MB", raising=False)
    monkeypatch.delenv("WETTER_DEBUG_EXPORT_MAX_TOTAL_MB", raising=False)
    args = parse_args(["--max-total-mb", "256"])
    assert args.max_source_total_mb == 256
    assert args.max_zip_mb == DEFAULT_MAX_ZIP_MB


def test_parse_args_uses_new_environment_fallbacks(monkeypatch):
    monkeypatch.setenv("WETTER_DEBUG_EXPORT_MAX_SOURCE_TOTAL_MB", "512")
    monkeypatch.setenv("WETTER_DEBUG_EXPORT_MAX_ZIP_MB", "90")
    args = parse_args([])
    assert args.max_source_total_mb == 512
    assert args.max_zip_mb == 90


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


def _publish_args(tmp_path: Path, *, max_zip_mb: int, dry_run: bool = True) -> Namespace:
    return Namespace(
        repo_dir=tmp_path,
        branch=DEFAULT_BRANCH,
        target_path=validate_relative_path(DEFAULT_TARGET_PATH),
        hours=24,
        max_source_total_mb=512,
        max_zip_mb=max_zip_mb,
        check_only=False,
        dry_run=dry_run,
    )


def test_publish_accepts_zip_below_final_zip_limit(monkeypatch, tmp_path):
    zip_path = tmp_path / "export.zip"
    zip_path.write_bytes(b"x" * 1024)
    captured = {}

    monkeypatch.setattr("tools.publish_latest_debug_export_branch.ensure_repo", lambda repo_dir: None)
    monkeypatch.setattr(
        "tools.publish_latest_debug_export_branch.create_export",
        lambda repo_dir, hours, max_source_total_mb, max_zip_mb: (zip_path, "export.zip", {"ok": True}),
    )

    def fake_write_branch_repo(**kwargs):
        captured.update(kwargs)
        return {"target_path": kwargs["target_path"].as_posix()}

    monkeypatch.setattr("tools.publish_latest_debug_export_branch.write_branch_repo", fake_write_branch_repo)

    publish(_publish_args(tmp_path, max_zip_mb=1))

    assert captured["max_source_total_mb"] == 512
    assert captured["max_zip_mb"] == 1
    assert captured["zip_size_bytes"] == 1024
    assert not zip_path.exists()


def test_publish_rejects_zip_above_final_zip_limit(monkeypatch, tmp_path):
    zip_path = tmp_path / "export.zip"
    zip_path.write_bytes(b"x" * (1024 * 1024 + 1))

    monkeypatch.setattr("tools.publish_latest_debug_export_branch.ensure_repo", lambda repo_dir: None)
    monkeypatch.setattr(
        "tools.publish_latest_debug_export_branch.create_export",
        lambda repo_dir, hours, max_source_total_mb, max_zip_mb: (zip_path, "export.zip", {}),
    )

    with pytest.raises(PublisherError, match="Finale ZIP-Datei ist zu groß für GitHub"):
        publish(_publish_args(tmp_path, max_zip_mb=1))

    assert not zip_path.exists()


def test_timer_runs_daily_at_2359():
    timer = Path("wetterprojekt-debug-export-branch.timer").read_text(encoding="utf-8")
    assert "OnCalendar=*-*-* 23:59:00" in timer


def test_service_sets_default_debug_export_branch():
    service = Path("wetterprojekt-debug-export-branch.service").read_text(encoding="utf-8")
    assert "WETTER_DEBUG_EXPORT_BRANCH=debug-export-latest" in service


def test_service_uses_separate_source_and_zip_limits():
    service = Path("wetterprojekt-debug-export-branch.service").read_text(encoding="utf-8")
    assert "Environment=WETTER_DEBUG_EXPORT_MAX_SOURCE_TOTAL_MB=512" in service
    assert "Environment=WETTER_DEBUG_EXPORT_MAX_ZIP_MB=90" in service
    assert "Environment=WETTER_DEBUG_EXPORT_MAX_TOTAL_MB=90" not in service


def test_install_sh_uses_check_only_for_write_test():
    install_sh = Path("install.sh").read_text(encoding="utf-8")
    assert "--check-only" in install_sh


def test_install_sh_enables_only_debug_export_timer():
    install_sh = Path("install.sh").read_text(encoding="utf-8")
    assert "sudo systemctl enable --now wetterprojekt-debug-export-branch.timer" in install_sh


def test_install_sh_generates_separate_source_and_zip_limit_environment():
    install_sh = Path("install.sh").read_text(encoding="utf-8")
    assert "DEBUG_EXPORT_MAX_SOURCE_TOTAL_MB=512" in install_sh
    assert "DEBUG_EXPORT_MAX_ZIP_MB=90" in install_sh
    assert "Environment=WETTER_DEBUG_EXPORT_MAX_SOURCE_TOTAL_MB=$DEBUG_EXPORT_MAX_SOURCE_TOTAL_MB" in install_sh
    assert "Environment=WETTER_DEBUG_EXPORT_MAX_ZIP_MB=$DEBUG_EXPORT_MAX_ZIP_MB" in install_sh
    assert "WETTER_DEBUG_EXPORT_MAX_TOTAL_MB=90" not in install_sh
