"""CI wrapper: the use-case harness doubles as the integration test suite."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_usecases_all_green():
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_usecases.py")],
        capture_output=True, text=True, cwd=ROOT, timeout=300,
    )
    assert r.returncode == 0, (
        f"use-case harness failed:\n{r.stdout}\n{r.stderr}")
    assert "0 failed" in r.stdout
    # the harness regenerates the report as a side effect; make sure it exists
    assert (ROOT / "docs" / "TEST_REPORT.md").exists()
