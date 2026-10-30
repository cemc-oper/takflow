"""Execute rendered invocations: exit codes must reach the ecFlow owner once."""

import os
import shutil
import subprocess

import pytest

from takflow.config import BaseWorkflowConfig
from takflow.toolkit import render_jobs_from_directory


def render(tmp_path, body, mode, *, workflow="ecflow", template=None):
    repo = tmp_path / "repo"
    output = tmp_path / "output with spaces"
    (repo / "jobs").mkdir(parents=True)
    (output / "scripts").mkdir(parents=True)
    script = output / "scripts/business.sh"
    script.write_text("#!/usr/bin/env bash\n" + body + "\n")
    script.chmod(0o755)
    (repo / "jobs/task.sh.j2").write_text(
        template or "{{ invoke_script('scripts/business.sh') }}"
    )
    config = BaseWorkflowConfig(
        project_base_dir=str(tmp_path), run_base_dir=str(tmp_path / "run"),
        workload={"workload_type": "shell"}, workflow_mode=workflow,
        script_invoke_mode=mode,
    )
    render_jobs_from_directory(config, repo, str(output))
    suffix = "ecf" if workflow == "ecflow" else "sh"
    return (output / f"jobs/task.{suffix}").read_text(), output


def execute(tmp_path, shell, rendered, output):
    # These fixtures contain only nopp/end directives, not includes or variables.
    body = "\n".join(
        line for line in rendered.splitlines() if line not in ("%nopp", "%end")
    )
    wrapper = """set -eu
ecflow_client() { printf '%s\n' "$*" >> "$CALLBACK_LOG"; }
ERROR() { set +e; ecflow_client --abort=trap; trap - 0; exit 0; }
ecflow_client --init=test
trap ERROR 0
parent_dir=$PWD
parent_value=original
set -- parent-argument
""" + body + """
test "$PWD" = "$parent_dir"
test "$parent_value" = original
test "$1" = parent-argument
ecflow_client --complete
trap - 0
exit 0
"""
    log = tmp_path / "callbacks"
    result = subprocess.run(
        [shell], input=wrapper, text=True, capture_output=True, timeout=10,
        cwd=tmp_path,
        env={**os.environ, "OUTPUT_REPO_BASE": str(output), "CALLBACK_LOG": str(log)},
    )
    assert result.returncode == 0, result.stderr
    return result, log.read_text().splitlines()


@pytest.fixture(params=["bash", "ksh"])
def shell(request):
    executable = shutil.which(request.param)
    if executable is None:
        pytest.skip(f"{request.param} is not installed")
    return executable


@pytest.mark.parametrize("mode", ["inline", "external"])
@pytest.mark.parametrize("body,success", [
    ("exit 0", True),
    ("exit 1", False),
    ("exit 7", False),
    ("echo business-done", True),
    ("# Empty marker task", True),
    ("set -e\nfalse\necho should-not-run", False),
    ("set +e\nexit 7", False),
    ("parent_value=changed\ncd /\nexit 0", True),
])
def test_ecflow_callbacks(tmp_path, shell, mode, body, success):
    rendered, output = render(tmp_path, body, mode)
    result, calls = execute(tmp_path, shell, rendered, output)
    assert calls == ["--init=test", "--complete" if success else "--abort=trap"]
    assert "should-not-run" not in result.stdout


def test_inline_inherits_errexit(tmp_path, shell):
    rendered, output = render(tmp_path, "false\necho should-not-run", "inline")
    result, calls = execute(tmp_path, shell, rendered, output)
    assert calls == ["--init=test", "--abort=trap"]
    assert "should-not-run" not in result.stdout


@pytest.mark.parametrize("mode", ["inline", "external"])
@pytest.mark.parametrize("rc", [0, 1])
def test_multiple_calls_continue_only_after_success(tmp_path, shell, mode, rc):
    template = """{{ invoke_script('scripts/business.sh', 'first') }}
{{ invoke_script('scripts/business.sh', 'second') }}"""
    body = f'echo "business:$1"\nexit {rc}'
    rendered, output = render(tmp_path, body, mode, template=template)
    result, calls = execute(tmp_path, shell, rendered, output)
    assert result.stdout.splitlines() == (
        ["business:first", "business:second"] if rc == 0 else ["business:first"]
    )
    assert calls == ["--init=test", "--complete" if rc == 0 else "--abort=trap"]


@pytest.mark.parametrize("mode", ["inline", "external"])
def test_arguments_are_literal_and_do_not_change_parent(tmp_path, shell, mode):
    argument = "space ' quote; $(touch UNEXPECTED)"
    template = "{{ invoke_script('scripts/business.sh', " + repr(argument) + ") }}"
    rendered, output = render(tmp_path, 'printf "%s\\n" "$1"', mode, template=template)
    result, calls = execute(tmp_path, shell, rendered, output)
    assert result.stdout.strip() == argument
    assert not (tmp_path / "UNEXPECTED").exists()
    assert calls == ["--init=test", "--complete"]


@pytest.mark.parametrize("workflow", ["shell", "takler"])
@pytest.mark.parametrize("mode", ["inline", "external"])
def test_other_backends_keep_existing_output(tmp_path, workflow, mode):
    rendered, output = render(tmp_path, "exit 0", mode, workflow=workflow)
    expected = (
        (output / "scripts/business.sh").read_text() if mode == "inline"
        else "${OUTPUT_REPO_BASE}/scripts/business.sh"
    )
    assert rendered.endswith(expected)


def test_include_raw_keeps_same_shell_semantics(tmp_path, shell):
    template = "{{ include_raw('scripts/business.sh') }}\ntest \"$loaded\" = yes"
    rendered, output = render(tmp_path, "loaded=yes", "inline", template=template)
    _, calls = execute(tmp_path, shell, rendered, output)
    assert calls == ["--init=test", "--complete"]
