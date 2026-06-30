"""Generic workflow-config base and loader.

``BaseWorkflowConfig`` holds only the app-agnostic fields. Apps subclass it,
override ``workload`` with their own workload union if needed, and add domain
fields (toggles, component configs).
"""
from __future__ import annotations

from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field

from takflow.config.scheduling import CycleConfig, HousekeepConfig, SchedulingConfig
from takflow.config.workload import WorkloadType


class BaseWorkflowConfig(BaseModel):
    """App-agnostic workflow configuration base.

    Attributes
    ----------
    project_base_dir : str
        Program base directory (model program, static data).
    run_base_dir : str
        Run base directory (copied program, intermediate data, outputs).
    workflow_repo_base_dir : str or None
        Resource directory (scripts and templates). None -> use the app's
        packaged ``resources/`` directory.
    output_repo_base_dir : str or None
        Output directory for the generated workflow.
    workflow_name : str
        Workflow name.
    workflow_mode : str
        ``"shell"`` / ``"ecflow"`` / ``"takler"``.
    script_invoke_mode : str
        ``"external"`` (invoke script files) or ``"inline"`` (embed content).
    workload : WorkloadType
        Workload config (slurm or shell). Apps may override the union type.
    scheduling : SchedulingConfig or None
        Time scheduling; ecFlow mode only.
    cycles : dict[str, CycleConfig] or None
        Forecast cycle configs; ecFlow mode only.
    housekeep : HousekeepConfig or None
        Cleanup config; ecFlow mode only.
    """

    project_base_dir: str
    run_base_dir: str

    workflow_repo_base_dir: Optional[str] = None
    output_repo_base_dir: Optional[str] = None

    workflow_name: str = "workflow"
    workflow_mode: Literal["shell", "ecflow", "takler"] = "shell"
    script_invoke_mode: Literal["external", "inline"] = "external"

    workload: WorkloadType

    scheduling: Optional[SchedulingConfig] = None
    cycles: Optional[dict[str, CycleConfig]] = None
    housekeep: Optional[HousekeepConfig] = None


def load_config_from_file(
    file_path: str,
    config_class: type[BaseWorkflowConfig] = BaseWorkflowConfig,
):
    """Load a workflow config from a YAML file into ``config_class``."""
    with open(file_path, "r") as f:
        yaml_data = yaml.safe_load(f)
    return config_class(**yaml_data)


__all__ = ["BaseWorkflowConfig", "load_config_from_file"]
