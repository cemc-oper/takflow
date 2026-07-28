"""takflow generic config layer.

- workload models (BaseWorkload / SlurmWorkload / ShellWorkload)
- scheduling / cycle / housekeep models
- BaseWorkflowConfig + generic loader
- field types & variable assembly helpers (FortranBool, fortran/flag_variables)
"""
from takflow.config.types import FortranBool, flag_variables, fortran_variables
from takflow.config.workload import (
    BaseWorkload,
    ShellWorkload,
    SlurmWorkload,
    WorkloadType,
)
from takflow.config.scheduling import (
    CycleConfig,
    HousekeepConfig,
    SchedulingConfig,
)
from takflow.config.workflow import BaseWorkflowConfig, load_config_from_file

__all__ = [
    "BaseWorkload",
    "ShellWorkload",
    "SlurmWorkload",
    "WorkloadType",
    "SchedulingConfig",
    "CycleConfig",
    "HousekeepConfig",
    "BaseWorkflowConfig",
    "load_config_from_file",
    "FortranBool",
    "fortran_variables",
    "flag_variables",
]
