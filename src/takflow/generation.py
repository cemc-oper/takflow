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
) -> GenerationResult:
    """Generate a definition or invoke an application's shell renderer.

    Definition output defaults to ``<output_repo>/<workflow_name>.def`` for
    ecFlow and ``.json`` for takler. An explicit ``output`` is used as supplied.
    Definition callbacks run immediately before and after ``save_suite``.

    Shell mode does not create an engine or backend. Its renderer owns the
    output path and all application-specific rendering behavior.
    """
    mode = config.workflow_mode
    if mode == "shell":
        if shell_renderer is None:
            raise ValueError("shell_renderer is required for shell workflow generation")
        resolved_output_repo_base = _resolve_output_repo_base(config, output_repo_base)
        output_path = shell_renderer(
            config, resolved_output_repo_base, workflow_repo_base
        )
        return GenerationResult(
            mode=mode,
            output_repo_base=resolved_output_repo_base,
            output_path=output_path,
            suite=None,
        )

    backend_cls = _get_backend_class(mode)
    if suite_builder is None:
        raise ValueError(
            "suite_builder is required for ecflow/takler workflow generation"
        )
    resolved_output_repo_base = _resolve_output_repo_base(config, output_repo_base)
    suffix = ".def" if mode == "ecflow" else ".json"
    output_path = (
        Path(output)
        if output is not None
        else resolved_output_repo_base / f"{config.workflow_name}{suffix}"
    )

    engine = WorkflowEngine(backend_cls())
    suite = suite_builder(config, engine)
    context = GenerationContext(
        config=config,
        engine=engine,
        suite=suite,
        output_repo_base=resolved_output_repo_base,
        output_path=output_path,
    )
    if before_save is not None:
        before_save(context)
    engine.save_suite(suite, output_path)
    if after_save is not None:
        after_save(context)

    return GenerationResult(
        mode=mode,
        output_repo_base=resolved_output_repo_base,
        output_path=output_path,
        suite=suite,
    )


__all__ = ["GenerationContext", "GenerationResult", "generate_workflow"]
