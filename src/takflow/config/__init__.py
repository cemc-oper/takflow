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
from takflow.config.workflow import BaseWorkflowConfig, ObservabilityConfig, load_config_from_file
from takflow.config.validation import (
    apply_config_overrides,
    load_config_data,
    ConfigDiagnostic,
    ConfigValidationError,
    load_validated_config,
    validate_config,
    validation_diagnostics,
)

__all__ = [
    "BaseWorkload",
    "ShellWorkload",
    "SlurmWorkload",
    "WorkloadType",
    "SchedulingConfig",
    "CycleConfig",
    "HousekeepConfig",
    "BaseWorkflowConfig",
    "ObservabilityConfig",
    "load_config_from_file",
    "ConfigDiagnostic",
    "ConfigValidationError",
    "load_validated_config",
    "load_config_data",
    "apply_config_overrides",
    "validate_config",
    "validation_diagnostics",
    "FortranBool",
    "fortran_variables",
    "flag_variables",
]
