"""Conformance tests: takflow-rendered #ORVIX scripts vs orvix output.

For each case x scheduler:
  1. rebuild the vector script from the shared cases (proving render stability
     against the committed ``vectors/<name>.sh``);
  2. run ``orvix generate --scheduler X`` on the committed vector;
  3. diff the result against the committed ``golden/X/<name>.submit``.

Requires an ``orvix`` binary (``ORVIX_BIN`` env var or on ``PATH``). If none is
found, the orvix-dependent tests are skipped (not failed) so the suite still
runs in environments without orvix.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from takflow.spec.jobspec.conformance import CASES, SCHEDULERS, build_script

HERE = Path(__file__).resolve()
CONF_DIR = (
    HERE.parents[1]
    / "src" / "takflow" / "spec" / "jobspec" / "conformance"
)
VECTORS_DIR = CONF_DIR / "vectors"
GOLDEN_DIR = CONF_DIR / "golden"


def _find_orvix() -> str | None:
    return os.environ.get("ORVIX_BIN") or shutil.which("orvix")


orvix_required = pytest.mark.skipif(
    _find_orvix() is None,
    reason="orvix binary not found (set ORVIX_BIN or add to PATH)",
)

CASE_NAMES = sorted(CASES)


@pytest.mark.parametrize("name", CASE_NAMES)
def test_rendered_script_matches_committed_vector(name):
    """The committed vector must equal what build_script() produces now."""
    committed = (VECTORS_DIR / f"{name}.sh").read_text(encoding="utf-8")
    assert build_script(CASES[name]) == committed


@orvix_required
@pytest.mark.parametrize("scheduler", SCHEDULERS)
@pytest.mark.parametrize("name", CASE_NAMES)
def test_orvix_generate_matches_golden(name, scheduler):
    orvix = _find_orvix()
    vector = VECTORS_DIR / f"{name}.sh"
    golden = (GOLDEN_DIR / scheduler / f"{name}.submit").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.submit"
        proc = subprocess.run(
            [orvix, "generate", "--scheduler", scheduler,
             "--output-script", str(out), str(vector)],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stderr
        produced = out.read_text(encoding="utf-8")
    assert produced == golden, (
        f"orvix output drifted from golden for {name}/{scheduler}.\n"
        f"--- golden ---\n{golden}\n--- produced ---\n{produced}"
    )
