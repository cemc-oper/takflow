"""Runtime carrier adapters: translate generic resource models to scheduler-specific runtime variables.

Supported carriers:
- ``orvix``: writes ``#ORVIX`` directives into scripts, sets orvix submit/kill commands.
- ``slsubmit6``: sets ecFlow variables ``%QUEUE%``/``%NODES%``/``%WCKEY%`` and slsubmit6 commands.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict

from takflow.backends.runtime.orvix import set_runtime as set_orvix_runtime
from takflow.backends.runtime.slsubmit import set_runtime as set_slsubmit_runtime

if TYPE_CHECKING:
    from takflow.config import SchedulingConfig, WorkloadType
    from takflow.flow import Node, WorkflowEngine


def _is_ecflow(engine: "WorkflowEngine") -> bool:
    """Return True if the engine backend is ecflow."""
    return engine.backend_type == "ecflow"


# ---------------------------------------------------------------------------
# Script command variables
# ---------------------------------------------------------------------------


def script_cmd_var_name(engine: "WorkflowEngine") -> str:
    """Return the variable name used to point a task at its script.

    ecflow uses ``ECF_SCRIPT_CMD``; takler uses ``TAKLER_SCRIPT``.
    """
    return "ECF_SCRIPT_CMD" if _is_ecflow(engine) else "TAKLER_SCRIPT"


def script_cmd_value(
    engine: "WorkflowEngine", jobs_dir, relative_path: str
) -> str:
    """Return the value for ``script_cmd_var_name``.

    ecflow mode returns ``cat {jobs_dir}/{relative_path}`` because ecflow
    embeds the script via ``%include``. takler mode returns the absolute path
    to the ``.sh`` script.
    """
    from pathlib import Path

    if _is_ecflow(engine):
        return f"cat {jobs_dir}/{relative_path}"
    relative_sh = relative_path.replace(".ecf", ".sh")
    return str(Path(jobs_dir) / relative_sh)


# ---------------------------------------------------------------------------
# Common settings
# ---------------------------------------------------------------------------


def common_setting(engine: "WorkflowEngine") -> Dict[str, str]:
    """Return engine-common settings attached to suites."""
    if _is_ecflow(engine):
        return {
            "ECF_TRIES": "2",
            "ECF_TIMEOUT": "600",
            "ECF_DENIED": "1",
            "ECF_MICRO": "%",
            "ECF_EXTN": ".ecf",
            "ECF_STATUS_CMD": "ps --sid %ECF_RID% -f",
        }
    return {}


def set_scheduling(
    node: "Node",
    scheduling_config: "SchedulingConfig",
    engine: "WorkflowEngine",
    repeat_date_variable_name: str = "YMD",
):
    """Attach scheduling (RepeatDate/RepeatDay) to a node."""
    scheduling_type = getattr(scheduling_config, "scheduling_type", None)
    if scheduling_type == "RepeatDate":
        node.add_repeat_date(
            repeat_date_variable_name,
            scheduling_config.start_date,
            scheduling_config.end_date,
        )
    elif scheduling_type == "RepeatDay":
        node.add_repeat_day(1)
    else:
        raise ValueError(f"scheduler type is not supported: {scheduling_type}")


# ---------------------------------------------------------------------------
# Carrier-aware job submission commands
# ---------------------------------------------------------------------------


def shell_job(engine: "WorkflowEngine") -> Dict[str, str]:
    """Return shell-mode job submission/kill commands."""
    if _is_ecflow(engine):
        return {
            "ECF_JOB_CMD": "%ECF_JOB% 1> %ECF_JOBOUT% 2>&1",
            "ECF_KILL_CMD": "kill -15 %ECF_RID%",
        }
    from takler.tasks.shell.constant import (
        DEFAULT_TAKLER_SHELL_JOB_CMD,
        DEFAULT_TAKLER_SHELL_KILL_CMD,
    )

    return {
        "TAKLER_SHELL_JOB_CMD": DEFAULT_TAKLER_SHELL_JOB_CMD,
        "TAKLER_SHELL_KILL_CMD": DEFAULT_TAKLER_SHELL_KILL_CMD,
    }


def set_runtime(
    node: "Node",
    workload_config: "WorkloadType",
    engine: "WorkflowEngine",
    task_resource=None,
):
    """Configure runtime/submission variables on ``node``.

    Dispatches to the carrier-specific implementation based on
    ``workload_config.submit_carrier``.
    """
    if workload_config.workload_type == "shell":
        node.add_variables(shell_job(engine))
        return

    if workload_config.workload_type != "slurm":
        raise ValueError(f"workload type is not supported: {workload_config}")

    carrier = workload_config.submit_carrier

    if carrier == "orvix":
        set_orvix_runtime(node, workload_config, engine, task_resource)
    elif carrier == "slsubmit6":
        set_slsubmit_runtime(node, workload_config, engine, task_resource)
    else:
        raise ValueError(f"submit carrier is not supported: {carrier}")


__all__ = [
    "common_setting",
    "script_cmd_var_name",
    "script_cmd_value",
    "set_runtime",
    "set_scheduling",
    "shell_job",
]
