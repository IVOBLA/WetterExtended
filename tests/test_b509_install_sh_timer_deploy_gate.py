from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
TIMER_TEMPLATE = REPO_ROOT / "wetterprojekt-debug-export-branch.timer"


def test_old_full_mode_gate_removed() -> None:
    install_sh = INSTALL_SH.read_text(encoding="utf-8")

    assert 'if [[ "$MODE" == "full" && "$ENABLE_DEBUG_EXPORT_GIT" == true ]]; then' not in install_sh


def test_debug_export_git_gate_remains_without_mode_restriction() -> None:
    install_sh = INSTALL_SH.read_text(encoding="utf-8")

    assert 'if [[ "$ENABLE_DEBUG_EXPORT_GIT" == true ]]; then' in install_sh


def test_timer_template_copy_line_is_unchanged() -> None:
    install_sh = INSTALL_SH.read_text(encoding="utf-8")

    assert 'sudo cp "$DEBUG_EXPORT_TIMER_SRC" "/etc/systemd/system/$DEBUG_EXPORT_TIMER"' in install_sh


def test_timer_template_targets_nightly_analysis_dispatcher() -> None:
    timer_template = TIMER_TEMPLATE.read_text(encoding="utf-8")

    assert "Unit=wetterprojekt-nightly-analysis.service" in timer_template
