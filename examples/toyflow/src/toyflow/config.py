"""toyflow 配置模型。

演示 takflow 配置层的标准用法：子类化 ``BaseWorkflowConfig``，
只添加领域字段，通用字段（目录、模式、workload、调度）全部继承。
"""
from __future__ import annotations

from pydantic import BaseModel

from takflow.config import BaseWorkflowConfig, load_config_from_file
from takflow.jobspec import TaskResource


class ForecastConfig(BaseModel):
    """预报步骤的领域配置。"""

    #: 预报时长（小时）。
    forecast_length: int = 24
    #: 预报任务的资源需求（serial/parallel 高层模型，生成时编译为 #ORVIX 指令）。
    resource: TaskResource = TaskResource(job_type="parallel", nodes=2, ntasks_per_node=16)


class ToyflowConfig(BaseWorkflowConfig):
    """toyflow 工作流配置。

    继承自 takflow 的 ``BaseWorkflowConfig``，通用字段（``project_base_dir``、
    ``run_base_dir``、``workflow_mode``、``workload``、``scheduling`` 等）
    无需重复定义，这里只声明玩具预报系统的领域字段。
    """

    #: 功能开关：观测预处理 / 预报 / 后处理。
    enable_obs: bool = True
    enable_main: bool = True
    enable_post: bool = True

    forecast: ForecastConfig = ForecastConfig()

    #: 后处理任务的资源需求。
    post_resource: TaskResource = TaskResource(job_type="serial")


__all__ = ["ForecastConfig", "ToyflowConfig", "load_config_from_file"]
