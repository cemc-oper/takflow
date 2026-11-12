"""Preflight actual job dependencies without executing workflow business logic."""
from __future__ import annotations

import hashlib
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
import pytest

from takflow.checks import GenerationCheckError, GenerationCheckReport
from takflow.config import BaseWorkflowConfig
from takflow.toolkit.job import render_jobs_from_directory, render_single_job_file


def config(**updates):
    return BaseWorkflowConfig(project_base_dir="/program", run_base_dir="/run",
                              workload={"workload_type": "shell"}, **updates)


def jobs(root, templates):
    for name, text in templates.items():
        path = root / "jobs" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def render(root, output, *, settings=None, report=None, **kwargs):
    return render_jobs_from_directory(settings or config(), root, str(output),
                                      check_report=report, **kwargs)


def test_static_include_failure_does_not_replace_any_selected_job(tmp_path):
    root = jobs(tmp_path / "repo", {"first.sh.j2": "new first", "last.sh.j2": '{% include "missing.j2" %}'})
    output = tmp_path / "out"
    (output / "jobs").mkdir(parents=True)
    first = output / "jobs/first.sh"
    first.write_text("previous first")
    first.chmod(0o750)
    with pytest.raises(GenerationCheckError) as caught:
        render(root, output)
    assert caught.value.diagnostic.code == "GEN_TEMPLATE_MISSING"
    assert caught.value.diagnostic.stage == "job.preflight"
    assert caught.value.diagnostic.object == "jobs/last.sh.j2"
    assert caught.value.report.artifacts == []
    assert first.read_text() == "previous first"
    assert first.stat().st_mode & 0o777 == 0o750
    assert not (output / "jobs/last.sh").exists()


@pytest.mark.parametrize("helper", ["include_raw", "invoke_script"])
@pytest.mark.parametrize("mode", ["inline", "external"])
def test_literal_script_reference_is_checked_before_any_job_write(tmp_path, helper, mode):
    root = jobs(tmp_path / "repo", {"first.sh.j2": "echo first", "last.sh.j2": f'{{{{ {helper}("scripts/missing.sh") }}}}'})
    output = tmp_path / "out"
    with pytest.raises(GenerationCheckError) as caught:
        render(root, output, settings=config(script_invoke_mode=mode))
    assert caught.value.diagnostic.code == "GEN_INPUT_MISSING"
    assert caught.value.diagnostic.stage == "job.preflight"
    assert caught.value.diagnostic.object.endswith("scripts/missing.sh")
    assert not output.exists()


def test_external_script_requires_execute_permission_but_inline_only_reads(tmp_path):
    root = jobs(tmp_path / "repo", {"task.sh.j2": '{{ invoke_script("scripts/task.sh") }}'})
    output = tmp_path / "out"
    (output / "scripts").mkdir(parents=True)
    script = output / "scripts/task.sh"
    script.write_text("echo business")
    script.chmod(0o644)
    with pytest.raises(GenerationCheckError) as caught:
        render(root, output, settings=config(script_invoke_mode="external"))
    assert caught.value.diagnostic.code == "GEN_INPUT_NOT_EXECUTABLE"
    assert caught.value.diagnostic.stage == "job.preflight"
    assert not (output / "jobs").exists()
    assert render(root, output, settings=config(script_invoke_mode="inline")) is None
    assert (output / "jobs/task.sh").read_text() == "echo business"


@pytest.mark.parametrize("reference", ["../outside.sh", "/outside.sh", "../${DYNAMIC_SCRIPT}"])
def test_script_reference_must_be_relative_and_contained(tmp_path, reference):
    root = jobs(tmp_path / "repo", {"task.sh.j2": "{{ include_raw(" + repr(reference) + ") }}"})
    with pytest.raises(GenerationCheckError) as caught:
        render(root, tmp_path / "out")
    assert caught.value.diagnostic.code == "GEN_PATH_INVALID"
    assert caught.value.diagnostic.stage == "job.preflight"


def test_symlinked_script_cannot_escape_output_root(tmp_path):
    root = jobs(tmp_path / "repo", {"task.sh.j2": '{{ include_raw("scripts/task.sh") }}'})
    output = tmp_path / "out"
    (output / "scripts").mkdir(parents=True)
    outside = tmp_path / "outside.sh"
    outside.write_text("echo outside")
    (output / "scripts/task.sh").symlink_to(outside)
    with pytest.raises(GenerationCheckError) as caught:
        render(root, output)
    assert caught.value.diagnostic.code == "GEN_PATH_ESCAPE"
    assert not (output / "jobs").exists()


@pytest.mark.parametrize("job_output_dir", ["../escape", "/escape"])
def test_job_output_mapping_cannot_escape_root(tmp_path, job_output_dir):
    root = jobs(tmp_path / "repo", {"task.sh.j2": "echo ok"})
    with pytest.raises(GenerationCheckError) as caught:
        render(root, tmp_path / "out", job_output_dir=job_output_dir)
    assert caught.value.diagnostic.code == "GEN_PATH_INVALID"


def test_output_symlink_does_not_overwrite_outside_file(tmp_path):
    root = jobs(tmp_path / "repo", {"task.sh.j2": "echo new"})
    output = tmp_path / "out"
    output.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    original = outside / "task.sh"
    original.write_text("old")
    (output / "jobs").symlink_to(outside, target_is_directory=True)
    with pytest.raises(GenerationCheckError) as caught:
        render(root, output)
    assert caught.value.diagnostic.code == "GEN_PATH_ESCAPE"
    assert original.read_text() == "old"


@pytest.mark.parametrize("layered", [False, True])
def test_different_template_names_cannot_map_to_one_job(tmp_path, layered):
    base = jobs(tmp_path / "base", {"task.sh.j2": "echo base"})
    other = jobs(tmp_path / "oper" if layered else base, {"task.j2": "echo collision"})
    with pytest.raises(GenerationCheckError) as caught:
        render([base, other] if layered else base, tmp_path / "out")
    assert caught.value.diagnostic.code == "GEN_JOB_NAME_COLLISION"
    assert caught.value.diagnostic.stage == "job.preflight"
    assert not (tmp_path / "out").exists()


def test_planned_file_and_directory_outputs_cannot_collide(tmp_path):
    root = jobs(tmp_path / "repo", {"task.j2": "echo task", "task.sh/child.j2": "echo child"})
    with pytest.raises(GenerationCheckError) as caught:
        render(root, tmp_path / "out")
    assert caught.value.diagnostic.code == "GEN_JOB_NAME_COLLISION"


def test_same_template_overlay_keeps_only_final_artifact_record(tmp_path):
    base = jobs(tmp_path / "base", {"task.sh.j2": "echo base"})
    oper = jobs(tmp_path / "oper", {"task.sh.j2": "echo oper"})
    report = GenerationCheckReport()
    assert render([base, oper], tmp_path / "out", report=report) is None
    result = tmp_path / "out/jobs/task.sh"
    assert result.read_text() == "echo oper"
    assert len(report.artifacts) == 1
    assert report.artifacts[0]["sha256"] == hashlib.sha256(result.read_bytes()).hexdigest()
    assert report.artifacts[0]["role"] == "job"
    assert report.artifacts[0]["mode"] == "0o755"


def test_sparse_layers_use_original_loader_index_and_fallback_order(tmp_path):
    sparse = tmp_path / "sparse"
    (sparse / "templates").mkdir(parents=True)
    (sparse / "templates/shared.j2").write_text("old sparse")
    base = jobs(tmp_path / "base", {"task.sh.j2": '{% include "templates/shared.j2" %}'})
    (base / "templates").mkdir()
    (base / "templates/shared.j2").write_text("base current")
    oper = jobs(tmp_path / "oper", {"oper.sh.j2": '{% include "templates/shared.j2" %}'})
    render([sparse, base, oper], tmp_path / "out")
    assert (tmp_path / "out/jobs/task.sh").read_text() == "base current"
    assert (tmp_path / "out/jobs/oper.sh").read_text() == "base current"


def test_disabled_template_is_neither_read_nor_checked(tmp_path, monkeypatch):
    root = jobs(tmp_path / "repo", {"active.sh.j2": "echo active", "disabled.sh.j2": '{{ include_raw("missing.sh") }} {% if %}'})
    original = FileSystemLoader.get_source
    def get_source(loader, environment, template):
        assert "disabled" not in template
        return original(loader, environment, template)
    monkeypatch.setattr(FileSystemLoader, "get_source", get_source)
    render(root, tmp_path / "out", template_filter=lambda path: path.name != "disabled.sh.j2")
    assert not (tmp_path / "out/jobs/disabled.sh").exists()


def test_recursive_static_dependencies_check_script_references(tmp_path):
    root = jobs(tmp_path / "repo", {"task.sh.j2": '{% include "templates/inner.j2" %}'})
    (root / "templates").mkdir()
    (root / "templates/inner.j2").write_text('{{ include_raw("scripts/missing.sh") }}')
    with pytest.raises(GenerationCheckError) as caught:
        render(root, tmp_path / "out")
    assert caught.value.diagnostic.code == "GEN_INPUT_MISSING"
    assert caught.value.diagnostic.stage == "job.preflight"


def test_template_source_symlink_cannot_escape_resource_root(tmp_path):
    root = tmp_path / "repo"
    (root / "jobs").mkdir(parents=True)
    outside = tmp_path / "outside.j2"
    outside.write_text("echo outside")
    (root / "jobs/task.sh.j2").symlink_to(outside)
    with pytest.raises(GenerationCheckError) as caught:
        render(root, tmp_path / "out")
    assert caught.value.diagnostic.code == "GEN_PATH_ESCAPE"
    assert not (tmp_path / "out").exists()


def test_static_include_cannot_traverse_above_resource_root(tmp_path):
    root = jobs(tmp_path / "repo", {"task.sh.j2": '{% include "../outside.j2" %}'})
    with pytest.raises(GenerationCheckError) as caught:
        render(root, tmp_path / "out")
    assert caught.value.diagnostic.code == "GEN_PATH_ESCAPE"
    assert caught.value.diagnostic.stage == "job.preflight"


def test_jinja_candidate_list_and_optional_include_keep_native_semantics(tmp_path):
    root = jobs(tmp_path / "repo", {"task.sh.j2": '{% include ["absent.j2", "templates/ok.j2"] %}\n{% include "optional.j2" ignore missing %}'})
    (root / "templates").mkdir()
    (root / "templates/ok.j2").write_text("echo selected")
    report = GenerationCheckReport()
    render(root, tmp_path / "out", report=report)
    assert (tmp_path / "out/jobs/task.sh").read_text().strip() == "echo selected"
    assert any(item.code == "GEN_TEMPLATE_OPTIONAL" and item.status == "unchecked" for item in report.checks)


def test_dynamic_include_and_runtime_script_are_explicitly_unchecked(tmp_path):
    root = jobs(tmp_path / "repo", {"task.sh.j2": '{% include config.workflow_name %}\n{{ invoke_script("${REMOTE_SCRIPTS}/run.sh") }}'})
    (root / "templates").mkdir()
    (root / "templates/ok.j2").write_text("echo selected")
    report = GenerationCheckReport()
    render(root, tmp_path / "out", settings=config(workflow_name="templates/ok.j2"), report=report)
    unchecked = {item.code for item in report.checks if item.status == "unchecked"}
    assert {"GEN_TEMPLATE_DYNAMIC", "GEN_SCRIPT_DYNAMIC"} <= unchecked
    assert "${REMOTE_SCRIPTS}" in (tmp_path / "out/jobs/task.sh").read_text()


def test_remote_reference_is_not_probed_or_copied_into_diagnostics(tmp_path):
    secret = "synthetic-remote-credential"
    reference = f"https://user:{secret}@example.invalid/job.sh"
    root = jobs(tmp_path / "repo", {"task.sh.j2": "{{ invoke_script(" + repr(reference) + ") }}"})
    report = GenerationCheckReport()
    render(root, tmp_path / "out", report=report)
    assert any(item.code == "GEN_SCRIPT_DYNAMIC" and item.status == "unchecked" for item in report.checks)
    assert secret not in repr(report.as_dict())


def test_late_dynamic_render_failure_retains_earlier_outputs_and_report(tmp_path):
    first = jobs(tmp_path / "first", {"first.sh.j2": "echo first"})
    last = jobs(tmp_path / "last", {"last.sh.j2": '{% include config.workflow_name %}'})
    output = tmp_path / "out"
    with pytest.raises(GenerationCheckError) as caught:
        render([first, last], output, settings=config(workflow_name="missing-dynamic.j2"))
    assert caught.value.diagnostic.code == "GEN_JOB_RENDER"
    assert caught.value.diagnostic.stage == "job.render"
    assert (output / "jobs/first.sh").read_text() == "echo first"
    assert len(caught.value.report.artifacts) == 1
    assert not (output / "jobs/last.sh").exists()


def test_single_job_preflight_checks_output_and_missing_static_template(tmp_path):
    report = GenerationCheckReport()
    with pytest.raises(GenerationCheckError) as caught:
        render_single_job_file(Path("missing.j2"), str(tmp_path / "out"), Path("job.sh"),
                               config(), Environment(loader=FileSystemLoader(tmp_path)),
                               check_report=report)
    assert caught.value.diagnostic.code == "GEN_TEMPLATE_MISSING"
    assert caught.value.report is report
    assert not (tmp_path / "out").exists()


def test_post_generation_shell_syntax_failure_records_stage_without_execution(tmp_path):
    marker = tmp_path / "business-was-executed"
    root = jobs(tmp_path / "repo", {"task.sh.j2": f'#!/bin/bash\ntouch "{marker}"\nif then\n'})
    with pytest.raises(GenerationCheckError) as caught:
        render(root, tmp_path / "out")
    assert caught.value.diagnostic.code == "GEN_SCRIPT_SYNTAX"
    assert caught.value.diagnostic.stage == "job.output"
    assert (tmp_path / "out/jobs/task.sh").exists()
    assert not marker.exists()


@pytest.mark.parametrize("guard", [
    '{% if false %}BODY{% endif %}',
    '{% for item in [] %}BODY{% endfor %}',
    '{% macro unused() %}BODY{% endmacro %}',
])
def test_unexecuted_control_flow_does_not_read_or_require_its_references(tmp_path, monkeypatch, guard):
    body = '{{ include_raw("scripts/unreadable.sh") }}{% include "missing.j2" %}'
    root = jobs(tmp_path / "repo", {"task.sh.j2": guard.replace("BODY", body) + "\necho safe"})
    output = tmp_path / "out"
    (output / "scripts").mkdir(parents=True)
    unreadable = output / "scripts/unreadable.sh"
    unreadable.write_text("not read")
    unreadable.chmod(0o000)
    original = FileSystemLoader.get_source
    def get_source(loader, environment, template):
        assert template != "missing.j2"
        return original(loader, environment, template)
    monkeypatch.setattr(FileSystemLoader, "get_source", get_source)
    report = GenerationCheckReport()
    render(root, output, report=report)
    assert (output / "jobs/task.sh").read_text().strip() == "echo safe"
    assert any(item.code == "GEN_SCRIPT_CONDITIONAL" and item.status == "unchecked" for item in report.checks)
    assert any(item.code == "GEN_TEMPLATE_CONDITIONAL" and item.status == "unchecked" for item in report.checks)


def test_overridden_parent_block_does_not_require_unused_include(tmp_path):
    root = jobs(tmp_path / "repo", {"task.sh.j2": '{% extends "templates/base.j2" %}{% block body %}echo selected{% endblock %}'})
    (root / "templates").mkdir()
    (root / "templates/base.j2").write_text('{% block body %}{% include "missing.j2" %}{% endblock %}')
    render(root, tmp_path / "out")
    assert (tmp_path / "out/jobs/task.sh").read_text() == "echo selected"


@pytest.mark.parametrize("reference,code", [
    ('{{ include_raw("scripts/missing.sh") }}', "GEN_INPUT_MISSING"),
    ('{% include "missing.j2" %}', "GEN_JOB_RENDER"),
])
def test_executed_guarded_reference_fails_at_render_and_retains_earlier_jobs(tmp_path, reference, code):
    first = jobs(tmp_path / "first", {"first.sh.j2": "echo first"})
    last = jobs(tmp_path / "last", {"last.sh.j2": "{% if true %}" + reference + "{% endif %}"})
    output = tmp_path / "out"
    with pytest.raises(GenerationCheckError) as caught:
        render([first, last], output)
    assert caught.value.diagnostic.code == code
    assert caught.value.diagnostic.stage == "job.render"
    assert (output / "jobs/first.sh").read_text() == "echo first"
    assert len(caught.value.report.artifacts) == 1
    assert not (output / "jobs/last.sh").exists()


@pytest.mark.parametrize("hardlink", [False, True])
def test_single_job_cannot_overwrite_its_source_or_hardlink_alias(tmp_path, hardlink):
    root = jobs(tmp_path / "repo", {"self.sh.j2": "echo original template"})
    source = root / "jobs/self.sh.j2"
    output = root / "alias.sh" if hardlink else source
    if hardlink:
        output.hardlink_to(source)
    with pytest.raises(GenerationCheckError) as caught:
        render_single_job_file(Path("jobs/self.sh.j2"), str(root), output.relative_to(root),
                               config(), Environment(loader=FileSystemLoader(root)))
    assert caught.value.diagnostic.code == "GEN_INPUT_OUTPUT_OVERLAP"
    assert caught.value.diagnostic.stage == "job.preflight"
    assert source.read_text() == "echo original template"
    assert source.stat().st_mode & 0o777 == 0o644
    assert caught.value.report.artifacts == []


def test_directory_jobs_cannot_replace_a_script_input(tmp_path):
    root = jobs(tmp_path / "repo", {"task.sh.j2": '{{ include_raw("scripts/task.sh") }}'})
    output = tmp_path / "out"
    (output / "scripts").mkdir(parents=True)
    source = output / "scripts/task.sh"
    source.write_text("echo original script")
    with pytest.raises(GenerationCheckError) as caught:
        render(root, output, job_output_dir="scripts")
    assert caught.value.diagnostic.code == "GEN_INPUT_OUTPUT_OVERLAP"
    assert source.read_text() == "echo original script"


def test_directory_jobs_cannot_overwrite_a_future_loader_template_via_hardlink(tmp_path):
    root = jobs(tmp_path / "repo", {"first.sh.j2": "echo first", "future.sh.j2": "echo future"})
    future = root / "jobs/future.sh.j2"
    (root / "jobs/first.sh").hardlink_to(future)
    with pytest.raises(GenerationCheckError) as caught:
        render(root, root)
    assert caught.value.diagnostic.code == "GEN_INPUT_OUTPUT_OVERLAP"
    assert future.read_text() == "echo future"
    assert not (root / "jobs/future.sh").exists()


def test_false_include_branch_does_not_read_an_escaping_template_symlink(tmp_path, monkeypatch):
    root = jobs(tmp_path / "repo", {"task.sh.j2": '{% if false %}{% include "templates/foreign.j2" %}{% endif %}\necho safe'})
    (root / "templates").mkdir()
    outside = tmp_path / "outside.j2"
    outside.write_text("echo outside")
    (root / "templates/foreign.j2").symlink_to(outside)
    original = FileSystemLoader.get_source
    def get_source(loader, environment, template):
        assert template != "templates/foreign.j2"
        return original(loader, environment, template)
    monkeypatch.setattr(FileSystemLoader, "get_source", get_source)
    render(root, tmp_path / "out")
    assert (tmp_path / "out/jobs/task.sh").read_text().strip() == "echo safe"


@pytest.mark.parametrize("body", [
    '{% if true %}{% include "templates/foreign.j2" %}{% endif %}',
    '{% include config.workflow_name %}',
])
def test_actual_conditional_or_dynamic_include_refuses_escaping_symlink_before_read(tmp_path, monkeypatch, body):
    root = jobs(tmp_path / "repo", {"task.sh.j2": body})
    (root / "templates").mkdir()
    outside = tmp_path / "outside.j2"
    outside.write_text("echo outside")
    (root / "templates/foreign.j2").symlink_to(outside)
    original = FileSystemLoader.get_source
    def get_source(loader, environment, template):
        assert template != "templates/foreign.j2", "escaping source was passed to the unguarded file reader"
        return original(loader, environment, template)
    monkeypatch.setattr(FileSystemLoader, "get_source", get_source)
    with pytest.raises(GenerationCheckError) as caught:
        render(root, tmp_path / "out", settings=config(workflow_name="templates/foreign.j2"))
    assert caught.value.diagnostic.code == "GEN_PATH_ESCAPE"
    assert caught.value.diagnostic.stage == "job.render"
    assert not (tmp_path / "out/jobs/task.sh").exists()
