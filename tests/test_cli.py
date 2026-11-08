"""Public CLI lifecycle, artifact parity, safe failures and parser boundaries."""
from dataclasses import replace
import json
import logging
import sys
import types
import warnings

from click.testing import CliRunner
import pytest
import yaml

from takflow.application import ApplicationExtension
from takflow.build import build, BuildError
from takflow.cli import ApplicationLoadError, create_cli, load_application, main
from test_build import application, comparable, data, put, resources

SECRET = "must-never-appear-in-cli-output"


def configuration(tmp_path, mode="shell", **values):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data(tmp_path / "output", mode, **values)))
    return path


def invoke(app, path, *command, format="json", **values):
    options = [value for key, value in values.items() for value in ("--" + key.replace("_", "-"), str(value))]
    return CliRunner().invoke(create_cli(app), ["--format", format, *command, "--config-file", str(path), *options])


@pytest.mark.parametrize("mode", ["shell", "ecflow"])
def test_cli_and_python_full_build_are_equivalent(tmp_path, resources, mode):
    app = application(resources)
    path = configuration(tmp_path, mode)
    with app.prepare(path) as context:
        expected = build(context)
    original = comparable(tmp_path / "output")
    response = invoke(app, path, "build")
    assert response.exit_code == 0, response.output
    report = json.loads(response.output)
    result = report["result"]
    assert report["status"] == "success" and result["complete"]
    assert result["stages"] == expected.as_dict()["stages"]
    assert comparable(tmp_path / "output") == original
    def metadata(items):
        return [{key: value for key, value in item.items() if key != "sha256"} for item in items]
    assert metadata(result["artifacts"]) == metadata(expected.as_dict()["artifacts"])
    assert report["diagnostics"] == []


def test_single_stages_share_preconditions_and_invalidate_manifest(tmp_path, resources):
    path = configuration(tmp_path)
    app = application(resources)
    missing = invoke(app, path, "job", "generate")
    assert missing.exit_code == 1
    failed = json.loads(missing.output)["result"]
    assert next(stage for stage in failed["stages"] if stage["name"] == "job")["status"] == "failed"
    assert all(stage["status"] == "not_run" for stage in failed["stages"] if stage["name"] != "job")
    assert not failed["complete"]
    for stage in ("resource", "config", "credential", "job", "workflow"):
        result = invoke(app, path, stage, "copy" if stage == "resource" else "generate")
        assert result.exit_code == 0, result.output
        report = json.loads(result.output)["result"]
        assert report["scope"] == "stage" and not report["complete"] and report["manifest_path"] is None
        assert all(item["status"] == "not_run" for item in report["stages"] if item["name"] != stage)
        assert next(item for item in report["stages"] if item["name"] == stage)["status"] == ("skipped" if stage == "credential" else "passed")
    complete = invoke(app, path, "build")
    assert complete.exit_code == 0
    manifest = tmp_path / "output/generation_manifest.json"
    assert manifest.exists()
    assert invoke(app, path, "config", "generate").exit_code == 0
    assert not manifest.exists()


def test_overrides_before_validation_and_path_resolution(tmp_path, resources):
    path = configuration(tmp_path, "ecflow", machine_name="unknown", output_repo_base_dir="relative-output")
    external = "/target/site-not-local"
    output = tmp_path / "override"
    workflow = tmp_path / "custom/workflow.def"
    response = invoke(application(resources), path, "build", output_repo_base=output,
                      workflow_repo_base=resources, machine_name="site", machine_dir=external, output=workflow)
    assert response.exit_code == 0, response.output
    report = json.loads(response.output)["result"]
    assert report["output_root"] == str(output) and report["workflow_output"] == str(workflow)
    assert workflow.exists() and not (output / "machine").exists()
    assert f"%includenopp <{external}/env/runtime.sh>" in (output / "jobs/on/task.ecf").read_text()


@pytest.mark.parametrize("arguments", [[], ["build"], ["build", "--config-file", "x", "--unknown", "secret"],
    ["--format", "xml", "build"], ["resource", "copy", "--config-file", "x", "--output", "x"],
    ["job", "generate", "--config-file", "x", "--credential-file", "x"]])
def test_invalid_arguments_do_not_load_application(arguments):
    def forbidden():
        pytest.fail("parser must not load application")
    response = CliRunner().invoke(create_cli(forbidden), arguments)
    assert response.exit_code == 2, response.output
    assert "{" not in response.stdout


@pytest.mark.parametrize("args", [["--help"], ["--version"], ["build", "--help"], ["workflow", "generate", "--help"]])
def test_help_is_lazy(args):
    def forbidden():
        pytest.fail("help must not load application")
    response = CliRunner().invoke(create_cli(forbidden), args)
    assert response.exit_code == 0, response.output


def test_explicit_application_reference_and_binding(tmp_path, resources, monkeypatch):
    module = types.ModuleType("test_cli_application")
    module.instance = application(resources)
    calls = []
    def factory():
        calls.append("factory")
        return module.instance
    module.factory = factory
    monkeypatch.setitem(sys.modules, module.__name__, module)
    assert load_application("test_cli_application:instance") is module.instance
    path = configuration(tmp_path)
    response = CliRunner().invoke(main, ["--application", "test_cli_application:factory", "--format", "json", "build", "--config-file", str(path)])
    assert response.exit_code == 0, response.output
    assert calls == ["factory"]
    assert CliRunner().invoke(main, ["build", "--config-file", str(path)]).exit_code == 2
    assert CliRunner().invoke(create_cli(module.instance), ["--application", "other:app"]).exit_code == 2
    with pytest.raises(ApplicationLoadError) as error:
        load_application("not_installed_tc12:app")
    assert isinstance(error.value.__cause__, ModuleNotFoundError)
    for reference in ("os.system('x')", "module", "module:a.b"):
        with pytest.raises(ApplicationLoadError):
            load_application(reference)


def test_initialization_once_and_safe_output(tmp_path, resources):
    calls = []
    def initialize():
        calls.append("init")
        print(SECRET)
        print(SECRET, file=sys.stderr)
        logging.error(SECRET)
        warnings.warn(SECRET)
    app = application(resources, extensions=(ApplicationExtension("test", initialize=initialize),))
    previous = logging.root.manager.disable
    result = invoke(app, configuration(tmp_path), "build")
    assert result.exit_code == 0, result.output
    assert calls == ["init"] and SECRET not in result.output
    assert json.loads(result.output)["warnings"][0]["count"] == 1
    assert logging.root.manager.disable == previous


@pytest.mark.parametrize("failure", ["factory", "prepare", "validation", "template", "partial"])
def test_controlled_failures_and_partial_results(tmp_path, resources, monkeypatch, failure):
    app = application(resources)
    path = configuration(tmp_path)
    if failure == "factory":
        def app():
            print(SECRET)
            raise RuntimeError(SECRET)
    elif failure == "prepare":
        def bad_context(context):
            raise RuntimeError(SECRET)
        app = replace(app, context=bad_context)
    elif failure == "validation":
        path.write_text(yaml.safe_dump({"workflow_mode": SECRET}))
    elif failure == "template":
        (resources / "config/config.sh.j2").unlink()
    else:
        import takflow.build as module
        original = module.write_text
        def fail(path, text, mode, root):
            original(path, text, mode, root)
            if str(path).endswith("config/config.sh"):
                raise OSError(SECRET)
        monkeypatch.setattr(module, "write_text", fail)
    result = invoke(app, path, "build")
    assert result.exit_code == 1, result.output
    assert SECRET not in result.output and "Traceback" not in result.output
    report = json.loads(result.output)
    if failure in ("template", "partial"):
        assert report["result"]["stages"][1]["status"] == "failed"
        assert report["result"]["stages"][0]["status"] == "passed"
        assert not (tmp_path / "output/generation_manifest.json").exists()
        with pytest.raises(BuildError) as error:
            with app.prepare(path) as context:
                build(context)
        assert report["result"]["stages"] == error.value.result.as_dict()["stages"]
        assert [item["code"] for item in report["result"]["diagnostics"]] == [item["code"] for item in error.value.result.diagnostics]
        if failure == "partial":
            assert any(item["role"] == "config" for item in report["result"]["artifacts"])
            assert str(error.value.original) == SECRET
    else:
        assert report["result"] is None and report["diagnostics"]


def test_text_lists_statuses_and_artifacts(tmp_path, resources):
    result = invoke(application(resources), configuration(tmp_path), "build", format="text")
    assert result.exit_code == 0
    assert "credential: skipped" in result.output and "manifest:" in result.output
    assert "config [generated 0o644]" in result.output


def test_interrupt_and_log_restore(tmp_path, resources):
    previous = logging.root.manager.disable
    def factory():
        raise KeyboardInterrupt
    result = invoke(factory, configuration(tmp_path), "build")
    assert result.exit_code == 130 and json.loads(result.output)["diagnostics"][0]["code"] == "CLI_INTERRUPTED"
    assert logging.root.manager.disable == previous


def test_generation_never_executes_business_or_machine_shell(tmp_path, resources, monkeypatch):
    import subprocess
    marker = tmp_path / "executed"
    put(resources, "scripts/on/task.sh", f"#!/bin/bash\ntouch '{marker}'\n")
    put(resources, "machine/site/env/runtime.sh", f"touch '{marker}'\n")
    original = subprocess.run
    calls = []
    def checked(command, *args, **kwargs):
        calls.append(command)
        assert command[1] == "-n", "generation must only invoke interpreter syntax checks"
        return original(command, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", checked)
    response = invoke(application(resources), configuration(tmp_path), "build")
    assert response.exit_code == 0, response.output
    assert calls and not marker.exists()


def test_shell_output_override_remains_a_controlled_error(tmp_path, resources):
    response = invoke(application(resources), configuration(tmp_path), "build", output=tmp_path / "other.sh")
    assert response.exit_code == 1
    assert json.loads(response.output)["diagnostics"][0]["code"] == "APPLICATION_OUTPUT_UNSUPPORTED"


def test_module_import_output_and_original_error_are_suppressed(tmp_path, monkeypatch):
    module = tmp_path / "tc12_unsafe_import.py"
    module.write_text(f"import sys\nprint({SECRET!r})\nprint({SECRET!r}, file=sys.stderr)\nraise RuntimeError({SECRET!r})\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    response = CliRunner().invoke(main, ["--application", "tc12_unsafe_import:app", "--format", "json", "build", "--config-file", "unused.yaml"])
    assert response.exit_code == 1 and SECRET not in response.output
    assert json.loads(response.output)["diagnostics"][0]["code"] == "CLI_APPLICATION_LOAD"


def test_domain_validator_message_is_not_exposed(tmp_path, resources):
    from pydantic import field_validator
    from takflow.config import BaseWorkflowConfig
    class DomainConfig(BaseWorkflowConfig):
        @field_validator("workflow_name")
        @classmethod
        def reject(cls, value):
            raise ValueError(SECRET)
    response = invoke(application(resources, config_type=DomainConfig), configuration(tmp_path), "build")
    assert response.exit_code == 1 and SECRET not in response.output
    assert json.loads(response.output)["diagnostics"][0]["code"] == "CONFIG_DOMAIN_RULE"
