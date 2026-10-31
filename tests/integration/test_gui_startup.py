"""Real GUI startup in separate processes with background warm-up enabled."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("case", ["warm", "close-style", "close-customize"])
def test_real_startup_and_constructor_close(case: str, tmp_path: Path) -> None:
    pytest.importorskip("customtkinter")
    if sys.platform != "win32" and case != "warm":
        pytest.skip("The constructor nested-update race is Windows-specific")
    if sys.platform != "win32" and not os.environ.get("DISPLAY"):
        pytest.skip("Real startup needs a graphical display")
    report = tmp_path / "result.json"
    env = dict(
        os.environ,
        AUDIO8D_HOME=str(tmp_path),
        AUDIO8D_NO_WT="1",
        AUDIO8D_GUI_SMOKE_REPORT=str(report),
        AUDIO8D_GUI_SMOKE_CASE=case,
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from src.gui import run_gui; raise SystemExit(run_gui())",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        timeout=75,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert report.is_file(), completed.stdout + completed.stderr
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["success"], data
    assert data["errors"] == []
    assert data["warm_dialogs_ready"] if case == "warm" else data["close_injected"]
