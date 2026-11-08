"""Public full/step generation, artifact ownership and failure semantics."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

import pytest
from jinja2 import TemplateNotFound, UndefinedError

from takflow.application import (
    Application, ApplicationBrand, ApplicationExtension, ComponentSelection,
    ResourceEntry, ResourceLayer, TemplateOutput,
)
from takflow.build import build, run_stage, BuildError, STAGES
from takflow.config import BaseWorkflowConfig
from takflow.toolkit.credential import register_credential_hook, render_credential_template, CredentialHookPoint
import takflow.build as build_module
import takflow.toolkit.resource as resource_module


SENTINEL = "credential-body-must-not-enter-reports"


def put(root, name, text, mode=0o644):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)
    return path


@pytest.fixture
def resources(tmp_path):
    root = tmp_path / "resources"
    put(root, "config/config.sh.j2", "# {{ build_info_detail }}\nDOMAIN=ready\n")
    put(root, "scripts/on/task.sh", "#!/usr/bin/env bash\nprintf '%s' unchanged\n")
    put(root, "scripts/off/disabled.sh", "invalid disabled content\n", 0o000)
    put(root, "jobs/on/task.sh.j2", """#!/usr/bin/env bash
# {{ build_info_detail }}
{% if config.workflow_mode == 'ecflow' %}
%include <config.h>
{% else %}
. "{{ paths.config_file }}"
{% endif %}
{{ include_machine('env/runtime.sh') }}
{{ invoke_script('scripts/on/task.sh') }}
""")
    put(root, "jobs/off/broken.sh.j2", "{{ broken(\n")
    put(root, "templates/runner.sh.j2", '#!/usr/bin/env bash\n. "{{ paths.jobs_dir }}/on/task.sh"\n')
    put(root, "machine/site/env/runtime.sh", 'RUNTIME_VALUE=before\n')
    put(root, "machine/other/env/runtime.sh", 'OTHER_SITE=1\n')
    return root


def application(resources, **values):
    def suite_builder(config, engine):
        suite = engine.Suite(config.workflow_name)
        root = Path(config.output_repo_base_dir)
        suite.add_variables({"ECF_FILES": str(root / "jobs/on"), "ECF_INCLUDE": str(root / "config")})
        suite.add_task("task")
        return suite

    return Application(**{
        "config_type": BaseWorkflowConfig, "resources": resources,
        "suite_builder": suite_builder, "supported_modes": ("ecflow", "shell", "takler"),
        "shell_template": "templates/runner.sh.j2", "brand": ApplicationBrand("test-domain", "1.0"),
        "select_components": lambda config: ComponentSelection(frozenset({"on"}),
            lambda path: path.parts[1] if len(path.parts) > 1 and path.parts[0] == "scripts" else None,
            lambda path: path.parts[0] if len(path.parts) > 1 else None),
        **values,
    })


def data(output, mode="ecflow", invoke="inline", **values):
    return {"project_base_dir": "/program", "run_base_dir": "/run", "output_repo_base_dir": str(output),
            "workflow_name": "test_workflow", "workflow_mode": mode, "machine_name": "site",
            "script_invoke_mode": invoke, "workload": {"workload_type": "shell"}, **values}


def statuses(result):
    return {item.name: item.status for item in result.stages}


@pytest.mark.parametrize("mode", ["ecflow", "shell"])
@pytest.mark.parametrize("invoke", ["inline", "external"])
def test_complete_pipeline_and_native_artifact_roles(tmp_path, resources, mode, invoke):
    output = tmp_path / "output"
    stale = put(output, "stale.txt", "old")
    with application(resources).prepare(data(output, mode, invoke)) as context:
        result = build(context)
        assert context.checks.artifacts == []
    assert result.complete and result.manifest_path == output / "generation_manifest.json"
    assert statuses(result) == {name: "skipped" if name == "credential" else "passed" for name in STAGES}
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["complete"] and manifest["schema_version"] == 1
    assert manifest["build_id"] == result.build_id
    assert manifest["config_fingerprint"]["scope"] == "public-generation-options"
    assert {item.kind for item in result.artifacts} == {"generated", "copied", "reference"}
    assert str(stale) not in {item.path for item in result.artifacts}
    assert not (output / "scripts/off").exists() and not (output / "machine/other").exists()
    assert any(item.mutable and item.kind == "reference" for item in result.artifacts)
    job = output / ("jobs/on/task.ecf" if mode == "ecflow" else "jobs/on/task.sh")
    assert job.stat().st_mode & 0o777 == 0o755
    assert (output / "scripts/on/task.sh").stat().st_mode & 0o777 == 0o755
    assert (output / "machine/site/env/runtime.sh").stat().st_mode & 0o777 == 0o644
    assert context.paths.config_file.stat().st_mode & 0o777 == 0o644
    assert context.paths.workflow_output.stat().st_mode & 0o777 == (0o755 if mode == "shell" else 0o644)
    assert result.manifest_path.stat().st_mode & 0o777 == 0o644
    assert ("%includenopp <" in job.read_text()) == (mode == "ecflow")
    assert "RUNTIME_VALUE=before" not in job.read_text(), "machine content must remain referenced"


def comparable(root):
    result = {}
    for path in root.rglob("*"):
        if path.is_file() and path.name != "generation_manifest.json":
            content = path.read_bytes().replace(str(root).encode(), b"<OUTPUT>")
            content = re.sub(rb"at \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", b"at <BUILD_TIME>", content)
            result[str(path.relative_to(root))] = (content, path.stat().st_mode & 0o777)
    return result


@pytest.mark.parametrize("mode", ["ecflow", "shell"])
def test_complete_and_step_business_artifacts_are_equivalent(tmp_path, resources, mode):
    app = application(resources)
    with app.prepare(data(tmp_path / "full", mode)) as context:
        full = build(context)
    with app.prepare(data(tmp_path / "steps", mode)) as context:
        for stage in STAGES[:5]:
            result = run_stage(context, stage)
            assert not result.complete and result.manifest_path is None
            assert statuses(result)[stage] in ("passed", "skipped")
            assert all(item.status == "not_run" for item in result.stages if item.name != stage)
        assert all(item.stage == "workflow" for item in result.artifacts)
        assert run_stage(context, "check").artifacts == []
    assert full.complete
    assert comparable(tmp_path / "full") == comparable(tmp_path / "steps")


def test_step_rewrite_invalidates_previous_success(tmp_path, resources):
    with application(resources).prepare(data(tmp_path / "out")) as context:
        previous = build(context)
        result = run_stage(context, "config")
    assert not previous.manifest_path.exists()
    assert not result.complete
    assert {item.role for item in result.artifacts} == {"config"}


def test_single_stage_does_not_implicitly_run_prerequisites(tmp_path, resources):
    output = tmp_path / "out"
    with application(resources).prepare(data(output)) as context:
        with pytest.raises(BuildError) as captured:
            run_stage(context, "job")
    error = captured.value
    assert statuses(error.result)["job"] == "failed"
    assert statuses(error.result)["resource"] == "not_run"
    assert not (output / "scripts").exists()


@pytest.mark.parametrize("mask", [0o000, 0o077])
def test_exact_permissions_on_existing_files_and_directories(tmp_path, resources, mask):
    output = tmp_path / "out"
    put(output, "config/config.h", "old", 0o777)
    put(output, "jobs/on/task.ecf", "old", 0o777)
    (output / "config").chmod(0o700)
    old = os.umask(mask)
    try:
        with application(resources).prepare(data(output)) as context:
            build(context)
    finally:
        os.umask(old)
    assert (output / "config").stat().st_mode & 0o777 == 0o755
    assert (output / "config/config.h").stat().st_mode & 0o777 == 0o644
    assert (output / "jobs/on/task.ecf").stat().st_mode & 0o777 == 0o755


def test_layered_resources_and_templates_share_final_precedence(tmp_path, resources):
    extension = tmp_path / "extension"
    put(extension, "scripts/on/task.sh", "#!/bin/sh\nprintf override\n")
    put(extension, "config/config.sh.j2", "# override config\n")
    put(extension, "jobs/on/task.sh.j2", "#!/bin/sh\n# selected final layer\n")
    # An obsolete shadowed base template cannot cause a render failure.
    put(resources, "jobs/on/task.sh.j2", "{{ invalid(\n")
    app = application(resources, resource_layers=(ResourceLayer("oper", extension),))
    with app.prepare(data(tmp_path / "out")) as context:
        result = build(context)
    assert "override config" in context.paths.config_file.read_text()
    assert "selected final layer" in (tmp_path / "out/jobs/on/task.ecf").read_text()
    artifact = next(item for item in result.artifacts if item.path.endswith("scripts/on/task.sh"))
    assert [source["layer"] for source in artifact.sources] == ["base", "oper"]


@pytest.mark.parametrize("missing", ["config/config.sh.j2", "scripts/on/task.sh", "machine/site/env/runtime.sh"])
def test_missing_required_inputs_fail_at_responsible_stage(tmp_path, resources, missing):
    (resources / missing).unlink()
    output = tmp_path / "out"
    put(output, "generation_manifest.json", '{"complete": true}')
    with application(resources).prepare(data(output)) as context:
        with pytest.raises(BuildError) as captured:
            build(context)
    assert not (output / "generation_manifest.json").exists()
    expected = "config" if missing.startswith("config") else "job"
    assert statuses(captured.value.result)[expected] == "failed"
    assert statuses(captured.value.result)["report"] == "not_run"


def test_strict_undefined_and_optional_extra_outputs(tmp_path, resources):
    app = application(resources, outputs=(TemplateOutput("absent.j2", "optional.txt", required=False),))
    with app.prepare(data(tmp_path / "out")) as context:
        result = build(context)
    assert result.stages[1].skipped_outputs == [str(tmp_path / "out/optional.txt")]
    put(resources, "config/config.sh.j2", "{{ missing_domain_value }}")
    with app.prepare(data(tmp_path / "bad")) as context:
        with pytest.raises(BuildError) as captured:
            build(context)
    assert isinstance(captured.value.original, UndefinedError)
    assert statuses(captured.value.result)["config"] == "failed"


def credentials(resources, error=None):
    def initialize():
        def fragment(context):
            if error is not None:
                raise error
            return render_credential_template(str(resources), context.credential, context.config)
        register_credential_hook(CredentialHookPoint.RENDER)(fragment)
    return ApplicationExtension("credentials", initialize)


def test_credentials_are_private_and_never_hashed_in_reports(tmp_path, resources):
    put(resources, "config/credential_workflow.sh.j2", "export TOKEN='{{ credential.token }}'\n")
    credential = put(tmp_path, "credential.yaml", f"token: {SENTINEL}\n", 0o600)
    app = application(resources, credential_enabled=True, extensions=(credentials(resources),))
    with app.prepare(data(tmp_path / "out")) as context:
        result = build(context, credential_file=credential)
    artifact = next(item for item in result.artifacts if item.role == "credential")
    assert artifact.mode == "0o600" and artifact.sha256 is None and artifact.sensitive
    assert SENTINEL in Path(artifact.path).read_text()
    rendered = result.manifest_path.read_text() + json.dumps(result.as_dict())
    assert SENTINEL not in rendered
    assert hashlib.sha256(Path(artifact.path).read_bytes()).hexdigest() not in rendered
    assert "sha256" not in next(item for item in json.loads(result.manifest_path.read_text())["artifacts"] if item["role"] == "credential")


@pytest.mark.parametrize("file_kind", ["unconfigured", "missing"])
def test_enabled_credentials_distinguish_unconfigured_and_missing(tmp_path, resources, file_kind):
    app = application(resources, credential_enabled=True, extensions=(credentials(resources),))
    with app.prepare(data(tmp_path / "out")) as context:
        with pytest.raises(BuildError) as captured:
            build(context, credential_file=None if file_kind == "unconfigured" else tmp_path / "absent.yaml")
    codes = {item["code"] for item in captured.value.result.diagnostics}
    assert ("BUILD_CREDENTIAL_UNCONFIGURED" if file_kind == "unconfigured" else "GEN_INPUT_MISSING") in codes
    assert statuses(captured.value.result)["credential"] == "failed"
    assert statuses(captured.value.result)["job"] == "not_run"


def test_credential_failure_preserves_original_without_logging_body(tmp_path, resources, caplog):
    original = RuntimeError(SENTINEL)
    credential = put(tmp_path, "credential.yaml", "token: unused\n")
    app = application(resources, credential_enabled=True, extensions=(credentials(resources, original),))
    with app.prepare(data(tmp_path / "out")) as context:
        with pytest.raises(BuildError) as captured:
            build(context, credential_file=credential)
    assert captured.value.original is original and captured.value.__cause__ is original
    assert SENTINEL not in str(captured.value) + caplog.text + json.dumps(captured.value.result.as_dict())
    assert statuses(captured.value.result)["credential"] == "failed"


def test_resource_copy_failure_retains_partial_output_and_stops(tmp_path, resources, monkeypatch):
    original = OSError("copy failed")
    def fail(source, target):
        Path(target).write_text("partial")
        raise original
    monkeypatch.setattr(resource_module.shutil, "copy2", fail)
    output = tmp_path / "out"
    put(output, "generation_manifest.json", "old success")
    with application(resources).prepare(data(output)) as context:
        with pytest.raises(BuildError) as captured:
            build(context)
    assert captured.value.original is original
    assert not (output / "generation_manifest.json").exists()
    assert any(Path(item.path).read_text() == "partial" for item in captured.value.result.artifacts)
    assert statuses(captured.value.result)["resource"] == "failed"
    assert statuses(captured.value.result)["config"] == "not_run"


@pytest.mark.parametrize("stage", ["config", "job", "workflow"])
def test_write_failures_preserve_partial_artifacts(tmp_path, resources, monkeypatch, stage):
    import takflow._files as files
    original = OSError("write failed")
    real_write = files.write_text
    def fail(path, text, mode, root):
        selected = ((stage == "config" and path.name == "config.h") or
                    (stage == "job" and path.suffix == ".ecf") or
                    (stage == "workflow" and path.name == "run_workflow.sh"))
        if selected:
            files.make_parents(path, root)
            path.write_text("partial output")
            raise original
        return real_write(path, text, mode, root)
    monkeypatch.setattr(files, "write_text", fail)
    monkeypatch.setattr(build_module, "write_text", fail)
    output = tmp_path / "out"
    mode = "shell" if stage == "workflow" else "ecflow"
    with application(resources).prepare(data(output, mode)) as context:
        with pytest.raises(BuildError) as captured:
            build(context)
    assert captured.value.original is original
    assert statuses(captured.value.result)[stage] == "failed"
    assert not (output / "generation_manifest.json").exists()
    assert any(Path(item.path).read_text() == "partial output" for item in captured.value.result.artifacts)


@pytest.mark.parametrize("point", ["before", "after"])
def test_save_callback_order_and_original_failure(tmp_path, resources, point):
    events = []
    original = RuntimeError("callback failed")
    def before(context):
        events.append("before")
        if point == "before":
            raise original
    def after(context):
        events.append("after")
        context.output_path.write_text("partial definition")
        raise original
    with application(resources).prepare(data(tmp_path / "out")) as context:
        with pytest.raises(BuildError) as captured:
            build(context, before_save=before, after_save=after)
    assert captured.value.original is original
    assert events == (["before"] if point == "before" else ["before", "after"])
    assert context.paths.workflow_output.exists() == (point == "after")
    assert not (tmp_path / "out/generation_manifest.json").exists()


def test_final_check_rejects_changed_generated_job(tmp_path, resources):
    output = tmp_path / "out"
    def tamper(context):
        (output / "jobs/on/task.ecf").write_text("changed after render")
    with application(resources).prepare(data(output)) as context:
        with pytest.raises(BuildError) as captured:
            build(context, after_save=tamper)
    assert statuses(captured.value.result)["check"] == "failed"
    assert statuses(captured.value.result)["workflow"] == "passed"
    assert statuses(captured.value.result)["report"] == "not_run"
    assert any(item["code"] == "BUILD_ARTIFACT_CHANGED" for item in captured.value.result.diagnostics)


def test_mutable_machine_reference_changes_are_reported_without_freezing(tmp_path, resources):
    output = tmp_path / "out"
    def update(context):
        (output / "machine/site/env/runtime.sh").write_text("RUNTIME_VALUE=after\n")
    with application(resources).prepare(data(output)) as context:
        result = build(context, after_save=update)
    assert result.complete
    assert any(item["code"] == "BUILD_MUTABLE_REFERENCE_CHANGED" for item in result.diagnostics)
    assert "%includenopp" in (output / "jobs/on/task.ecf").read_text()


def test_manifest_publish_failure_never_leaves_success(tmp_path, resources, monkeypatch):
    original = OSError("replace failed")
    def fail(*args):
        raise original
    monkeypatch.setattr(build_module.os, "replace", fail)
    output = tmp_path / "out"
    put(output, "generation_manifest.json", "old success")
    with application(resources).prepare(data(output)) as context:
        with pytest.raises(BuildError) as captured:
            build(context)
    assert captured.value.original is original
    assert statuses(captured.value.result)["report"] == "failed"
    assert not captured.value.result.complete
    assert not (output / "generation_manifest.json").exists()
    assert not list(output.glob(".generation_manifest.*"))


def test_external_machine_is_referenced_without_copy_or_fallback(tmp_path, resources):
    with application(resources).prepare(data(tmp_path / "out", machine_dir="/remote/not-mounted/site")) as context:
        result = build(context)
    assert result.complete
    assert not (tmp_path / "out/machine").exists()
    assert any(item.kind == "reference" and item.sha256 is None and item.mode is None for item in result.artifacts)


def test_shell_variable_channel_quotes_values_and_reads_updated_machine(tmp_path, resources):
    output = tmp_path / "out with spaces"
    value = "space ' quote $HOME `touch should-not-execute`"
    app = application(resources, variables=lambda config: {"DOMAIN_VALUE": value})
    with app.prepare(data(output, "shell", "external")) as context:
        build(context)
    command = '. "$1"; . "$MACHINE_DIR/env/runtime.sh"; printf "%s\\n%s" "$DOMAIN_VALUE" "$RUNTIME_VALUE"'
    first = subprocess.check_output(["bash", "-c", command, "bash", str(output / "config/config.sh")], text=True)
    assert first == value + "\nbefore"
    (output / "machine/site/env/runtime.sh").write_text("RUNTIME_VALUE=after\n")
    second = subprocess.check_output(["bash", "-c", command, "bash", str(output / "config/config.sh")], text=True)
    assert second == value + "\nafter"
    assert not (Path.cwd() / "should-not-execute").exists()


def test_reserved_output_and_input_aliases_fail_before_overwrite(tmp_path, resources):
    app = application(resources, outputs=(TemplateOutput("config/config.sh.j2", "config/config.h"),))
    with app.prepare(data(tmp_path / "out")) as context:
        with pytest.raises(BuildError) as captured:
            build(context)
    assert statuses(captured.value.result)["config"] == "failed"
    assert not (tmp_path / "out/config/config.h").exists()


def test_credential_step_preserves_private_existing_directory(tmp_path, resources):
    put(resources, "config/credential_workflow.sh.j2", "export TOKEN='{{ credential.token }}'\n")
    credential = put(tmp_path, "credential.yaml", f"token: {SENTINEL}\n")
    output = tmp_path / "out"
    put(output, "config/credential.sh", "old", 0o755)
    (output / "config").chmod(0o700)
    app = application(resources, credential_enabled=True, extensions=(credentials(resources),))
    with app.prepare(data(output)) as context:
        result = run_stage(context, "credential", credential_file=credential)
    assert (output / "config").stat().st_mode & 0o777 == 0o700
    assert (output / "config/credential.sh").stat().st_mode & 0o777 == 0o600
    assert result.artifacts[0].sha256 is None


def test_sensitive_additional_output_uses_same_no_digest_policy(tmp_path, resources):
    put(resources, "config/sensitive.j2", SENTINEL)
    app = application(resources, outputs=(TemplateOutput("config/sensitive.j2", "config/private.sh", mode=0o600),))
    with app.prepare(data(tmp_path / "out")) as context:
        result = build(context)
    artifact = next(item for item in result.artifacts if item.path.endswith("private.sh"))
    assert artifact.sensitive and artifact.sha256 is None and artifact.mode == "0o600"
    assert SENTINEL not in result.manifest_path.read_text()


def test_registered_source_and_output_hardlink_is_rejected(tmp_path, resources):
    output = tmp_path / "out"
    target = output / "config/config.h"
    target.parent.mkdir(parents=True)
    original = resources / "config/config.sh.j2"
    os.link(original, target)
    before = original.read_bytes()
    with application(resources).prepare(data(output)) as context:
        with pytest.raises(BuildError) as captured:
            build(context)
    assert original.read_bytes() == before
    assert statuses(captured.value.result)["config"] == "failed"


def test_empty_selected_resource_directory_is_preserved(tmp_path, resources):
    (resources / "utils/empty").mkdir(parents=True)
    with application(resources).prepare(data(tmp_path / "out")) as context:
        run_stage(context, "resource")
    assert (tmp_path / "out/utils/empty").is_dir()
    assert (tmp_path / "out/utils/empty").stat().st_mode & 0o777 == 0o755


def test_invalid_stage_does_not_modify_previous_success(tmp_path, resources):
    output = tmp_path / "out"
    marker = put(output, "generation_manifest.json", "previous success")
    with application(resources).prepare(data(output)) as context:
        with pytest.raises(ValueError, match="Unknown generation stage"):
            run_stage(context, "misspelled")
    assert marker.read_text() == "previous success"


def test_explicit_definition_output_cannot_overwrite_copied_source(tmp_path, resources):
    source = resources / "scripts/on/task.sh"
    original = source.read_bytes()
    with application(resources).prepare(data(tmp_path / "out"), output=source) as context:
        with pytest.raises(BuildError) as captured:
            build(context)
    assert source.read_bytes() == original
    assert statuses(captured.value.result)["workflow"] == "failed"


def test_standard_slurm_shell_log_directory_permissions(tmp_path, resources):
    old = os.umask(0o077)
    try:
        with application(resources).prepare(data(tmp_path / "out", "shell", workload={"workload_type": "slurm", "submit_carrier": "orvix", "wckey": "test-account"})) as context:
            build(context)
    finally:
        os.umask(old)
    assert (tmp_path / "out/logs").stat().st_mode & 0o777 == 0o755


def test_optional_template_does_not_hide_missing_nested_dependency(tmp_path, resources):
    put(resources, "config/optional.j2", "{% include 'missing-required.j2' %}")
    app = application(resources, outputs=(TemplateOutput("config/optional.j2", "optional.txt", required=False),))
    with app.prepare(data(tmp_path / "out")) as context:
        with pytest.raises(BuildError) as captured:
            build(context)
    assert isinstance(captured.value.original, TemplateNotFound)
    assert statuses(captured.value.result)["config"] == "failed"


def test_disabled_component_does_not_require_its_declared_resource(tmp_path, resources):
    app = application(resources, resource_entries=(
        ResourceEntry("scripts/on", "scripts/on", executable=True, required=True),
        ResourceEntry("scripts/off-missing", "scripts/off-missing", required=True),
    ))
    with app.prepare(data(tmp_path / "out")) as context:
        result = build(context)
    assert result.complete
    assert not (tmp_path / "out/scripts/off-missing").exists()


