#!/usr/bin/env python3
"""Exercise installed console/module commands outside the framework source tree."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import takflow
from _wheel_smoke import check_installed_package


def main():
    check_installed_package(takflow, "takflow")
    console = Path(sys.executable).parent / "takflow"
    assert console.is_file()
    with tempfile.TemporaryDirectory(prefix="takflow-cli-wheel-") as directory:
        root = Path(directory)
        resources = root / "resources"
        for name, text in {
            "config/config.sh.j2": "DOMAIN=ready\n",
            "jobs/task.sh.j2": '#!/bin/bash\n. "{{ paths.config_file }}"\n',
            "runner.sh.j2": '#!/bin/bash\n. "{{ paths.jobs_dir }}/task.sh"\n',
        }.items():
            path = resources / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        (root / "wheel_domain.py").write_text('''from pathlib import Path
from takflow.application import Application, ApplicationBrand
from takflow.config import BaseWorkflowConfig

def application():
    return Application(config_type=BaseWorkflowConfig,
        resources=Path(__file__).parent / "resources", resource_entries=(),
        supported_modes=("shell",), shell_template="runner.sh.j2",
        brand=ApplicationBrand("wheel-domain", "1"))
''')
        config = root / "config.yaml"
        config.write_text('''project_base_dir: /program
run_base_dir: /target/runs
output_repo_base_dir: output
workflow_name: wheel_cli
workflow_mode: shell
workload:
  workload_type: shell
''')
        environment = {**os.environ, "PYTHONPATH": str(root)}
        def run(arguments, expected=0, module=False):
            command = [sys.executable, "-m", "takflow"] if module else [str(console)]
            result = subprocess.run([*command, *arguments], cwd=root, env=environment, text=True, capture_output=True)
            assert result.returncode == expected, (arguments, result.stdout, result.stderr)
            return result
        for module in (False, True):
            assert "build" in run(["--help"], module=module).stdout
            assert "takflow" in run(["--version"], module=module).stdout
        base = ["--application", "wheel_domain:application", "--format", "json"]
        options = ["--config-file", str(config)]
        report = json.loads(run([*base, "build", *options]).stdout)
        assert report["result"]["complete"]
        output = root / "output"
        manifest = output / "generation_manifest.json"
        assert manifest.is_file()
        for stage in ("resource", "config", "credential", "job", "workflow"):
            report = json.loads(run([*base, stage, "copy" if stage == "resource" else "generate", *options]).stdout)
            assert report["status"] == "success" and not report["result"]["complete"]
            assert not manifest.exists()
        assert run(["build"], expected=2).stderr
        (resources / "config/config.sh.j2").unlink()
        report = json.loads(run([*base, "build", *options], expected=1).stdout)
        assert report["result"]["stages"][1]["status"] == "failed" and not manifest.exists()
    print("Installed console/module help, version, full build, five stages, usage and missing-template failures passed")


if __name__ == "__main__":
    main()
