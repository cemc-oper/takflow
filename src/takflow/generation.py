"""Application-neutral orchestration for workflow generation.

Applications retain their configuration models, suite builders, shell renderers,
and CLI. This module centralizes only mode dispatch, output path resolution, and
definition save ordering.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from takflow.backends.ecflow import EcflowBackend
from takflow.checks import (
    GenerationCheckReport,
    check_definition_output,
    check_output_path,
    check_relative_path,
    check_shell_output,
    check_workflow_structure,
    preflight_generation,
)
from takflow.config import BaseWorkflowConfig
from takflow.flow import Node, WorkflowBackend, WorkflowEngine


@dataclass(frozen=True)
class GenerationContext:
    """Resolved state passed to definition save callbacks."""

    config: BaseWorkflowConfig
    engine: WorkflowEngine
    suite: Node
    output_repo_base: Path
    output_path: Path


@dataclass(frozen=True)
class GenerationResult:
    """Result of definition or application-provided shell generation."""

    mode: str
    output_repo_base: Path
    output_path: Path | None
    suite: Node | None


def _get_backend_class(mode: str) -> type[WorkflowBackend]:
    if mode == "ecflow":
        return EcflowBackend
    if mode == "takler":
        from takflow.backends.takler import TaklerBackend

        return TaklerBackend
    raise ValueError(f"Unsupported workflow_mode: {mode}")


def _resolve_output_repo_base(
    config: BaseWorkflowConfig,
    output_repo_base: str | Path | None,
) -> Path:
    value = (
        output_repo_base
        if output_repo_base is not None
        else config.output_repo_base_dir
    )
    if value is None:
        raise ValueError(
            "output_repo_base_dir is not set. "
            "Please set it in the config file or pass --output-repo-base on the command line."
        )
    resolved = Path(value)
    config.output_repo_base_dir = str(resolved)
    return resolved


def _file_state(path: Path):
    try:
        metadata = path.stat()
        return (metadata.st_dev, metadata.st_ino, metadata.st_size,
                metadata.st_mtime_ns, metadata.st_ctime_ns)
    except OSError:
        return None


def _record_failed_output(report, path, previous, stage):
    """Best-effort failure evidence must never replace the original exception."""
    try:
        if not path.is_file():
            report.artifacts[:] = [item for item in report.artifacts if item["path"] != str(path)]
        elif _file_state(path) != previous:
            report.artifact(path, "definition_partial", stage=stage)
    except Exception:
        report.unchecked("GEN_PARTIAL_OUTPUT_UNREADABLE", stage, str(path),
                         "failed output remains on disk but its current metadata could not be collected")


def generate_workflow(
    config: BaseWorkflowConfig,
    *,
    output_repo_base: str | Path | None = None,
    output: str | Path | None = None,
    workflow_repo_base: str | Path | None = None,
    suite_builder: Callable[
        [BaseWorkflowConfig, WorkflowEngine], Node
    ] | None = None,
    shell_renderer: Callable[
        [BaseWorkflowConfig, Path, str | Path | None], Path | None
    ] | None = None,
    before_save: Callable[[GenerationContext], None] | None = None,
    after_save: Callable[[GenerationContext], None] | None = None,
    required_operations: tuple[str, ...] = (),
    check_report: GenerationCheckReport | None = None,
) -> GenerationResult:
    """Generate a definition or invoke an application's shell renderer.

    Definition output defaults to ``<output_repo>/<workflow_name>.def`` for
    ecFlow and ``.json`` for takler. An explicit ``output`` is used as supplied.
    Definition callbacks run immediately before and after ``save_suite``.

    Shell mode does not create an engine or backend. Its renderer owns the
    output path and all application-specific rendering behavior.
    """
    report = preflight_generation(config, required_operations=required_operations, check_report=check_report)
    mode = config.workflow_mode
    if mode == "shell":
        if shell_renderer is None:
            report.fail("GEN_RENDERER_REQUIRED", "generation.preflight", "shell_renderer",
                        "shell_renderer is required for shell workflow generation")
        resolved_output_repo_base = _resolve_output_repo_base(config, output_repo_base)
        output_path = shell_renderer(
            config, resolved_output_repo_base, workflow_repo_base
        )
        if output_path is not None:
            check_shell_output(output_path, check_report=report, stage="workflow.output", role="shell_runner")
        else:
            report.unchecked("GEN_OUTPUT_UNKNOWN", "workflow.output", "shell_renderer",
                             "legacy renderer returned None; no output path is available for postchecks")
        return GenerationResult(
            mode=mode,
            output_repo_base=resolved_output_repo_base,
            output_path=output_path,
            suite=None,
        )

    backend_cls = _get_backend_class(mode)
    if suite_builder is None:
        report.fail("GEN_BUILDER_REQUIRED", "generation.preflight", "suite_builder",
                    "suite_builder is required for ecflow/takler workflow generation")
    resolved_output_repo_base = _resolve_output_repo_base(config, output_repo_base)
    suffix = ".def" if mode == "ecflow" else ".json"
    output_path = (
        Path(output)
        if output is not None
        else check_relative_path(resolved_output_repo_base, f"{config.workflow_name}{suffix}",
                                 stage="definition.preflight", report=report, object="workflow_name")
    )
    check_output_path(output_path, stage="definition.preflight", report=report)

    engine = WorkflowEngine(backend_cls())
    suite = suite_builder(config, engine)
    check_workflow_structure(suite, engine=engine, check_report=report)
    context = GenerationContext(
        config=config,
        engine=engine,
        suite=suite,
        output_repo_base=resolved_output_repo_base,
        output_path=output_path,
    )
    if before_save is not None:
        before_save(context)
        check_workflow_structure(suite, engine=engine, check_report=report)
    before_write = _file_state(output_path)
    try:
        engine.save_suite(suite, output_path)
    except Exception:
        report.failed("GEN_SAVE_FAILED", "definition.save", str(output_path),
                         "save failed; any partial output is retained and no rollback is attempted")
        _record_failed_output(report, output_path, before_write, "definition.save")
        raise
    report.artifact(output_path, "definition", stage="definition.save")
    if after_save is not None:
        before_callback = _file_state(output_path)
        try:
            after_save(context)
        except Exception:
            report.failed("GEN_AFTER_SAVE_FAILED", "definition.output", str(output_path),
                             "callback failed after save; output may have changed and remains unqualified")
            _record_failed_output(report, output_path, before_callback, "definition.output")
            raise
    check_definition_output(suite, output_path, check_report=report)

    return GenerationResult(
        mode=mode,
        output_repo_base=resolved_output_repo_base,
        output_path=output_path,
        suite=suite,
    )


__all__ = ["GenerationContext", "GenerationResult", "generate_workflow"]
