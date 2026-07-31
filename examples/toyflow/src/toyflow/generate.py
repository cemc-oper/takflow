"""toyflow 生成步骤的实现（config generate / workflow generate）。

``resource copy`` 和 ``job generate`` 直接用 ``takflow.toolkit`` 的现成函数，
这里只实现 takflow 刻意留给应用的两步：配置文件渲染和工作流定义生成。
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Optional, Union

from jinja2 import Environment, FileSystemLoader

from takflow.build_info import get_build_info, get_build_info_lines
from takflow.flow import WorkflowEngine
from takflow.backends.ecflow import EcflowBackend
from takflow.backends.takler import TaklerBackend

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


_BACKEND_MAP = {
    "ecflow": EcflowBackend,
    "takler": TaklerBackend,
}

_DEFAULT_SUFFIX = {
    "ecflow": ".def",
    "takler": ".json",
}


def generate_workflow(
    config: ToyflowConfig,
    output_repo_base: Optional[Union[str, Path]] = None,
) -> Path:
    """根据 ``workflow_mode`` 生成工作流定义文件（ecflow .def / takler .json）。

    定义文件写入输出仓库根目录，返回其路径。
    """
    resolved_output_repo_base = get_output_repo_base_dir(config, output_repo_base)
    config.output_repo_base_dir = str(resolved_output_repo_base)

    mode = config.workflow_mode
    backend_cls = _BACKEND_MAP.get(mode)
    if backend_cls is None:
        raise ValueError(f"Unsupported workflow_mode: {mode}")

    engine = WorkflowEngine(backend_cls())
    suite = create_suite(config, engine=engine)

    output_path = Path(resolved_output_repo_base, f"{config.workflow_name}{_DEFAULT_SUFFIX[mode]}")
    engine.save_suite(suite, output_path)
    return output_path
