"""toyflow 生成步骤的实现（config generate / workflow generate）。

``resource copy`` 和 ``job generate`` 使用 ``takflow.toolkit``，工作流生成
编排使用 ``takflow.generation``；这里保留应用自己的配置渲染和 manifest 回调。
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Optional, Union

from jinja2 import Environment, FileSystemLoader

from takflow.build_info import get_build_info, get_build_info_lines
from takflow.generation import generate_workflow as generate_workflow_service
from takflow.toolkit.observability import (
    ObservabilityConfigError,
    TaskMapping,
    export_definition_manifest,
    write_definition_manifest,
)
import takflow

import toyflow
from toyflow.config import ToyflowConfig
from toyflow.flow import create_suite
from toyflow.util import get_output_repo_base_dir, get_workflow_repo_base_dir


def toyflow_build_info_lines() -> dict[str, str]:
    """toyflow 品牌的生成文件头（注入给 takflow.toolkit.job）。"""
    return get_build_info_lines(get_build_info(toyflow.__version__), "toyflow")


def render_config(
    config: ToyflowConfig,
    workflow_repo_base: Optional[Union[str, Path]] = None,
    output_repo_base: Optional[Union[str, Path]] = None,
) -> Path:
    """渲染配置文件：shell/takler 模式生成 ``config.sh``，ecflow 模式生成 ``config.h``。"""
    workflow_repo_base = get_workflow_repo_base_dir(config, workflow_repo_base)
    output_repo_base = get_output_repo_base_dir(config, output_repo_base)

    env = Environment(loader=FileSystemLoader(str(workflow_repo_base)), lstrip_blocks=True)
    template = env.get_template("config/config.sh.j2")

    build_info_lines = toyflow_build_info_lines()
    rendered = template.render(
        config=config,
        build_info_warning=build_info_lines["warning"],
        build_info_detail=build_info_lines["info"],
    )

    output_file_name = "config.h" if config.workflow_mode == "ecflow" else "config.sh"
    output_file_path = Path(output_repo_base, "config", output_file_name)
    output_file_path.parent.mkdir(exist_ok=True, parents=True)
    output_file_path.write_text(rendered)

    mode = os.stat(output_file_path).st_mode
    os.chmod(output_file_path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return output_file_path


def _reject_shell(config: ToyflowConfig, *_args) -> None:
    """toyflow remains definition-only; retain its historical shell error."""
    raise ValueError(f"Unsupported workflow_mode: {config.workflow_mode}")


def _task_mappings(suite, config: ToyflowConfig) -> list[TaskMapping]:
    """Toyflow owns these keys; they are independent of the engine path API."""
    from takflow.flow import NodeType

    mappings = []

    def visit(node, relative: str = "") -> None:
        for child in node.children:
            path = f"{relative}/{child.name}" if relative else child.name
            if child.node_type is NodeType.TASK:
                if path == "admin/toggles":
                    key, stage, dependencies, params = "admin.toggles", "control", (), {}
                elif path.startswith("time_triggers/") and path.split("/", 1)[1] in (config.cycles or {}):
                    key, stage, dependencies, params = (
                        f"time_triggers.{child.name}", "control", (), {}
                    )
                elif path == "obs/prepare":
                    key, stage, dependencies, params = "obs.prepare", "prepare", (), {}
                elif path == "main/forecast":
                    key, stage, dependencies, params = (
                        "main.forecast", "forecast",
                        ("obs.prepare",) if config.enable_obs else (),
                        {"member": {"type": "string", "required": True},
                         "lead_seconds": {"type": "integer", "required": True}},
                    )
                elif path == "main/verify":
                    key, stage, dependencies, params = "main.verify", "verify", ("main.forecast",), {}
                elif path == "post/plot":
                    key, stage, dependencies, params = (
                        "post.plot", "post",
                        ("main.forecast",) if config.enable_main else (), {}
                    )
                else:
                    raise ObservabilityConfigError(f"toyflow has no stable key for {path}")
                mappings.append(TaskMapping(child, key, stage, stage,
                                            params, dependencies))
            visit(child, path)

    visit(suite)
    return mappings


def generate_workflow(
    config: ToyflowConfig,
    output_repo_base: Optional[Union[str, Path]] = None,
) -> Path:
    """根据 ``workflow_mode`` 生成工作流定义文件（ecflow .def / takler .json）。

    定义文件写入输出仓库根目录，返回其路径。通用编排由 takflow 提供，
    toyflow 只保留 suite builder 和可选 manifest 的保存前后回调。
    """
    manifest = None

    def before_save(context) -> None:
        nonlocal manifest
        manifest = export_definition_manifest(
            context.suite,
            _task_mappings(context.suite, config) if config.observability.enabled else (),
            observability=config.observability,
            application_revision=config.observability.application_revision or "",
            config_revision=config.observability.config_revision or "",
            mapping_version="toyflow-1",
            generator_version=takflow.__version__,
            script_invoke_mode=config.script_invoke_mode,
        )

    def after_save(context) -> None:
        if manifest is not None:
            write_definition_manifest(
                context.output_repo_base / "definition_manifest.json", manifest
            )

    result = generate_workflow_service(
        config,
        output_repo_base=output_repo_base,
        suite_builder=create_suite,
        shell_renderer=_reject_shell,
        before_save=before_save,
        after_save=after_save,
    )
    assert result.output_path is not None
    return result.output_path
