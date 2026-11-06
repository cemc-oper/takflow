"""Real ecFlow parsing and job preprocessing, separate from serializer checks.

The dedicated native contract gate must provide ecFlow and reject all skips.
Ordinary source tests may run without this optional system dependency.
"""
from pathlib import Path

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
