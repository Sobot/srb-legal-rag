"""Security regressions: no live PIS archive can run without access gates."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/ci_live_one_act_smoke.py"


@pytest.mark.parametrize(
    ("visibility", "written_consent"),
    [
        ("public", "true"),
        ("private", "false"),
        ("public", "false"),
    ],
)
def test_live_archive_is_blocked_before_network(tmp_path, visibility, written_consent):
    env = {**os.environ,
           "GITHUB_REPOSITORY_VISIBILITY": visibility,
           "PIS_WRITTEN_CONSENT": written_consent}
    report = tmp_path / "report.json"
    bundle = tmp_path / "private-kb"
    process = subprocess.run(
        [sys.executable, str(RUNNER), "--report", str(report),
         "--bundle-dir", str(bundle)],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert process.returncode != 0
    assert "private repository and written consent" in process.stderr
    assert not report.exists()
    assert not bundle.exists()
