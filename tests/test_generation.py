"""Regression tests for application-neutral workflow generation."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import takflow.generation as generation
from takflow.config import BaseWorkflowConfig, ShellWorkload
from takflow.flow import WorkflowEngine
from takflow.generation import generate_workflow


def _config(tmp_path: Path, mode: str = "ecflow") -> BaseWorkflowConfig:
    return BaseWorkflowConfig(
        project_base_dir=str(tmp_path / "project"),
        run_base_dir=str(tmp_path / "run"),
        output_repo_base_dir=str(tmp_path / "from-config"),
        workflow_name="demo",
        workflow_mode=mode,
        workload=ShellWorkload(),
    )


def _build_suite(config: BaseWorkflowConfig, engine: WorkflowEngine):
    return engine.Suite(config.workflow_name)


@pytest.mark.parametrize(
    "mode",
    [
        "ecflow",
        pytest.param(
            "takler",
            marks=pytest.mark.skipif(
                importlib.util.find_spec("takler") is None,
                reason="takler is not installed",
            ),
        ),
    ],
)
def test_definition_default_output_and_result(mode, tmp_path):
    config = _config(tmp_path, mode)
    selected_output = tmp_path / "from-argument"
    built = []

    def builder(config, engine):
        assert config.output_repo_base_dir == str(selected_output)
        suite = engine.Suite(config.workflow_name)
        built.append(suite)
        return suite

    result = generate_workflow(
        config,
        output_repo_base=selected_output,
        suite_builder=builder,
    )

    suffix = ".def" if mode == "ecflow" else ".json"
    output_path = selected_output / f"demo{suffix}"
    assert result.mode == mode
    assert result.output_repo_base == selected_output
    assert result.output_path == output_path
    assert result.suite is built[0]
    assert output_path.is_file()
    assert not (tmp_path / "from-config").exists()


def test_definition_explicit_output_is_used_verbatim(tmp_path):
    config = _config(tmp_path)
    output = tmp_path / "elsewhere" / "definition.custom"

    result = generate_workflow(
        config,
        output=output,
        suite_builder=_build_suite,
    )

    assert result.output_path == output
    assert output.is_file()
    assert not (tmp_path / "from-config" / "demo.def").exists()


def test_missing_output_repo_is_an_error(tmp_path):
    config = _config(tmp_path)
    config.output_repo_base_dir = None

    with pytest.raises(ValueError, match="output_repo_base_dir is not set"):
        generate_workflow(config, suite_builder=_build_suite)


def test_definition_requires_suite_builder(tmp_path):
    with pytest.raises(ValueError, match="suite_builder is required"):
        generate_workflow(_config(tmp_path))


def test_shell_requires_shell_renderer(tmp_path):
    config = _config(tmp_path, "shell")

    with pytest.raises(ValueError, match="shell_renderer is required"):
        generate_workflow(config)


def test_unsupported_mode_is_an_error(tmp_path):
    config = _config(tmp_path).model_copy(update={"workflow_mode": "unknown"})

    with pytest.raises(ValueError, match="Unsupported workflow_mode: unknown"):
        generate_workflow(config, suite_builder=_build_suite)


def test_definition_callback_order_and_context(tmp_path, monkeypatch):
    config = _config(tmp_path)
    output = tmp_path / "from-config" / "demo.def"
    events = []
    contexts = []

    def builder(config, engine):
        events.append("builder")
        return engine.Suite(config.workflow_name)

    def before_save(context):
        events.append("before_save")
        contexts.append(context)
        assert not output.exists()

    def after_save(context):
        events.append("after_save")
        contexts.append(context)
        assert output.is_file()

    original_save = WorkflowEngine.save_suite

    def recording_save(self, suite, output_path):
        events.append("save")
        original_save(self, suite, output_path)

    monkeypatch.setattr(WorkflowEngine, "save_suite", recording_save)
    result = generate_workflow(
        config,
        suite_builder=builder,
        before_save=before_save,
        after_save=after_save,
    )

    assert events == ["builder", "before_save", "save", "after_save"]
    assert contexts[0] is contexts[1]
    context = contexts[0]
    assert context.config is config
    assert context.suite is result.suite
    assert context.engine is result.suite.engine
    assert context.output_repo_base == tmp_path / "from-config"
    assert context.output_path == output


def test_before_save_failure_preserves_existing_definition(tmp_path):
    config = _config(tmp_path)
    output = tmp_path / "from-config" / "demo.def"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"original definition\n")
    after_save_called = False

    def before_save(context):
        raise RuntimeError("before-save failure")

    def after_save(context):
        nonlocal after_save_called
        after_save_called = True

    with pytest.raises(RuntimeError, match="before-save failure"):
        generate_workflow(
            config,
            suite_builder=_build_suite,
            before_save=before_save,
            after_save=after_save,
        )

    assert output.read_bytes() == b"original definition\n"
    assert after_save_called is False


def test_after_save_failure_propagates_after_definition_is_saved(tmp_path):
    config = _config(tmp_path)
    output = tmp_path / "from-config" / "demo.def"

    def after_save(context):
        raise RuntimeError("after-save failure")

    with pytest.raises(RuntimeError, match="after-save failure"):
        generate_workflow(
            config,
            suite_builder=_build_suite,
            after_save=after_save,
        )

    assert "suite demo" in output.read_text(encoding="utf-8")


@pytest.mark.parametrize("return_path", [True, False], ids=["path", "none"])
def test_shell_only_invokes_renderer(tmp_path, monkeypatch, return_path):
    config = _config(tmp_path, "shell")
    selected_output = tmp_path / "shell-output"
    resources = tmp_path / "resources"
    rendered_path = selected_output / "workflow" / "run.sh"
    renderer_calls = []

    def unexpected(*args, **kwargs):
        raise AssertionError("definition generation must not run in shell mode")

    def renderer(received_config, output_repo_base, workflow_repo_base):
        renderer_calls.append(
            (received_config, output_repo_base, workflow_repo_base)
        )
        assert received_config.output_repo_base_dir == str(selected_output)
        if not return_path:
            return None
        rendered_path.parent.mkdir(parents=True)
        rendered_path.write_text("#!/bin/sh\n", encoding="utf-8")
        return rendered_path

    monkeypatch.setattr(generation, "WorkflowEngine", unexpected)
    monkeypatch.setattr(generation, "_get_backend_class", unexpected)
    result = generate_workflow(
        config,
        output_repo_base=selected_output,
        output=tmp_path / "unused.def",
        workflow_repo_base=resources,
        suite_builder=unexpected,
        shell_renderer=renderer,
        before_save=unexpected,
        after_save=unexpected,
    )

    assert renderer_calls == [(config, selected_output, resources)]
    assert result.mode == "shell"
    assert result.output_repo_base == selected_output
    assert result.output_path == (rendered_path if return_path else None)
    assert result.suite is None
    assert not (tmp_path / "unused.def").exists()


@pytest.mark.skipif(
    importlib.util.find_spec("takler") is not None,
    reason="takler is installed",
)
def test_missing_takler_dependency_is_not_wrapped(tmp_path):
    config = _config(tmp_path, "takler")

    with pytest.raises(ImportError, match="TaklerBackend requires"):
        generate_workflow(config, suite_builder=_build_suite)
