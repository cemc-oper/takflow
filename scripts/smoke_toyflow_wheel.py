#!/usr/bin/env python3
"""Run toyflow's generation pipeline using installed, non-editable packages."""
from __future__ import annotations

import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import takflow
import toyflow

TAKFLOW_ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = TAKFLOW_ROOT / "examples" / "toyflow" / "config" / "toyflow.yaml"


def main() -> None:
    executable = Path(sys.executable).with_name("toyflow")
    if not executable.is_file():
        raise SystemExit(f"installed toyflow entry point not found: {executable}")

    with tempfile.TemporaryDirectory(prefix="takflow-wheel-smoke-") as tmp:
        output = Path(tmp) / "output"
        for command in (
            ("resource", "copy"),
            ("config", "generate"),
            ("job", "generate"),
            ("workflow", "generate"),
        ):
            subprocess.run(
                [
                    str(executable),
                    *command,
                    "--config-file",
                    str(CONFIG_FILE),
                    "--output-repo-base",
                    str(output),
                ],
                check=True,
            )

        config_path = output / "config" / "config.h"
        forecast_path = output / "jobs" / "main" / "forecast.ecf"
        verify_path = output / "jobs" / "main" / "verify.ecf"
        definition_path = output / "toyflow.def"
        for path in (config_path, forecast_path, verify_path, definition_path):
            assert path.is_file(), f"generated file missing: {path}"
        for path in (config_path, forecast_path, verify_path):
            assert path.stat().st_mode & stat.S_IXUSR, f"not executable: {path}"

        definition = definition_path.read_text(encoding="utf-8")
        assert "suite toyflow" in definition
        assert "task verify" in definition
        assert "/toyflow/obs/prepare == complete" in definition
        assert "#ORVIX nodes=2" in forecast_path.read_text(encoding="utf-8")

    print(f"Installed takflow: {takflow.__file__}")
    print(f"Installed toyflow: {toyflow.__file__}")
    print("Installed toyflow ecFlow generation smoke passed")


if __name__ == "__main__":
    main()
