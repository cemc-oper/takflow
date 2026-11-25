"""Native ecFlow parsing, job preprocessing and local Bash and Ksh93 execution.

The dedicated native contract gate must provide ecFlow and reject all skips.
Ordinary source tests may run without this optional system dependency.
"""
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import time

import pytest

from takflow.flow.backends.ecflow import EcflowBackend
from takflow.checks import GenerationCheckReport, check_definition_output
from takflow.flow import WorkflowEngine
from takflow.jobs.submission import set_runtime
from takflow.jobs.submission.variables import ecflow_resource_variables, set_resource_variables
from test_build import resources
from test_runtime_local_carrier import assert_command_argv


ecflow = pytest.importorskip("ecflow", reason="native ecFlow is not installed")


def _save_suite(tmp_path: Path):
    scripts = tmp_path / "scripts"
    includes = tmp_path / "include"
    scripts.mkdir()
    includes.mkdir()
    engine = WorkflowEngine(EcflowBackend())
    suite = engine.Suite("native_gate")
    suite.add_variables({
        "ECF_HOME": str(tmp_path / "home"),
        "ECF_FILES": str(scripts),
        "ECF_INCLUDE": str(includes),
        "MESSAGE": "from-definition",
    })
    suite.add_task(engine.Task("smoke"))
    output = tmp_path / "native.def"
    engine.save_suite(suite, output)
    return suite, output, scripts, includes


def test_native_ecflow_parses_takflow_definition(tmp_path):
    suite, output, _, _ = _save_suite(tmp_path)
    report = GenerationCheckReport()

    check_definition_output(suite, output, check_report=report)

    assert ecflow.Defs(str(output)).find_abs_node("/native_gate/smoke") is not None
    assert any(item.code == "GEN_NATIVE_ECFLOW_VALID" and item.status == "passed"
               for item in report.checks)
    assert not any(item.code == "GEN_NATIVE_ECFLOW_UNAVAILABLE" for item in report.checks)


def test_native_ecflow_preprocesses_job_without_running_it(tmp_path):
    _, output, scripts, includes = _save_suite(tmp_path)
    marker = tmp_path / "business-command-was-run"
    (includes / "head.h").write_text('echo "native-head:%MESSAGE%"\n')
    (includes / "tail.h").write_text('echo "native-tail"\n')
    (scripts / "smoke.ecf").write_text(
        '#!/bin/sh\n%include <head.h>\n'
        'echo "task:%ECF_NAME%"\n'
        f'touch "{marker}"\n'
        '%include <tail.h>\n'
    )
    generated = tmp_path / "jobs"
    control = ecflow.JobCreationCtrl()
    control.set_dir_for_job_creation(str(generated))

    ecflow.Defs(str(output)).check_job_creation(control)

    assert control.get_error_msg() == ""
    jobs = list(generated.rglob("*.job0"))
    assert len(jobs) == 1
    text = jobs[0].read_text()
    assert 'echo "native-head:from-definition"' in text
    assert 'echo "task:/native_gate/smoke"' in text
    assert 'echo "native-tail"' in text
    assert "%include" not in text
    assert "%MESSAGE%" not in text
    assert not marker.exists(), "native preprocessing must not run business commands"


@pytest.mark.parametrize("carrier", ["orvix", "slsubmit6", "direct"])
def test_native_ecflow_commands_use_current_try(tmp_path, carrier):
    from takflow.config import ShellWorkload, SlurmWorkload

    suite, output, _, _ = _save_suite(tmp_path)
    workload = ShellWorkload() if carrier == "direct" else SlurmWorkload(project="model", submit_carrier=carrier)
    set_runtime(suite, workload, suite.engine)
    suite.add_variable("ECF_TRIES", 2)
    suite.engine.save_suite(suite, output)
    definition = ecflow.Defs(str(output))
    server = {variable.name(): variable.value() for variable in definition.server_variables}
    # Load each native try from a checkpoint. Job-creation checks alone always use try 0.
    checkpoint = tmp_path / "checkpt"
    definition.save_as_checkpt(str(checkpoint))
    initial = checkpoint.read_text()
    home = tmp_path / "operator's forecast jobs"
    for attempt, scheduler in ((1, "slurm"), (2, "donau")):
        checkpoint.write_text(initial.replace("task smoke\n", f"task smoke # try:{attempt}\n"))
        definition.restore_from_checkpt(str(checkpoint))
        parent = definition.find_abs_node("/native_gate")
        parent.add_variable("ECF_HOME", str(home))
        task = definition.find_abs_node("/native_gate/smoke")
        assert task.get_int_try_no() == attempt
        job = home / "native_gate" / f"smoke.job{attempt}"
        if carrier == "orvix" and attempt == 2:
            parent.add_variable("ORVIX_SCHEDULER", scheduler)
            job = home / "reruns" / "smoke.job2"
            task.add_variable("ECF_JOB", str(job))
        task.add_variable("ECF_RID", str(100 + attempt))
        submit = task.find_parent_variable_sub_value("ECF_JOB_CMD")
        kill = task.find_parent_variable_sub_value("ECF_KILL_CMD")
        if carrier == "orvix":
            assert_command_argv(submit, "orvix", "submit", "--scheduler", scheduler, job)
            assert_command_argv(kill, "orvix", "kill", str(job) + ".info.yaml")
        elif carrier == "slsubmit6":
            endpoint = (server["ECF_HOST"], server["ECF_PORT"])
            assert_command_argv(submit, "slsubmit6", job, task.get_abs_node_path(), 2, attempt, *endpoint)
            assert_command_argv(kill, "slcancel4", 100 + attempt, task.get_abs_node_path(), *endpoint)
        else:
            job.parent.mkdir(exist_ok=True, parents=True)
            job.write_text('#!/bin/sh\nprintf "%s\\n" "$0"\n')
            job.chmod(0o700)
            subprocess.run(["/bin/sh", "-ec", submit], check=True, timeout=5)
            assert (job.parent / f"smoke.{attempt}").read_text().splitlines() == [str(job)]
            assert_command_argv(kill, "kill", "-15", 100 + attempt)


def test_native_ecflow_rejects_missing_job_include(tmp_path):
    _, output, scripts, _ = _save_suite(tmp_path)
    (scripts / "smoke.ecf").write_text('#!/bin/sh\n%include <missing.h>\n')
    control = ecflow.JobCreationCtrl()
    control.set_dir_for_job_creation(str(tmp_path / "jobs"))

    ecflow.Defs(str(output)).check_job_creation(control)

    errors = control.get_error_msg()
    assert errors, "the real native preprocessor must reject a missing include"
    assert "missing.h" in errors


@pytest.mark.parametrize("mode", ["inline", "external"])
def test_native_ecflow_executes_business_invocation(tmp_path, mode):
    from takflow.build import build
    from test_build import application, data, put

    source = tmp_path / "resources"
    output = tmp_path / "workflow output"
    script = "scripts/on/model's step.sh"
    argument = "two words ' $(printf expanded) %RUN_TAG%"
    business = """#!/bin/bash -f
set -eu
if (( $# )); then
    [[ $# == 2 && -z $2 ]]
fi
files=(a b)
glob=on
if [[ -o noglob ]]; then glob=off; fi
printf '%s\\n' "$glob | $BUSINESS_INPUT | ${#files[@]} | %RUN_TAG% | ${1:-no-argument}"
cd /
export BUSINESS_INPUT=changed
set -- changed
set +u
trap 'echo business-exit' EXIT
exit "$BUSINESS_STATUS"
"""
    put(source, script, business)
    put(source, "scripts/on/setup.sh", 'export BUSINESS_INPUT="$RUN_TAG"\n')
    put(source, "config/config.sh.j2", "# domain configuration\n")
    plain_call = f"{{{{ invoke_script({script!r}) }}}}"
    literal_call = f"{{{{ invoke_script({script!r}, {argument!r}, '') }}}}"
    put(source, "jobs/on/task.sh.j2", """#!/usr/bin/env bash
%include <head.h>
%include <config.h>
{{ include_raw('scripts/on/setup.sh') }}
set +f
parent_dir=$PWD
parent_options=$-
""" + plain_call + """
echo next-step
set -- owner
""" + literal_call + """
[[ $PWD == "$parent_dir" && $- == "$parent_options" ]]
[[ $BUSINESS_INPUT == "$RUN_TAG" && $# == 1 && $1 == owner ]]
%include <tail.h>
""")

    def suite_builder(config, engine):
        suite = engine.Suite(config.workflow_name)
        suite.add_variables({"ECF_FILES": str(output / "jobs/on"),
                             "ECF_INCLUDE": f"{output}/ecflow/include/common:{output}/config"})
        suite.add_task("task")
        return suite

    app = application(source, suite_builder=suite_builder, use_public_resources=True,
                      variables=lambda config: {"RUN_TAG": "from-definition"})
    with app.prepare(data(output, invoke=mode, machine_name=None)) as context:
        result = build(context)
    jobs = tmp_path / "jobs"
    control = ecflow.JobCreationCtrl()
    control.set_dir_for_job_creation(str(jobs))
    ecflow.Defs(str(result.workflow_output)).check_job_creation(control)
    assert not control.get_error_msg(), control.get_error_msg()
    job, = jobs.rglob("*.job0")
    assert (business in job.read_text()) == (mode == "inline")

    client = put(tmp_path, "bin/ecflow_client", '#!/bin/sh\necho "${1%%=*}"\n', 0o755)
    # Only a separately launched script gets -f from its own shebang.
    glob = "off" if mode == "external" else "on"
    body_output = "from-definition | 2 | %RUN_TAG%"
    first = [f"{glob} | {body_output} | no-argument", "business-exit"]
    second = [f"{glob} | {body_output} | {argument}", "business-exit"]
    for rc in (0, 7):
        env = {**os.environ, "BUSINESS_STATUS": str(rc), "PATH": f"{client.parent}:{os.environ['PATH']}"}
        direct = subprocess.run([output / script], cwd=tmp_path,
                                env={**env, "BUSINESS_INPUT": "from-definition"},
                                capture_output=True, text=True, timeout=10)
        assert direct.returncode == rc, direct.stderr
        assert direct.stdout.splitlines() == [f"off | {body_output} | no-argument", "business-exit"]

        run = subprocess.run(["bash", job], cwd=tmp_path, env=env, capture_output=True,
                             text=True, timeout=10)
        assert run.returncode == rc, run.stderr
        after = ["next-step", *second, "--complete"] if rc == 0 else ["--abort"]
        assert run.stdout.splitlines() == ["--init", *first, *after]


@pytest.mark.parametrize("mode", ["inline", "external"])
def test_native_ksh93_delivers_signals_during_invocation_and_wait(tmp_path, mode):
    from takflow.build import build
    from test_build import application, data, put

    ksh = shutil.which("ksh93")
    if not ksh or not Path("/proc/self/wchan").is_file():
        pytest.skip("requires ksh93 and Linux procfs to signal a job blocked in wait")
    version = subprocess.check_output([ksh, "-c", 'echo "$KSH_VERSION"'], text=True)
    assert " 93" in version, f"expected ksh93, found {version.strip()}"
    source, output = tmp_path / "source", tmp_path / "workflow output"
    put(source, "config/config.sh.j2", "# domain config\n")
    put(source, "scripts/on/model.sh", """#!/bin/sh
if [ "$POSITION" = foreground ]; then hold_step; fi
if [ "$POSITION" = error ]; then exit 7; fi
""")
    put(source, "jobs/on/run.sh.j2", """#!/usr/bin/env ksh93
%include <common/head.h>
%include <config.h>
if [ "$POSITION" = error ]; then hold_step & fi
{{ invoke_script("scripts/on/model.sh") }}
echo after-business
if [ "$POSITION" = tail ]; then hold_step & fi
%include <common/tail.h>
""")

    def suite_builder(config, engine):
        suite = engine.Suite(config.workflow_name)
        suite.add_variables({"ECF_FILES": str(output / "jobs/on"),
                             "ECF_INCLUDE": f"{output}/ecflow/include:{output}/config"})
        suite.add_task("run")
        return suite

    app = application(source, suite_builder=suite_builder, use_public_resources=True)
    with app.prepare(data(output, invoke=mode, machine_name=None)) as ctx:
        definition = build(ctx).workflow_output
    control = ecflow.JobCreationCtrl()
    control.set_dir_for_job_creation(str(tmp_path / "jobs"))
    ecflow.Defs(str(definition)).check_job_creation(control)
    assert not control.get_error_msg(), control.get_error_msg()
    job, = (tmp_path / "jobs").rglob("*.job0")
    client = put(tmp_path, "bin/ecflow_client", '#!/bin/sh\necho "${1%%=*}"\n', 0o755)
    put(tmp_path, "bin/hold_step", """#!/bin/sh
echo holding
while [ ! -f "$RELEASE" ]; do sleep 0.02; done
""", 0o755)
    for position in ("foreground", "tail", "error"):
        log, release = tmp_path / f"{position}.log", tmp_path / f"{position}.release"
        env = {**os.environ, "PATH": f"{client.parent}:{os.environ['PATH']}",
               "POSITION": position, "RELEASE": str(release)}
        with log.open("w") as stream, subprocess.Popen(
            [ksh, job], env=env, stdout=stream, stderr=subprocess.STDOUT,
        ) as process:
            try:
                # For each wait, observe the sleeping parent after it entered the relevant path.
                checkpoint = {"foreground": "holding", "tail": "after-business",
                              "error": "job failed: phase=running status=7"}[position]
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    events = log.read_text().splitlines()
                    assert process.poll() is None, events
                    if checkpoint in events and "holding" in events:
                        kernel_wait = Path(f"/proc/{process.pid}/wchan").read_text()
                        if position == "foreground" or "wait" in kernel_wait or "sigsuspend" in kernel_wait:
                            break
                    time.sleep(0.01)
                else:
                    pytest.fail(f"ksh93 did not reach {position}")
                process.send_signal(signal.SIGTERM)
                release.touch()
                assert process.wait(timeout=10) == (7 if position == "error" else 143)
            finally:
                release.touch()
                if process.poll() is None:
                    process.kill()
        events = log.read_text().splitlines()
        assert [event for event in events if event.startswith("--")] == ["--init", "--abort"]
        assert ("after-business" in events) == (position == "tail")
        reason = "received signal 15" + (" during error handling" if position == "error" else "")
        assert events.count(reason) == 1


def test_native_rebuild_reads_public_head_after_component_override_is_removed(tmp_path):
    from takflow.application import ResourceEntry
    from takflow.build import build
    from test_build import application, data, put

    source = tmp_path / "source"
    output = tmp_path / "out"
    put(source, "config/config.sh.j2", "# config\n")
    put(source, "jobs/on/task.sh.j2", "#!/bin/bash\n%include <head.h>\n:\n%include <tail.h>\n")
    override = put(source, "ecflow/include/data/head.h", "echo component-head\n")

    def suite_builder(config, engine):
        suite = engine.Suite(config.workflow_name)
        includes = output / "ecflow/include"
        suite.add_variables({"ECF_FILES": str(output / "jobs/on"),
                             "ECF_INCLUDE": f"{includes}/data:{includes}/common"})
        suite.add_task("task")
        return suite

    # Both sources map to the path searched by this component's native job.
    app = application(source, suite_builder=suite_builder, use_public_resources=True, resource_entries=(
        ResourceEntry("ecflow/include/common", "ecflow/include/common"),
        ResourceEntry("ecflow/include/common/head.h", "ecflow/include/data/head.h"),
        ResourceEntry("ecflow/include/data", "ecflow/include/data"),
    ))

    def build_and_expand(destination):
        with app.prepare(data(output, machine_name=None)) as context:
            result = build(context)
        control = ecflow.JobCreationCtrl()
        control.set_dir_for_job_creation(str(destination))
        ecflow.Defs(str(result.workflow_output)).check_job_creation(control)
        assert not control.get_error_msg(), control.get_error_msg()
        return next(destination.rglob("*.job0")).read_text()

    first = build_and_expand(tmp_path / "first-jobs")
    assert "echo component-head" in first and "ecflow_client --complete" in first
    assert not (output / "ecflow/include/data/tail.h").exists()
    override.unlink()
    second = build_and_expand(tmp_path / "second-jobs")
    assert "echo component-head" not in second
    assert "ecflow_client --init" in second and "ecflow_client --complete" in second


def test_native_orvix_resource_variables_and_application_default(tmp_path):
    from types import SimpleNamespace

    from jinja2 import Environment

    from takflow.config import SlurmWorkload
    from takflow.jobs.headers import RESOURCE_TEMPLATE_HELPERS

    suite, output, scripts, includes = _save_suite(tmp_path)
    shutil.copytree(Path(__file__).parents[1] / "src/takflow/resources/ecflow/include", includes, dirs_exist_ok=True)
    workload = SlurmWorkload(wckey="project-value")
    set_runtime(suite, workload, suite.engine)
    suite.engine.save_suite(suite, output)
    env = Environment()
    env.globals.update(RESOURCE_TEMPLATE_HELPERS)
    text = env.from_string(
        '#!/bin/sh\n{{ render_orvix_resource_block(job_type="parallel", nodes=2, '
        'ntasks_per_node=4, walltime="6:00:00", application="template-app") }}\n'
    ).render(config=SimpleNamespace(workflow_mode="ecflow", workload=workload))
    (scripts / "smoke.ecf").write_text(text)
    definition = ecflow.Defs(str(output))

    def create_job(name):
        generated = tmp_path / name
        control = ecflow.JobCreationCtrl()
        control.set_dir_for_job_creation(str(generated))
        definition.check_job_creation(control)
        assert not control.get_error_msg(), control.get_error_msg()
        return next(generated.rglob("*.job0")).read_text()

    before = create_job("before")
    assert "#ORVIX queue=serial" in before
    assert "#ORVIX project=project-value" in before
    assert "#ORVIX application=template-app" in before
    assert "#ORVIX nodes=2" in before
    assert "#ORVIX ntasks-per-node=4" in before
    assert "#ORVIX time=6:00:00" in before
    task = definition.find_abs_node("/native_gate/smoke")
    task.add_variable("QUEUE", "custom-queue")
    task.add_variable("WCKEY", "custom-project")
    task.add_variable("APPLICATION", "custom-app")
    task.add_variable("NODES", "3")
    task.add_variable("TASKS_PER_NODE", "8")
    task.add_variable("WALLTIME", "02:00:00")
    after = create_job("after")
    assert "#ORVIX queue=custom-queue" in after
    assert "#ORVIX project=custom-project" in after
    assert "#ORVIX application=custom-app" in after
    assert "#ORVIX nodes=3" in after
    assert "#ORVIX ntasks-per-node=8" in after
    assert "#ORVIX time=02:00:00" in after


def test_native_pipeline_retains_machine_updates_without_regenerating_ecf(tmp_path):
    from takflow.build import build
    from test_build import application, data

    source = tmp_path / "resources"
    for relative, text in {
        "config/config.sh.j2": "# config\n",
        "scripts/on/task.sh": "#!/bin/sh\necho business-marker\n",
        "machine/site/env/runtime.sh": "VALUE=before\n",
        "jobs/on/task.sh.j2": "#!/bin/sh\n%include <config.h>\n{{ include_machine('env/runtime.sh') }}\n",
        "templates/runner.sh.j2": "#!/bin/sh\ntrue\n",
    }.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    app = application(source, variables=lambda config: {"QUOTE_VALUE": "space ' quote $HOME"})
    with app.prepare(data(tmp_path / "out")) as context:
        result = build(context)
    original_ecf = (tmp_path / "out/jobs/on/task.ecf").read_bytes()

    def create_jobs(destination):
        control = ecflow.JobCreationCtrl()
        control.set_dir_for_job_creation(str(destination))
        ecflow.Defs(str(result.workflow_output)).check_job_creation(control)
        assert not control.get_error_msg(), control.get_error_msg()
        return next(destination.rglob("*.job0")).read_text()

    before = create_jobs(tmp_path / "first-jobs")
    (tmp_path / "out/machine/site/env/runtime.sh").write_text("VALUE=after\n")
    after = create_jobs(tmp_path / "second-jobs")
    assert "VALUE=before" in before and "VALUE=after" in after
    assert "export QUOTE_VALUE=" in before
    export = next(line for line in before.splitlines() if line.startswith("export QUOTE_VALUE="))
    assert shlex.split(export) == ["export", "QUOTE_VALUE=space ' quote $HOME"]
    assert (tmp_path / "out/jobs/on/task.ecf").read_bytes() == original_ecf
    # Public validation also works after the standard serializer scope exits.
    check_definition_output(result.generation.suite, result.workflow_output)


@pytest.mark.parametrize("fallback", [None, False, True])
def test_native_shared_resource_header_follows_parent_edits(tmp_path, fallback):
    from takflow.config import SlurmWorkload
    from takflow.jobspec import TaskResource
    from takflow.jobs.headers import render_orvix_resource_block, render_slurm_resource_block

    engine = WorkflowEngine(EcflowBackend())
    suite = engine.Suite("suite")
    includes = Path(__file__).parents[1] / "src/takflow/resources/ecflow/include"
    source = tmp_path / "shared.ecf"
    suite.add_variables({"ECF_HOME": str(tmp_path), "ECF_INCLUDE": str(includes),
                         "ECF_SCRIPT_CMD": "cat " + shlex.quote(str(source))})
    set_runtime(suite, SlurmWorkload(project="model"), engine)
    family = suite.add_family("fcst")
    set_resource_variables(family, TaskResource(
        job_type="parallel", queue="batch", nodes=4, ntasks_per_node=32,
    ))
    set_resource_variables(family.add_task("inherited"), TaskResource(time="00:40:00", memory=None))
    set_resource_variables(family.add_task("fixed"), TaskResource(
        job_type="parallel", queue="batch", nodes=4, memory="8G", requeue=True,
    ))
    path = tmp_path / "suite.def"
    engine.save_suite(suite, path)
    assert "#ORVIX " not in path.read_text() and "#SBATCH " not in path.read_text()
    defs = ecflow.Defs(str(path))
    native_family = defs.find_abs_node("/suite/fcst")
    fields = dict(job_type="parallel", workflow_mode="ecflow", time="06:00:00", requeue=fallback,
                  job_name="trial forecast", output="%ECF_JOBOUT%.%A_%a.%04j.%j%j.out", error="/log path/%%.%j.err")
    original = ("#!/bin/bash\n" + render_orvix_resource_block(**fields) + "\n"
                + render_slurm_resource_block(**fields) + "\ntrue\n")
    source.write_text(original)
    previous = {}
    for attempt, state in enumerate((None, False, True)):
        if state is not None:
            native_family.add_variable("REQUEUE", str(state).lower())
            native_family.add_variable("NODES", str(4 + attempt))
            native_family.add_variable("TASKS_PER_NODE", str(32 + attempt))
            if attempt == 1:
                native_family.add_variable("MEMORY", "9G")
                native_family.add_variable("JOB_NAME", "new forecast")
                log_edits = ecflow_resource_variables({"JOB_OUTPUT": "/parent log/%A_%a.%j.out"})
                assert log_edits == {"JOB_OUTPUT": "/parent log/%%A_%%a.%%j.out"}
                native_family.add_variable(log_edits)
            else:
                native_family.add_variable("MEMORY", "10G")
            native_family.add_variable("WALLTIME", f"0{attempt}:10:00")
            native_family.add_variable("QUEUE", f"batch-{attempt}")
        jobs = tmp_path / f"attempt-{attempt}"
        control = ecflow.JobCreationCtrl()
        control.set_dir_for_job_creation(str(jobs))
        defs.check_job_creation(control)
        assert not control.get_error_msg(), control.get_error_msg()
        paths = sorted(jobs.rglob("*.job0"))
        assert len(paths) == 2
        for job in paths:
            fixed = job.name == "fixed.job0"
            policy = True if fixed else (fallback if state is None else state)
            lines = job.read_text().splitlines()
            assert lines.count("#SBATCH --no-requeue") == int(policy is False)
            assert "#SBATCH --requeue" not in lines
            expect = {
                "queue": "batch" if fixed or not attempt else f"batch-{attempt}",
                "nodes": 4 if fixed else 4 + attempt,
                "ntasks-per-node": 32 + attempt, "memory": "8G" if fixed else (f"{8 + attempt}G" if attempt else None),
                "time": ("06:00:00" if not attempt else f"0{attempt}:10:00") if fixed else "00:40:00",
                "project": "model",
                "requeue": None if policy is None else str(policy).lower(), "application": None,
            }
            for key, value in expect.items():
                assert [line for line in lines if line.startswith(f"#ORVIX {key}=")] == (
                    [] if value is None else [f"#ORVIX {key}={value}"])
            native = [shlex.split(line)[1] for line in lines if line.startswith("#SBATCH ")]
            for key, option in (("nodes", "nodes"), ("ntasks-per-node", "ntasks-per-node"),
                                ("queue", "partition"), ("memory", "mem"), ("time", "time"),
                                ("project", "wckey"), ("application", "comment")):
                actual = [arg for arg in native if arg.startswith(f"--{option}=")]
                assert actual == ([] if expect[key] is None else [f"--{option}={expect[key]}"])
            assert native.count("--job-name=" + ("new forecast" if attempt else "trial forecast")) == 1
            assert native.count("--error=/log path/%%.%j.err") == 1
            native_output, = [arg.removeprefix("--output=") for arg in native if arg.startswith("--output=")]
            if attempt:
                assert native_output == "/parent log/%A_%a.%j.out"
            else:
                assert native_output.endswith(".%A_%a.%04j.%j%j.out")
            assert lines.count(f'#ORVIX output="{native_output}"') == 1
            previous[job] = job.read_bytes()
        assert source.read_text() == original
        assert all(job.read_bytes() == content for job, content in previous.items())

    # Remove only scalars on the loaded definition. The fixed task first
    # inherits its parent's value, then both tasks lose the memory directive.
    defs.find_abs_node("/suite/fcst/fixed").delete_variable("MEMORY")
    native_family.delete_variable("JOB_OUTPUT")
    for label, memory in (("inherited", "10G"), ("removed", None)):
        if memory is None:
            native_family.delete_variable("MEMORY")
        directory = tmp_path / label
        control = ecflow.JobCreationCtrl()
        control.set_dir_for_job_creation(str(directory))
        defs.check_job_creation(control)
        assert not control.get_error_msg(), control.get_error_msg()
        jobs = list(directory.rglob("*.job0"))
        assert len(jobs) == 2
        for job in jobs:
            lines = job.read_text().splitlines()
            for prefix in ("#ORVIX memory=", "#SBATCH --mem="):
                assert [line for line in lines if line.startswith(prefix)] == (
                    [prefix + memory] if memory else [])
            for prefix in ('#ORVIX output="', '#SBATCH --output="'):
                output, = [line for line in lines if line.startswith(prefix)]
                assert output.endswith('.%A_%a.%04j.%j%j.out"') and "/parent log/" not in output

    native_family.add_variable("MEMORY", "%UNDEFINED_LIMIT%")
    control = ecflow.JobCreationCtrl()
    control.set_dir_for_job_creation(str(tmp_path / "invalid"))
    defs.check_job_creation(control)
    assert "UNDEFINED_LIMIT" in control.get_error_msg()


def test_native_ecflow_checks_isolate_commands_includes_and_jobs(tmp_path, resources):
    from test_build import application, data, put
    from test_artifact_checks import snapshot
    from takflow.checks import check_artifacts
    from takflow.build import build
    import shlex
    from takflow.checks._native import expand_ecflow
    from takflow.checks.artifacts import Inventory, _parse

    out = tmp_path / "outputs with space"
    source = out / "jobs/on/task.ecf"
    sentinel = put(tmp_path, "outside/original.job0", "original", 0o640)
    marker = sentinel.parent / "executed"
    def suite(config, engine):
        root = engine.Suite("suite")
        root.add_variables({"ECF_HOME": str(sentinel.parent), "ECF_JOB": str(sentinel), "ECF_INCLUDE": str(out),
                            "ECF_SCRIPT_CMD": "cat " + shlex.quote(str(source)), "SELECTED": "native-value"})
        root.add_task("task")
        return root
    put(resources, "jobs/on/task.sh.j2", '#!/bin/bash\n%include <scripts/on/part.h>\n%nopp\n%include <literal-body>\n%end\ntouch ' + str(marker) + '\n')
    put(resources, "scripts/on/part.h", "echo %SELECTED%\n")
    with application(resources, suite_builder=suite).prepare(data(out)) as ctx:
        result = build(ctx)
    resources.rename(tmp_path / "detached-source")
    inventory = Inventory(result.manifest_path)
    original = snapshot(out)
    before = snapshot(sentinel.parent)
    work = tmp_path / "native"
    work.mkdir()
    job = expand_ecflow(_parse(result.workflow_output, "ecflow"), "/suite/task", inventory, work)
    assert "echo native-value" in job.read_text() and "%include <literal-body>" in job.read_text()
    assert job.is_relative_to(work)
    assert check_artifacts(manifest=result.manifest_path, parse=True, expand=["/suite/task"]).passed
    assert snapshot(out) == original and snapshot(sentinel.parent) == before

    definition = result.workflow_output.read_text()
    cmd = next(line for line in definition.splitlines() if "edit ECF_SCRIPT_CMD" in line)
    result.workflow_output.write_text(definition.replace(cmd, "  edit ECF_SCRIPT_CMD 'touch " + str(marker) + "'"))
    before_out = snapshot(out)
    assert check_artifacts(manifest=result.manifest_path, parse=True).passed
    checked = check_artifacts(manifest=result.manifest_path, expand=["/suite/task"])
    assert checked.checks[0]["status"] == "incomplete" and "ECF_SCRIPT_CMD" in checked.checks[0]["reason"]
    assert before_out == snapshot(out) and before == snapshot(sentinel.parent)
    result.workflow_output.write_text(definition)
    put(out, "old.h", "old output")
    for content, status in [("%include <old.h>\n", "incomplete"),
                            ("%includenopp <" + str(sentinel) + ">\n", "incomplete"),
                            ("%MISSING_NATIVE_VALUE%\n", "failed")]:
        source.write_text(content)
        before_out = snapshot(out)
        checked = check_artifacts(manifest=result.manifest_path, expand=["/suite/task"])
        assert checked.checks[0]["status"] == status
        if status == "failed":
            assert "could not substitute a job variable" in checked.checks[0]["reason"]
            assert str(source) in checked.checks[0]["reason"] and "MISSING_NATIVE_VALUE" not in repr(checked)
        assert before_out == snapshot(out) and before == snapshot(sentinel.parent)
    result.workflow_output.write_text("suite example\nprivate_definition_text\nendsuite\n")
    checked = check_artifacts(manifest=result.manifest_path, parse=True).checks[0]
    assert checked["status"] == "failed" and checked["object"] == str(result.workflow_output)
    assert "line 2" in checked["reason"] and "private_definition_text" not in repr(checked)
