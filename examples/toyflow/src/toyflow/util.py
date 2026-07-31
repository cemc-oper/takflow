"""toyflow 目录解析辅助函数。

资源目录优先级：CLI 参数 > 配置字段 > 包内 resources/；
输出目录优先级：CLI 参数 > 配置字段 > 报错。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from toyflow.config import ToyflowConfig


def get_resources_path() -> Path:
    """返回 toyflow 包内 resources/ 目录。"""
    return Path(__file__).parent / "resources"


def get_workflow_repo_base_dir(
    config: ToyflowConfig,
    workflow_repo_base_dir: Optional[Union[Path, str]] = None,
) -> Path:
    """解析资源模板目录：CLI 参数 > 配置字段 > 包内 resources/。"""
    if workflow_repo_base_dir is not None:
        return Path(workflow_repo_base_dir)
    if config.workflow_repo_base_dir is not None:
        return Path(config.workflow_repo_base_dir)
    return get_resources_path()


def get_output_repo_base_dir(
    config: ToyflowConfig,
    output_repo_base_dir: Optional[Union[Path, str]] = None,
) -> Path:
    """解析输出目录：CLI 参数 > 配置字段 > 报错。"""
    if output_repo_base_dir is not None:
        return Path(output_repo_base_dir)
    if config.output_repo_base_dir is not None:
        return Path(config.output_repo_base_dir)
    raise ValueError(
        "output_repo_base_dir is not set. "
        "Please set it in the config file or pass --output-repo-base on the command line."
    )
