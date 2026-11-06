"""Public generation checks: concrete evidence and explicit native boundaries."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import pytest

from takflow.backends.ecflow import EcflowBackend
from takflow.backends.takler import TaklerBackend
from takflow.checks import (
    GenerationCheckError,
    GenerationCheckReport,
    check_input_file,
    check_output_path,
    check_relative_path,
    check_shell_output,
    check_workflow_structure,
    preflight_generation,
)
from takflow.config import BaseWorkflowConfig
from takflow.flow import WorkflowEngine
from takflow.generation import generate_workflow


takler_required = pytest.mark.skipif(importlib.util.find_spec("takler") is None,
                                    reason="real takler dependency is not installed")


def config(tmp_path, mode="ecflow", **updates):
    return BaseWorkflowConfig(project_base_dir="/program", run_base_dir="/run",
                              output_repo_base_dir=str(tmp_path / "out"),
                              workflow_name="demo", workflow_mode=mode,
                              workload={"workload_type": "shell"}, **updates)


def build_suite(settings, engine):
    suite = engine.Suite(settings.workflow_name)
    suite.add_task("run")
    return suite


def has_check(report, code, status):
    return any(item.code == code and item.status == status for item in report.checks)


def assert_failure(error, code, stage):
    assert error.diagnostic.code == code
    assert error.diagnostic.stage == stage
    assert has_check(error.report, code, "failed")


@pytest.mark.parametrize("mode", ["ecflow", "takler", "shell"])
@pytest.mark.parametrize("workload", [
    {"workload_type": "shell", "submit_carrier": "direct"},
    {"workload_type": "shell", "submit_carrier": "orvix"},
    {"workload_type": "slurm", "wckey": "project", "submit_carrier": "orvix", "scheduler": "slurm"},
    {"workload_type": "slurm", "wckey": "project", "submit_carrier": "orvix", "scheduler": "donau"},
    {"workload_type": "slurm", "wckey": "project", "submit_carrier": "slsubmit6", "scheduler": "slurm"},
])
def test_preflight_accepts_declared_combinations_without_claiming_runtime(tmp_path, mode, workload):
    settings = config(tmp_path, mode)
    settings = settings.model_copy(update={"workload": BaseWorkflowConfig(
        project_base_dir="/program", run_base_dir="/run", workload=workload,
    ).workload})
    report = GenerationCheckReport()
    assert preflight_generation(settings, check_report=report) is report
    assert has_check(report, "GEN_CAPABILITIES_VALID", "passed")
    assert has_check(report, "GEN_RUNTIME_UNCHECKED", "unchecked")
    assert report.artifacts == []
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("field,value,code", [
    ("workflow_mode", "unknown", "GEN_MODE_UNSUPPORTED"),
    ("script_invoke_mode", "source", "GEN_SCRIPT_MODE_UNSUPPORTED"),
    ("workload.workload_type", "pbs", "GEN_WORKLOAD_UNSUPPORTED"),
    ("workload.submit_carrier", "slsubmit6", "GEN_CARRIER_UNSUPPORTED"),
])
def test_mutated_unsupported_configuration_fails_before_builder_or_output(tmp_path, field, value, code):
    settings = config(tmp_path)
    target, name = (settings.workload, field.split(".")[1]) if "." in field else (settings, field)
    setattr(target, name, value)
    called = []
    with pytest.raises(GenerationCheckError) as caught:
        generate_workflow(settings, suite_builder=lambda *args: called.append(True))
    assert_failure(caught.value, code, "generation.preflight")
    assert not called
    assert not (tmp_path / "out").exists()


def test_slsubmit6_donau_combination_is_explicitly_rejected(tmp_path):
    settings = config(tmp_path)
    settings.workload = BaseWorkflowConfig(project_base_dir="/program", run_base_dir="/run",
        workload={"workload_type": "slurm", "wckey": "project", "scheduler": "donau", "submit_carrier": "slsubmit6"}).workload
    with pytest.raises(GenerationCheckError) as caught:
        preflight_generation(settings)
    assert_failure(caught.value, "GEN_COMBINATION_UNSUPPORTED", "generation.preflight")


def test_consumer_can_narrow_supported_modes_without_inheriting_shell_support(tmp_path):
    with pytest.raises(GenerationCheckError) as caught:
        preflight_generation(config(tmp_path, "shell"), supported_modes=("ecflow",))
    assert_failure(caught.value, "GEN_MODE_UNSUPPORTED", "generation.preflight")


@pytest.mark.parametrize("operation", sorted(TaklerBackend.unsupported_operations))
def test_required_operations_respect_backend_capability_contract(tmp_path, operation):
    with pytest.raises(GenerationCheckError) as caught:
        preflight_generation(config(tmp_path, "takler"), required_operations=(operation,))
    assert_failure(caught.value, "GEN_OPERATION_UNSUPPORTED", "generation.preflight")
    assert caught.value.diagnostic.object == operation
    ecflow_report = preflight_generation(config(tmp_path), required_operations=(operation,))
    assert has_check(ecflow_report, "GEN_CAPABILITIES_VALID", "passed")


@pytest.mark.parametrize("mode,operation,code", [
    ("ecflow", "not_a_backend_operation", "GEN_OPERATION_UNKNOWN"),
    ("shell", "add_trigger", "GEN_OPERATION_UNSUPPORTED"),
])
def test_unknown_operation_and_shell_backend_operations_are_not_silently_accepted(tmp_path, mode, operation, code):
    with pytest.raises(GenerationCheckError) as caught:
        preflight_generation(config(tmp_path, mode), required_operations=(operation,))
    assert_failure(caught.value, code, "generation.preflight")


@pytest.mark.parametrize("name", ["", ".", "..", "bad/name", "bad\\name", "two words", "line\nbreak", "nul\x00name"])
def test_invalid_node_names_fail_before_definition_replaces_existing_file(tmp_path, name):
    output = tmp_path / "out/demo.def"
    output.parent.mkdir()
    output.write_text("previous definition")
    output.chmod(0o640)
    manifest = output.parent / "generation_manifest.json"
    manifest.write_text("previous unrelated manifest")
    def builder(settings, engine):
        suite = engine.Suite("demo")
        suite.add_task(name)
        return suite
    with pytest.raises(GenerationCheckError) as caught:
        generate_workflow(config(tmp_path), suite_builder=builder)
    assert_failure(caught.value, "GEN_NODE_NAME_INVALID", "definition.preflight")
    assert output.read_text() == "previous definition"
    assert output.stat().st_mode & 0o777 == 0o640
    assert manifest.read_text() == "previous unrelated manifest"
    assert caught.value.report.artifacts == []


@pytest.mark.parametrize("violation,code", [
    ("duplicate", "GEN_NODE_DUPLICATE"),
    ("parent", "GEN_TREE_INVALID"),
    ("foreign_child_engine", "GEN_TREE_INVALID"),
    ("foreign_suite_engine", "GEN_TREE_INVALID"),
])
def test_public_tree_relationships_are_checked_before_save(tmp_path, violation, code):
    def builder(settings, engine):
        if violation == "foreign_suite_engine":
            return WorkflowEngine(EcflowBackend()).Suite("demo")
        suite = engine.Suite("demo")
        if violation == "duplicate":
            suite.add_task("same")
            suite.add_task("same")
        elif violation == "parent":
            child = suite.add_task("run")
            engine.Family("other").add_task(child)
        else:
            suite.add_task(WorkflowEngine(EcflowBackend()).Task("foreign"))
        return suite
    with pytest.raises(GenerationCheckError) as caught:
        generate_workflow(config(tmp_path), suite_builder=builder)
    assert_failure(caught.value, code, "definition.preflight")
    assert not (tmp_path / "out/demo.def").exists()


def test_valid_public_tree_with_trigger_cycle_is_not_treated_as_a_generic_dag():
    engine = WorkflowEngine(EcflowBackend())
    suite = engine.Suite("demo")
    dated = suite.add_family("dated").add_repeat_date("YMD", 20260101, 20260102)
    dated.add_task("one").add_trigger("two == complete")
    dated.add_task("two").add_trigger("one == complete or ../signal")
    report = check_workflow_structure(suite)
    assert has_check(report, "GEN_TREE_VALID", "passed")
    assert has_check(report, "GEN_EXPRESSIONS_UNCHECKED", "unchecked")


@pytest.mark.parametrize("parent_kind,code", [
    ("file", "GEN_OUTPUT_PARENT_INVALID"),
    ("readonly_directory", "GEN_OUTPUT_NOT_WRITABLE"),
    ("directory_destination", "GEN_OUTPUT_NOT_FILE"),
    ("readonly_file", "GEN_OUTPUT_NOT_WRITABLE"),
])
def test_output_type_and_permissions_fail_before_builder(tmp_path, parent_kind, code):
    parent = tmp_path / "target"
    output = parent / "demo.def"
    if parent_kind == "file":
        parent.write_text("parent is file")
    else:
        parent.mkdir()
        if parent_kind == "readonly_directory":
            parent.chmod(0o555)
        elif parent_kind == "directory_destination":
            output.mkdir()
        else:
            output.write_text("previous")
            output.chmod(0o444)
    called = []
    try:
        with pytest.raises(GenerationCheckError) as caught:
            generate_workflow(config(tmp_path), output=output,
                              suite_builder=lambda *args: called.append(True))
        assert_failure(caught.value, code, "definition.preflight")
        assert not called
        if parent_kind == "readonly_file":
            assert output.read_text() == "previous"
            assert output.stat().st_mode & 0o777 == 0o444
    finally:
        if parent_kind == "readonly_directory":
            parent.chmod(0o755)


@pytest.mark.parametrize("explicit", [False, True])
def test_success_reports_only_current_default_or_explicit_definition(tmp_path, explicit):
    report = GenerationCheckReport()
    selected = tmp_path / "elsewhere/custom.definition" if explicit else None
    result = generate_workflow(config(tmp_path), output=selected,
                               suite_builder=build_suite, check_report=report)
    expected = selected if explicit else tmp_path / "out/demo.def"
    assert result.output_path == expected
    assert report.artifacts == [{"path": str(expected), "role": "definition",
                                 "mode": oct(expected.stat().st_mode & 0o777),
                                 "sha256": hashlib.sha256(expected.read_bytes()).hexdigest()}]
    assert has_check(report, "GEN_SERIALIZER_VALID", "passed")


def test_default_definition_name_cannot_escape_output_root(tmp_path):
    settings = config(tmp_path)
    settings.workflow_name = "../escape"
    with pytest.raises(GenerationCheckError) as caught:
        generate_workflow(settings, suite_builder=build_suite)
    assert_failure(caught.value, "GEN_PATH_INVALID", "definition.preflight")
    assert not (tmp_path / "escape.def").exists()


def test_after_save_corruption_is_detected_and_current_bad_file_is_reported(tmp_path):
    report = GenerationCheckReport()
    def corrupt(context):
        context.output_path.write_text("corrupt saved definition")
    with pytest.raises(GenerationCheckError) as caught:
        generate_workflow(config(tmp_path), suite_builder=build_suite,
                          after_save=corrupt, check_report=report)
    assert_failure(caught.value, "GEN_DEFINITION_INVALID", "definition.output")
    output = tmp_path / "out/demo.def"
    assert output.read_text() == "corrupt saved definition"
    assert report.artifacts[0]["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()


def test_after_save_brand_comments_are_accepted_without_claiming_native_jobs(tmp_path):
    report = GenerationCheckReport()
    def brand(context):
        context.output_path.write_text("# application brand\n" + context.output_path.read_text() + "\n# generated footer\n")
    generate_workflow(config(tmp_path), suite_builder=build_suite,
                      after_save=brand, check_report=report)
    assert has_check(report, "GEN_SERIALIZER_VALID", "passed")
    assert not any("JOB" in item.code and item.status == "passed" for item in report.checks)


@pytest.mark.skipif(importlib.util.find_spec("ecflow") is not None,
                    reason="native ecFlow is installed; missing-dependency case is inapplicable")
def test_absent_native_ecflow_is_explicitly_unchecked(tmp_path):
    report = GenerationCheckReport()
    generate_workflow(config(tmp_path), suite_builder=build_suite, check_report=report)
    assert has_check(report, "GEN_NATIVE_ECFLOW_UNAVAILABLE", "unchecked")
    assert not has_check(report, "GEN_NATIVE_ECFLOW_VALID", "passed")


@takler_required
def test_actual_takler_parse_is_distinct_from_job_creation(tmp_path):
    report = GenerationCheckReport()
    result = generate_workflow(config(tmp_path, "takler"), suite_builder=build_suite,
                               check_report=report)
    assert json.loads(result.output_path.read_bytes())["schema_version"] == 1
    assert has_check(report, "GEN_TAKLER_DEFINITION_VALID", "passed")
    assert has_check(report, "GEN_TAKLER_JOB_UNCHECKED", "unchecked")


@takler_required
def test_valid_takler_json_cannot_silently_lose_built_tasks_after_save(tmp_path):
    def remove_children(context):
        document = json.loads(context.output_path.read_bytes())
        document["root"]["children"] = []
        context.output_path.write_text(json.dumps(document))
    with pytest.raises(GenerationCheckError) as caught:
        generate_workflow(config(tmp_path, "takler"), suite_builder=build_suite,
                          after_save=remove_children)
    assert_failure(caught.value, "GEN_DEFINITION_INVALID", "definition.output")


@pytest.mark.parametrize("phase", ["save", "after_save"])
def test_original_callback_exception_and_partial_artifact_are_preserved(tmp_path, monkeypatch, phase):
    report = GenerationCheckReport()
    failure = RuntimeError(f"original {phase} error")
    partial = f"partial output from {phase}"
    def fail_save(engine, suite, output):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(partial)
        raise failure
    def fail_after(context):
        context.output_path.write_text(partial)
        raise failure
    if phase == "save":
        monkeypatch.setattr(WorkflowEngine, "save_suite", fail_save)
    with pytest.raises(RuntimeError) as caught:
        generate_workflow(config(tmp_path), suite_builder=build_suite,
                          after_save=fail_after if phase == "after_save" else None,
                          check_report=report)
    assert caught.value is failure
    output = tmp_path / "out/demo.def"
    assert output.read_text() == partial
    assert len(report.artifacts) == 1
    assert report.artifacts[0]["path"] == str(output)
    assert report.artifacts[0]["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert has_check(report, "GEN_SAVE_FAILED" if phase == "save" else "GEN_AFTER_SAVE_FAILED", "failed")


def test_save_failure_without_writing_does_not_claim_existing_file_as_current(tmp_path, monkeypatch):
    output = tmp_path / "out/demo.def"
    output.parent.mkdir()
    output.write_text("old definition")
    output.chmod(0o640)
    manifest = output.parent / "generation_manifest.json"
    manifest.write_text("old manifest")
    report = GenerationCheckReport()
    failure = OSError("save failed before writing")
    def fail_save(*args):
        raise failure
    monkeypatch.setattr(WorkflowEngine, "save_suite", fail_save)
    with pytest.raises(OSError) as caught:
        generate_workflow(config(tmp_path), suite_builder=build_suite, check_report=report)
    assert caught.value is failure
    assert output.read_text() == "old definition"
    assert output.stat().st_mode & 0o777 == 0o640
    assert manifest.read_text() == "old manifest"
    assert report.artifacts == []


def test_shell_syntax_check_does_not_run_business_commands_or_startup_file(tmp_path, monkeypatch):
    marker = tmp_path / "business-marker"
    startup = tmp_path / "startup.sh"
    startup.write_text(f'touch "{marker}"\n')
    monkeypatch.setenv("BASH_ENV", str(startup))
    script = tmp_path / "runner.sh"
    script.write_text(f'#!/bin/bash\ntouch "{marker}"\n')
    report = check_shell_output(script)
    assert has_check(report, "GEN_SHELL_SYNTAX_VALID", "passed")
    assert not marker.exists()


@pytest.mark.parametrize("suffix,text,code", [
    (".sh", "#!/usr/bin/env unavailable-shell\necho valid\n", "GEN_SHELL_UNAVAILABLE"),
    (".sh", "#!/bin/bash\necho '{{ RUNTIME }}'\n", "GEN_RUNTIME_TEMPLATE_UNCHECKED"),
    (".ecf", "#!/bin/bash\n%include <head.h>\n", "GEN_RUNTIME_TEMPLATE_UNCHECKED"),
])
def test_unavailable_shell_or_runtime_template_is_not_reported_as_syntax_pass(tmp_path, suffix, text, code):
    script = tmp_path / ("runner" + suffix)
    script.write_text(text)
    report = check_shell_output(script)
    assert has_check(report, code, "unchecked")
    assert not has_check(report, "GEN_SHELL_SYNTAX_VALID", "passed")
    assert len(report.artifacts) == 1


@pytest.mark.parametrize("options", ["-O extglob", "-c COMMAND"])
def test_shell_options_are_explicitly_unchecked_and_never_forwarded_as_commands(tmp_path, options):
    marker = tmp_path / "not-executed"
    options = options.replace("COMMAND", repr(f'touch "{marker}"'))
    script = tmp_path / "options.sh"
    script.write_text(f'#!/bin/bash {options}\ntouch "{marker}"\ncase x in +(x)) : ;; esac\n')
    report = check_shell_output(script)
    assert has_check(report, "GEN_SHELL_OPTIONS_UNCHECKED", "unchecked")
    assert not has_check(report, "GEN_SHELL_SYNTAX_VALID", "passed")
    assert not marker.exists()


@pytest.mark.skipif(
    shutil.which("ksh") is None
    or Path(shutil.which("ksh") or "").resolve().name not in {"mksh", "lksh"}
    or shutil.which("ksh93") is not None,
    reason="requires the actual ksh alternative to resolve to mksh/lksh without Ksh93 installed",
)
def test_real_mksh_alternative_does_not_qualify_target_ksh93_syntax(tmp_path):
    script = tmp_path / "target-ksh.sh"
    script.write_text("#!/bin/ksh\nfunction ns.fn { :; }\n")
    report = check_shell_output(script)
    assert has_check(report, "GEN_SHELL_DIALECT_UNAVAILABLE", "unchecked")
    assert not has_check(report, "GEN_SHELL_SYNTAX_VALID", "passed")


@pytest.mark.skipif(shutil.which("mksh") is None, reason="actual mksh is not installed")
def test_explicit_mksh_still_checks_and_rejects_its_invalid_syntax(tmp_path):
    script = tmp_path / "declared-mksh.sh"
    script.write_text("#!/usr/bin/env mksh\nif then\n")
    with pytest.raises(GenerationCheckError) as caught:
        check_shell_output(script)
    assert_failure(caught.value, "GEN_SCRIPT_SYNTAX", "job.output")
    assert len(caught.value.report.artifacts) == 1


@pytest.mark.parametrize("kind", ["relative", "input", "output"])
def test_nul_in_paths_is_a_stable_preflight_diagnostic(tmp_path, kind):
    report = GenerationCheckReport()
    with pytest.raises(GenerationCheckError) as caught:
        if kind == "relative":
            check_relative_path(tmp_path, "bad\x00name", stage="definition.preflight", report=report)
        else:
            checker = check_input_file if kind == "input" else check_output_path
            checker(tmp_path / "bad\x00name", stage="definition.preflight", report=report)
    assert_failure(caught.value, "GEN_PATH_INVALID", "definition.preflight")
    assert "\x00" not in str(caught.value)
