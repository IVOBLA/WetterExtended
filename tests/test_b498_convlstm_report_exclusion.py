import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_local_analysis_prompt_excludes_convlstm_training_errors():
    prompt = (REPO_ROOT / "docs/LOCAL_ANALYSIS_PROMPT.md").read_text()

    assert "Ausnahme ConvLSTM (B498)" in prompt


def test_hailo_a10_documents_dormant_convlstm_status():
    integration = (REPO_ROOT / "docs/HAILO_INTEGRATION.md").read_text()
    a10_section = integration.split("#### A10 — ConvLSTM MODEL_PATH", 1)[1].split(
        "\n#### ", 1
    )[0]

    assert "dormant seit Einfuehrung" in a10_section


def test_predict_radar_convlstm_still_has_no_callers():
    symbol = "predict_radar_" + "convlstm("
    command = (
        f'grep -rn "{symbol}" --include="*.py" . '
        '| grep -v "^\\./radar_convlstm.py:.*def predict_radar_convlstm"'
    )
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        shell=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == "", f"Unerwartete Aufrufer gefunden:\n{result.stdout}"
