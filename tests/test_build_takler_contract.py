"""Standard pipeline against the real optional takler definition contract."""
import json
import pytest

pytest.importorskip("takler")

from test_build import application, data, resources
from takflow.build import build
from takflow.checks import check_artifacts


def test_takler_pipeline_uses_real_native_json(tmp_path, resources):
    with application(resources).prepare(data(tmp_path / "out", "takler")) as context:
        result = build(context)
    assert result.complete
    definition = json.loads(result.workflow_output.read_text())
    assert definition["root"]["name"] == "test_workflow"
    assert not result.diagnostics
    assert check_artifacts(manifest=result.manifest_path, parse=True).passed


def test_native_takler_checks_isolate_explicit_job_paths_and_include_lookup(tmp_path, resources):
    from test_build import put
    from test_artifact_checks import snapshot
    from takflow.checks._native import expand_takler
    from takflow.checks.artifacts import Inventory
    from takler.serialization.builder import build_definition

    out = tmp_path / "output"
    home = tmp_path / "original home"
    sentinel = put(home, "outside.job", "original", 0o600)
    # This valid attempt-specific override resolves to the same existing file for every UUID.
    declared = home / "{attempt_id}" / ".." / sentinel.name
    before = snapshot(home)
    task_path = "/suite/task"

    def suite(config, engine):
        root = engine.Suite("suite")
        root.add_variables({"TAKLER_HOME": str(home), "TAKLER_INCLUDE": str(out), "PART": "scripts/on/part.h",
                            "TAKLER_JOB": str(declared), "VALUE": "selected"})
        task = root.add_task("task")
        task.add_variable("TAKLER_SCRIPT", str(out / "jobs/on/task.sh"))
        return root
    put(resources, "jobs/on/task.sh.j2", "{% raw %}#!/bin/sh\n{% include PART %}\n{% endraw %}")
    put(resources, "scripts/on/part.h", "echo {{ VALUE }}\ntouch " + str(home / "executed") + "\n")
    with application(resources, suite_builder=suite).prepare(data(out, mode="takler")) as ctx:
        result = build(ctx)
    resources.rename(tmp_path / "detached-source")
    original = snapshot(out)
    original_flow = build_definition(result.workflow_output.read_bytes())
    original_flow.begin()
    original_task = original_flow.find_node(task_path)
    original_task.increment_try_no()
    assert original_task._artifact_paths()[0] == sentinel
    work = tmp_path / "native"
    work.mkdir()
    job = expand_takler(result.workflow_output, task_path, Inventory(result.manifest_path), work)
    assert job.is_relative_to(work) and job.stat().st_mode & 0o100
    assert "echo selected" in job.read_text() and snapshot(home) == before
    assert check_artifacts(manifest=result.manifest_path, parse=True, expand=[task_path]).passed
    assert original == snapshot(out)
    template = out / "jobs/on/task.sh"
    for body, status in [('{% include "old.h" %}', "incomplete"), ("{% if %}", "failed")]:
        put(out, "old.h", "unregistered file")
        template.write_text(body)
        prior = snapshot(out)
        checked = check_artifacts(manifest=result.manifest_path, expand=[task_path])
        assert checked.checks[0]["status"] == status
        if status == "failed":
            assert f"{template} at line 1" in checked.checks[0]["reason"]
        assert prior == snapshot(out) and snapshot(home) == before
    definition = result.workflow_output.read_text()
    result.workflow_output.write_text(definition.replace(str(declared), str(sentinel)))
    assert check_artifacts(manifest=result.manifest_path, parse=True).passed
    checked = check_artifacts(manifest=result.manifest_path, expand=[task_path])
    assert checked.checks[0]["status"] == "incomplete" and "TAKLER_JOB" in checked.checks[0]["reason"]
    assert snapshot(home) == before
    result.workflow_output.write_text('{"private_definition_text": "private-value"}')
    checked = check_artifacts(manifest=result.manifest_path, parse=True).checks[0]
    assert checked["status"] == "failed" and checked["object"] == str(result.workflow_output)
    assert "invalid_field at $." in checked["reason"] and "private" not in checked["reason"]
