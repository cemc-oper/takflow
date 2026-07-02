"""Generic runtime helpers for workflow engines.

Provides engine-agnostic runtime configuration, scheduling setup, and the
carrier-specific job submission command generation (``orvix`` vs ``slsubmit6``).

This module intentionally stays app-agnostic: it knows about the generic
``WorkloadType``/``SchedulingConfig`` and ``TaskResource`` (the jobspec
high-level model), but not about MCV/GFS/MESO domain configs.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Optional, Union

if TYPE_CHECKING:
    from takflow.config import SchedulingConfig, WorkloadType
    from takflow.engine import Node, WorkflowEngine
    from takflow.jobspec import TaskResource


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


def orvix_job(engine: "WorkflowEngine", scheduler: str) -> Dict[str, str]:
    """Return the ``orvix`` carrier submission/kill commands.

    The actual resource requirements live inside the script as ``#ORVIX``
    directives, rendered separately by ``render_resource_block``.
    """
    if _is_ecflow(engine):
        return {
            "ECF_JOB_CMD": (
                f"orvix submit --scheduler %ORVIX_SCHEDULER% %ECF_JOB%"
            ),
            "ECF_KILL_CMD": "orvix kill %ECF_JOB%.info.yaml",
            "ORVIX_SCHEDULER": scheduler,
        }
    # takler
    return {
        "TAKLER_SHELL_JOB_CMD": f"orvix submit --scheduler {scheduler} {{ TAKLER_JOB }}",
        "TAKLER_SHELL_KILL_CMD": "orvix kill {{ TAKLER_JOB }}.info.yaml",
        "ORVIX_SCHEDULER": scheduler,
    }


def slsubmit6_serial_job(
    engine: "WorkflowEngine",
    class_name: Optional[str] = None,
    wckey: Optional[str] = None,
) -> Dict[str, str]:
    """Return slsubmit6 carrier serial job variables/commands."""
    if _is_ecflow(engine):
        params = {
            "ECF_JOB_CMD": (
                "slsubmit6 %ECF_JOB% %ECF_NAME% %ECF_TRIES% "
                "%ECF_TRYNO% %ECF_HOST% %ECF_PORT%"
            ),
            "ECF_KILL_CMD": (
                "slcancel4 %ECF_RID% %ECF_NAME% %ECF_HOST% %ECF_PORT%"
            ),
        }
    else:
        params = {
            "TAKLER_SHELL_JOB_CMD": "sbatch {{ TAKLER_JOB }}",
            "TAKLER_SHELL_KILL_CMD": "scancel {{ TAKLER_RID }}",
        }
    if class_name is not None:
        params["PARTITION"] = class_name
    if wckey is not None:
        params["WCKEY"] = wckey
    return params


def slsubmit6_parallel_job(
    engine: "WorkflowEngine",
    nodes: Union[int, str],
    tasks_per_node: Union[int, str],
    class_name: Optional[str] = None,
    wckey: Optional[str] = None,
) -> Dict[str, str]:
    """Return slsubmit6 carrier parallel job variables/commands."""
    if _is_ecflow(engine):
        params = {
            "ECF_JOB_CMD": (
                "slsubmit6 %ECF_JOB% %ECF_NAME% %ECF_TRIES% "
                "%ECF_TRYNO% %ECF_HOST% %ECF_PORT%"
            ),
            "ECF_KILL_CMD": (
                "slcancel4 %ECF_RID% %ECF_NAME% %ECF_HOST% %ECF_PORT%"
            ),
        }
    else:
        params = {
            "TAKLER_SHELL_JOB_CMD": "sbatch {{ TAKLER_JOB }}",
            "TAKLER_SHELL_KILL_CMD": "scancel {{ TAKLER_RID }}",
        }
    params["NODES"] = str(nodes)
    params["TASKS_PER_NODE"] = str(tasks_per_node)
    if class_name is not None:
        params["PARTITION"] = class_name
    if wckey is not None:
        params["WCKEY"] = wckey
    return params


# ---------------------------------------------------------------------------
# set_runtime
# ---------------------------------------------------------------------------

def set_runtime(
    node: "Node",
    workload_config: "WorkloadType",
    engine: "WorkflowEngine",
    task_resource: Optional["TaskResource"] = None,
):
    """Configure runtime/submission variables on ``node``.

    Parameters
    ----------
    node
        The engine node (suite/family/task).
    workload_config
        The generic workload config (SlurmWorkload/ShellWorkload).
    engine
        The workflow engine.
    task_resource
        Optional task-level resource description. Required for slurm carriers;
        for the ``orvix`` carrier its directives are rendered into the job
        script separately, while for ``slsubmit6`` it is flattened to ecFlow
        variables here.
    """
    if workload_config.workload_type == "shell":
        node.add_variables(shell_job(engine))
        return

    if workload_config.workload_type != "slurm":
        raise ValueError(f"workload type is not supported: {workload_config}")

    # From here workload_config is a SlurmWorkload: submit_carrier/scheduler are
    # declared fields, no getattr fallback needed.
    carrier = workload_config.submit_carrier

    if carrier == "orvix":
        scheduler = workload_config.scheduler or "slurm"
        node.add_variables(orvix_job(engine, scheduler))
        return

    if carrier != "slsubmit6":
        raise ValueError(f"submit carrier is not supported: {carrier}")

    # slsubmit6 carrier: flatten TaskResource to legacy %CLASS%/%NODES% vars.
    wckey = workload_config.wckey
    if task_resource is None:
        node.add_variables(
            slsubmit6_serial_job(
                engine,
                class_name=workload_config.default_serial_queue,
                wckey=wckey,
            )
        )
        return

    # Resolve queue (mcv still calls it partition in its own config).
    queue = task_resource.queue
    if queue is None:
        if task_resource.job_type == "parallel":
            queue = workload_config.default_parallel_queue
        else:
            queue = workload_config.default_serial_queue

    if task_resource.job_type == "serial":
        node.add_variables(
            slsubmit6_serial_job(engine, class_name=queue, wckey=wckey)
        )
    elif task_resource.job_type == "parallel":
        node.add_variables(
            slsubmit6_parallel_job(
                engine,
                nodes=task_resource.nodes or 1,
                tasks_per_node=task_resource.ntasks_per_node or 1,
                class_name=queue,
                wckey=wckey,
            )
        )
    else:
        raise ValueError(
            f"job type for slurm is not supported: {task_resource.job_type}"
        )


__all__ = [
    "common_setting",
    "script_cmd_var_name",
    "script_cmd_value",
    "set_runtime",
    "set_scheduling",
    "shell_job",
    "orvix_job",
    "slsubmit6_serial_job",
    "slsubmit6_parallel_job",
]
