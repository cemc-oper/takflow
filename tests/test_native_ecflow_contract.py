"""Real ecFlow parsing and job preprocessing, separate from serializer checks.

The dedicated native contract gate must provide ecFlow and reject all skips.
Ordinary source tests may run without this optional system dependency.
"""
from pathlib import Path
import shlex

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
