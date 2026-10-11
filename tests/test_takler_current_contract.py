"""Takler definition and orvix carrier contract without submitting a job."""

import os
import shlex
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("takler")

from takler.core import Bunch, Flow  # noqa: E402
from takler.protocol.commands import LoadCommand  # noqa: E402
from takler.schema.definition import parse_definition  # noqa: E402
from takler.serialization.builder import build_definition  # noqa: E402
from takler.server.scheduler import Scheduler  # noqa: E402
from takler.tasks.shell.shell_render import ShellRender  # noqa: E402
from takler.tasks.shell.shell_script_task import ShellScriptTask  # noqa: E402

from takflow.backends.runtime.orvix import orvix_job  # noqa: E402
from takflow.backends.takler.backend import TaklerBackend  # noqa: E402
from takflow.flow import WorkflowEngine  # noqa: E402
from takflow.jobspec.model import ResourceSpec  # noqa: E402
from takflow.jobspec.render import render_resource_block  # noqa: E402


def _golden(tmp_path: Path):
    engine = WorkflowEngine(TaklerBackend(host="localhost", port="33083"))
    suite = engine.Suite("suite")
    suite.add_variable("TAKLER_HOME", str(tmp_path / "jobs $' with spaces"))
    suite.add_limit("slots", 2)
    suite.add_repeat_date("DAY", 20260101, 20260102)
    suite.add_task("prepare")
    task = suite.add_task("run")
    task.add_trigger("/suite/prepare == complete")
    task.add_inlimit("slots")
    source = tmp_path / "scripts with spaces" / "source.takler"
    source.parent.mkdir()
    source.write_text(
        "#!/bin/sh\n"
        + render_resource_block(ResourceSpec(
            job_name="suite task",
            output="{{ TAKLER_JOBOUT }}",
            error="{{ TAKLER_JOBOUT }}.err",
        ))
        + "\nprintf '%s\\n' '{{ TAKLER_ATTEMPT_ID }}'\n"
        + "printf '%s\\n' '{{ TAKLER_PASS }}'\n",
        encoding="utf-8",
    )
    task.add_variables({"TAKLER_SCRIPT": str(source), "CONFIG": "alpha"})
    task.add_variables(orvix_job(engine, "local"))
    output = tmp_path / "suite.json"
    engine.save_suite(suite, output)
    return output, source


def _load_flow(output: Path):
    bunch = Bunch()
    Scheduler(bunch).run_command_load(LoadCommand(flow_bytes=output.read_bytes()))
    return bunch.find_node("/suite")


def test_saved_suite_builds_and_loads_current_definition(tmp_path):
    output, source = _golden(tmp_path)
    document = parse_definition(output.read_bytes())
    assert document.kind == "takler.definition"
    assert document.root.type_id == "takler.flow"
    detached = build_definition(document)
    assert isinstance(detached, Flow)
    assert detached.find_node("/suite/run").script_path == str(source)
    assert detached.find_limit("slots").limit == 2
    assert detached.repeat.value() == 20260101

    loaded = _load_flow(output)
    assert loaded is not None and not loaded.begun
    task = loaded.find_node("/suite/run")
    assert isinstance(task, ShellScriptTask)
    assert task.find_user_parameter("CONFIG").value == "alpha"
    assert task.trigger_expression.expression_str == "/suite/prepare == complete"
    assert task.in_limit_manager.in_limit_list[0].limit is loaded.find_limit("slots")
    assert task.script_path == str(source)


def test_rendered_orvix_commands_bind_attempt_and_quote_paths(tmp_path):
    output, _ = _golden(tmp_path)
    flow = _load_flow(output)
    flow.begin()
    task = flow.find_node("/suite/run")
    task.increment_try_no()
    command = task.create_job_script()
    assert task.attempt_id and task.job_password
    assert task.job_path and "jobs $' with spaces" in task.job_path
    assert task.jobout_path and "jobs $' with spaces" in task.jobout_path
    assert task.orvix_info_path == task.job_path + ".info.yaml"
    assert task._uses_orvix()
    assert shlex.split(command) == [
        "orvix", "submit", "--scheduler", "local", task.job_path,
    ]
    quoted_path = command.replace(
        "orvix submit --scheduler local ", "printf '%s\\n' ", 1
    )
    assert subprocess.run(
        ["/bin/sh", "-c", quoted_path], check=True, capture_output=True, text=True
    ).stdout.strip() == task.job_path
    kill = ShellRender(task).render_command(
        task.find_parent_parameter("TAKLER_SHELL_KILL_CMD").value
    )
    assert shlex.split(kill) == ["orvix", "kill", task.orvix_info_path]
    quoted_info = kill.replace("orvix kill ", "printf '%s\\n' ", 1)
    assert subprocess.run(
        ["/bin/sh", "-c", quoted_info], check=True, capture_output=True, text=True
    ).stdout.strip() == task.orvix_info_path
    rendered = Path(task.job_path).read_text(encoding="utf-8")
    assert "{{" not in rendered and "}}" not in rendered
    assert task.attempt_id in rendered and task.job_password in rendered
    assert '#ORVIX job-name="suite task"' in rendered
    assert f'#ORVIX output="{task.jobout_path}"' in rendered
    assert f'#ORVIX error="{task.jobout_path}.err"' in rendered
    assert not Path(task.orvix_info_path).exists()
    assert not Path(task.jobout_path).exists()


def test_real_orvix_generate_accepts_rendered_job_without_submit(tmp_path):
    binary = os.environ.get("ORVIX_BIN")
    if not binary:
        pytest.skip("set ORVIX_BIN for paired orvix validation")
    output, _ = _golden(tmp_path)
    flow = _load_flow(output)
    flow.begin()
    task = flow.find_node("/suite/run")
    task.increment_try_no()
    task.create_job_script()
    translated = tmp_path / "translated with spaces.sh"
    subprocess.run(
        [binary, "generate", "--scheduler", "local", "--output-script",
         str(translated), task.job_path],
        check=True, capture_output=True, text=True,
    )
    assert translated.is_file()
    assert "{{" not in translated.read_text(encoding="utf-8")
    assert not Path(task.orvix_info_path).exists()


def test_unsupported_late_and_repeat_day_fail_explicitly():
    engine = WorkflowEngine(TaklerBackend())
    task = engine.Suite("suite").add_task("task")
    with pytest.raises(NotImplementedError, match="late"):
        task.add_late(submitted=(0, 10))
    with pytest.raises(NotImplementedError, match="repeat_day"):
        task.add_repeat_day(1)
