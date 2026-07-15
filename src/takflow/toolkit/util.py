"""Generic toolkit utilities for workflow generation.

This module re-exports the engine-agnostic runtime helpers that live in
``takflow.backends.runtime`` so that toolkit users have a single import point.
"""
from takflow.backends.runtime import (
    common_setting,
    script_cmd_var_name,
    script_cmd_value,
    set_scheduling,
    shell_job,
)

__all__ = [
    "common_setting",
    "script_cmd_var_name",
    "script_cmd_value",
    "set_scheduling",
    "shell_job",
]
