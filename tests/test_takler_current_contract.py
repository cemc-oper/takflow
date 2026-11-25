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

from takflow.backends.takler.backend import TaklerBackend  # noqa: E402
from takflow.config import ShellWorkload, SlurmWorkload  # noqa: E402
from takflow.flow import WorkflowEngine  # noqa: E402
from takflow.jobs.submission import set_runtime  # noqa: E402
from takflow.jobs.submission.slsubmit6 import slsubmit6_parallel_job, slsubmit6_serial_job  # noqa: E402
from takflow.jobs.submission.variables import set_resource_variables  # noqa: E402
from takflow.jobspec import TaskResource  # noqa: E402
from takflow.jobspec.model import ResourceSpec  # noqa: E402
from takflow.jobspec.render import render_resource_block  # noqa: E402
from test_job_execution import BUSINESS_SCRIPT, build_business_workflow, check_business_job  # noqa: E402
from test_runtime_local_carrier import assert_command_argv  # noqa: E402


def _golden(tmp_path: Path, *, scheduler="local"):
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
    workload = (ShellWorkload(submit_carrier="orvix") if scheduler == "local"
                else SlurmWorkload(project="model", scheduler=scheduler))
    set_runtime(suite, workload, engine)
    output = tmp_path / "suite.json"
    engine.save_suite(suite, output)
    return output, source


def _load_flow(output: Path):
    bunch = Bunch()
    Scheduler(bunch).run_command_load(LoadCommand(flow_bytes=output.read_bytes()))
    return bunch.find_node("/suite")


@pytest.mark.parametrize("mode", ["inline", "external"])
def test_takler_preprocesses_and_runs_business_job(tmp_path, mode):
    flow = _load_flow(build_business_workflow(tmp_path, "takler", mode))
    flow.begin()
    task = flow.find_node("/suite/run")
    task.increment_try_no()
    source = Path(task.script_path).read_text()
    business = (tmp_path / "workflow output" / BUSINESS_SCRIPT).read_text()
    assert '{% include "env.sh" %}' in source

    task.create_job_script()
    job = Path(task.job_path)
    assert ("{% raw %}\n" + business + "\n{% endraw %}" in source) == (mode == "inline")
    rendered = job.read_text()
    assert (business in rendered) == (mode == "inline")
    assert 'export BUSINESS_INPUT="from-suite"' in rendered
    check_business_job(tmp_path, job, mode)


@pytest.mark.parametrize("mode", ["inline", "external"])
def test_public_takler_lifecycle_uses_current_attempt(tmp_path, mode):
    from takflow.build import build
    from test_build import application, data, put

    source = tmp_path / "source"
    output = tmp_path / "workflow output"
    put(source, "config/config.sh.j2", "# domain config\n")
    put(source, "scripts/on/model.sh", '#!/bin/sh\necho business\nexit "$BUSINESS_RC"\n')
    put(source, "jobs/on/run.sh.j2", """#!/bin/bash
{% raw %}
{% include "head.sh" %}
{% endraw %}
. "{{ paths.config_file }}"
{{ invoke_script("scripts/on/model.sh") }}
echo after-business
{% raw %}
{% include "tail.sh" %}
{% endraw %}
""")
    task_name = "model's-run"

    def suite_builder(config, engine):
        suite = engine.Suite("suite")
        suite.add_variables({"TAKLER_HOME": str(output / "home"),
                             "TAKLER_INCLUDE": str(output / "takler/include")})
        suite.add_task(task_name).add_variable("TAKLER_SCRIPT", str(output / "jobs/on/run.sh"))
        return suite

    app = application(source, suite_builder=suite_builder, use_public_resources=True)
    with app.prepare(data(output, "takler", mode, workflow_name="suite", machine_name=None)) as ctx:
        flow = _load_flow(build(ctx).workflow_output)
    flow.begin()
    task = flow.find_node(f"/suite/{task_name}")
    client = put(tmp_path, "bin/takler_client", """#!/bin/sh
set -eu
[ "$TAKLER_HOST" = localhost ] && [ "$TAKLER_PORT" = 33083 ] || exit 79
[ "$TAKLER_NAME" = "$EXPECTED_NAME" ] && [ "$TAKLER_ATTEMPT_ID" = "$EXPECTED_ATTEMPT" ] || exit 80
[ "${TAKLER_PASS-absent}" = "$EXPECTED_PASS" ] && [ "$TAKLER_RID" = "$PPID" ] || exit 81
echo "$1"
case "$1" in
    init) [ "$#" = 3 ] && [ "$2" = --task-id ] && [ "$3" = "$TAKLER_RID" ] || exit 82
          exit "$INIT_RC" ;;
    complete) [ "$#" = 1 ] || exit 83; exit "$COMPLETE_RC" ;;
    abort) [ "$#" = 3 ] && [ "$2" = --reason ] && [ "$3" = trap ] || exit 84; exit "$ABORT_RC" ;;
    *) exit 85 ;;
esac
""", 0o755)
    previous_attempt, previous_password = "inherited-attempt", "inherited-password"
    success = ["init", "business", "after-business", "complete"]
    failed = ["init", "business", "abort"]
    cases = [
        ("success", {}, 0, success),
        ("business", {"BUSINESS_RC": "7"}, 7, failed),
        ("abort", {"BUSINESS_RC": "7", "ABORT_RC": "23"}, 7, failed),
        ("init", {"INIT_RC": "17"}, 17, ["init"]),
        ("complete", {"COMPLETE_RC": "31"}, 31, success),
        ("no credential supplied", {}, 0, success),
    ]
    for case, overrides, expected, events in cases:
        task.increment_try_no()
        if not task.job_password or task.job_password == previous_password:
            pytest.fail("takler did not issue a fresh job credential")
        assert task.attempt_id and task.attempt_id != previous_attempt
        if case == "no credential supplied":
            task.job_password = None
        task.create_job_script()
        env = {**os.environ, "PATH": f"{client.parent}:{os.environ['PATH']}",
               "TAKLER_NAME": "/old/task", "TAKLER_ATTEMPT_ID": previous_attempt,
               "TAKLER_PASS": previous_password, "EXPECTED_NAME": task.node_path,
               "EXPECTED_ATTEMPT": task.attempt_id, "EXPECTED_PASS": task.job_password or "absent",
               "BUSINESS_RC": "0", "INIT_RC": "0", "COMPLETE_RC": "0", "ABORT_RC": "0", **overrides}
        run = subprocess.run(["bash", "-vx", task.job_path], cwd=tmp_path, env=env,
                             text=True, capture_output=True, timeout=10)
        if any(value and value in run.stdout + run.stderr for value in (task.job_password, previous_password)):
            pytest.fail("a job credential appeared in the job output")
        assert run.returncode == expected, case
        assert run.stdout.splitlines() == events, case
        if case == "abort":
            assert "takler abort failed: status=23" in run.stderr.splitlines()
        previous_attempt, previous_password = task.attempt_id, task.job_password


def test_backend_does_not_create_legacy_application_bunch(monkeypatch):
    def fail_if_created(*args, **kwargs):
        raise AssertionError("TaklerBackend must not create a legacy application Bunch")

    monkeypatch.setattr(
        "takflow.backends.takler.backend.Bunch", fail_if_created, raising=False
    )
    TaklerBackend(host="localhost", port="33083")


def test_suite_name_is_caller_supplied(tmp_path):
    engine = WorkflowEngine(TaklerBackend())
    suite = engine.Suite("research_flow")
    output = tmp_path / "research_flow.json"
    engine.save_suite(suite, output)

    assert "mcv" not in output.read_text(encoding="utf-8")
    document = parse_definition(output.read_bytes())
    assert build_definition(document).name == "research_flow"


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
    jobs = set()
    custom_job = str(tmp_path / "jobs $' with spaces" / "reruns" / "forecast.{attempt_id}.sh")
    for scheduler in ("local", "donau"):
        if scheduler == "donau":
            flow.add_parameter("ORVIX_SCHEDULER", scheduler)
            task.add_parameter("TAKLER_JOB", custom_job)
        task.increment_try_no()
        command = task.create_job_script()
        assert task.attempt_id and task.job_password
        assert task.job_path not in jobs and task.attempt_id in task.job_path
        jobs.add(task.job_path)
        if scheduler == "donau":
            assert task.job_path == custom_job.format(attempt_id=task.attempt_id)
        assert "jobs $' with spaces" in task.job_path and "jobs $' with spaces" in task.jobout_path
        assert task._uses_orvix() and task.orvix_info_path == task.job_path + ".info.yaml"
        assert_command_argv(command, "orvix", "submit", "--scheduler", scheduler, task.job_path)
        kill = ShellRender(task).render_command(task.find_parent_parameter("TAKLER_SHELL_KILL_CMD").value)
        assert_command_argv(kill, "orvix", "kill", task.orvix_info_path)
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


@pytest.mark.parametrize("scheduler", ["slurm", "donau"])
def test_scheduler_orvix_commands_render_without_submission(tmp_path, scheduler):
    output, _ = _golden(tmp_path, scheduler=scheduler)
    flow = _load_flow(output)
    flow.begin()
    task = flow.find_node("/suite/run")
    task.increment_try_no()

    command = task.create_job_script()
    kill = ShellRender(task).render_command(
        task.find_parent_parameter("TAKLER_SHELL_KILL_CMD").value
    )
    assert shlex.split(command) == [
        "orvix", "submit", "--scheduler", scheduler, task.job_path,
    ]
    assert shlex.split(kill) == ["orvix", "kill", task.orvix_info_path]
    assert Path(task.job_path).is_file()
    assert not Path(task.orvix_info_path).exists()
    assert not Path(task.jobout_path).exists()


def test_direct_local_commands_run_current_job(tmp_path):
    engine = WorkflowEngine(TaklerBackend())
    suite = engine.Suite("suite")
    suite.add_variable("TAKLER_HOME", str(tmp_path / "model's local jobs"))
    task = suite.add_task("run")
    source = tmp_path / "source.takler"
    source.write_text("#!/bin/sh\nprintf '%s\\n' '{{ TAKLER_ATTEMPT_ID }}'\n", encoding="utf-8")
    task.add_variable("TAKLER_SCRIPT", str(source))
    set_runtime(suite, ShellWorkload(submit_carrier="direct"), engine)
    output = tmp_path / "suite.json"
    engine.save_suite(suite, output)
    flow = _load_flow(output)
    flow.begin()
    loaded = flow.find_node("/suite/run")
    loaded.increment_try_no()
    command = loaded.create_job_script()
    loaded.add_parameter("TAKLER_RID", "12345")
    kill = ShellRender(loaded).render_command(
        loaded.find_parent_parameter("TAKLER_SHELL_KILL_CMD").value
    )
    assert shlex.split(kill) == ["kill", "-15", "12345"]
    assert not loaded._uses_orvix()
    assert loaded.orvix_info_path is None
    assert Path(loaded.job_path).is_file()
    assert loaded.attempt_id in Path(loaded.job_path).read_text(encoding="utf-8")
    subprocess.run(["/bin/sh", "-ec", command], check=True, timeout=5)
    assert Path(loaded.jobout_path).read_text().splitlines() == [loaded.attempt_id]


@pytest.mark.parametrize("job_type", ["serial", "parallel"])
def test_direct_slurm_is_rejected_before_setting_commands(job_type):
    engine = WorkflowEngine(TaklerBackend())
    task = engine.Suite("suite").add_task("run")
    workload = SlurmWorkload(project="model", submit_carrier="slsubmit6")
    with pytest.raises(ValueError, match="takler does not support slsubmit6"):
        set_runtime(task, workload, engine, TaskResource(job_type=job_type))
    assert task.raw.find_parent_parameter("TAKLER_SHELL_JOB_CMD") is None
    assert task.raw.find_parent_parameter("TAKLER_SHELL_KILL_CMD") is None
    with pytest.raises(ValueError, match="takler does not support slsubmit6"):
        if job_type == "serial":
            slsubmit6_serial_job(engine)
        else:
            slsubmit6_parallel_job(engine, 2, 4)


def test_unsupported_attributes_fail_with_stable_errors():
    engine = WorkflowEngine(TaklerBackend())
    task = engine.Suite("suite").add_task("task")

    with pytest.raises(NotImplementedError) as label_error:
        task.add_label("owner", "research")
    assert str(label_error.value) == (
        "takler backend does not support labels (ecflow-only attribute)"
    )

    with pytest.raises(NotImplementedError) as late_error:
        task.add_late(submitted=(0, 10))
    assert str(late_error.value) == "takler backend does not support late"

    with pytest.raises(NotImplementedError) as repeat_day_error:
        task.add_repeat_day(1)
    assert str(repeat_day_error.value) == "takler backend does not support repeat_day"


def test_shared_resource_header_follows_takler_parent_edits(tmp_path):
    from takflow.jobs.headers import render_orvix_resource_block

    engine = WorkflowEngine(TaklerBackend())
    suite = engine.Suite("suite")
    source = tmp_path / "shared.sh"
    original = "#!/bin/sh\n" + render_orvix_resource_block(
        job_type="parallel", workflow_mode="takler", time="06:00:00",
        queue="fallback", application="model-default", job_name="model", output="{{ TAKLER_JOBOUT }}",
    ) + "\ntrue\n"
    source.write_text(original)
    suite.add_variable("TAKLER_HOME", str(tmp_path / "jobs"))
    set_runtime(suite, SlurmWorkload(project="model"), engine)
    family = suite.add_family("fcst")
    set_resource_variables(family, TaskResource(
        job_type="parallel", queue="batch", nodes=4, ntasks_per_node=32,
    ))
    for name, resource in (
        ("inherited", TaskResource(time="00:40:00", memory=None)),
        ("fixed", TaskResource(job_type="parallel", queue="batch", nodes=4, requeue=True)),
    ):
        node = family.add_task(name)
        node.add_variable("TAKLER_SCRIPT", str(source))
        set_resource_variables(node, resource)
    path = tmp_path / "suite.json"
    engine.save_suite(suite, path)
    flow = _load_flow(path)
    flow.begin()
    parent = flow.find_node("/suite/fcst")
    previous = {}
    for attempt, state in enumerate((None, False, True)):
        if state is not None:
            parent.add_parameter({"REQUEUE": state, "MEMORY": f"{8 + attempt}G", "NODES": 4 + attempt,
                                  "TASKS_PER_NODE": 32 + attempt, "WALLTIME": "01:10:00",
                                  "QUEUE": "new-batch", "APPLICATION": "model-app", "JOB_NAME": "updated",
                                  "JOB_OUTPUT": "{{ TAKLER_JOBOUT }}.rerun", "JOB_ERROR": "/log dir/%j.err"})
        for name in ("inherited", "fixed"):
            fixed = name == "fixed"
            task = flow.find_node(f"/suite/fcst/{name}")
            task.increment_try_no()
            task.create_job_script()
            job = Path(task.job_path)
            assert job not in previous
            lines = job.read_text().splitlines()
            expected = {
                "queue": "batch" if fixed or not attempt else "new-batch",
                "time": ("01:10:00" if attempt else "06:00:00") if fixed else "00:40:00",
                "nodes": 4 if fixed else 4 + attempt, "ntasks-per-node": 32 + attempt,
                "memory": f"{8 + attempt}G" if attempt else None, "project": "model",
                "requeue": "true" if fixed else (str(state).lower() if state is not None else None),
                "application": "model-app" if attempt else "model-default",
                "job-name": '"updated"' if attempt else '"model"',
            }
            for key, value in expected.items():
                assert [line for line in lines if line.startswith(f"#ORVIX {key}=")] == (
                    [] if value is None else [f"#ORVIX {key}={value}"])
            logfile = str(task.jobout_path) + (".rerun" if attempt else "")
            assert [line for line in lines if line.startswith("#ORVIX output=")] == [f'#ORVIX output="{logfile}"']
            assert [line for line in lines if line.startswith("#ORVIX error=")] == (
                ['#ORVIX error="/log dir/%j.err"'] if attempt else [])
            previous[job] = job.read_bytes()
        assert source.read_text() == original
        assert all(job.read_bytes() == content for job, content in previous.items())
