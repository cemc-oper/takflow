"""Native ecFlow parsing, job preprocessing and local execution of a Bash fixture.

The dedicated native contract gate must provide ecFlow and reject all skips.
Ordinary source tests may run without this optional system dependency.
"""
import os
from pathlib import Path
import shlex
import subprocess

import pytest

from takflow.backends.ecflow import EcflowBackend
from takflow.checks import GenerationCheckReport, check_definition_output
from takflow.flow import WorkflowEngine


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

    from takflow.backends.runtime import set_runtime
    from takflow.config import SlurmWorkload
    from takflow.toolkit.job import _render_workflow_orvix_resource_block

    suite, output, scripts, _ = _save_suite(tmp_path)
    workload = SlurmWorkload(wckey="project-value")
    set_runtime(suite, workload, suite.engine)
    suite.engine.save_suite(suite, output)
    env = Environment()
    env.globals["render_orvix_resource_block"] = _render_workflow_orvix_resource_block
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
