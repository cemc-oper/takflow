"""slsubmit6 carrier: flatten resources to ecFlow variables and slsubmit6 commands."""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Optional, Union

if TYPE_CHECKING:
    from takflow.config import WorkloadType
    from takflow.flow import Node, WorkflowEngine
    from takflow.jobspec import TaskResource


def _is_ecflow(engine: "WorkflowEngine") -> bool:
    return engine.backend_type == "ecflow"


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
        params["QUEUE"] = class_name
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
        params["QUEUE"] = class_name
    if wckey is not None:
        params["WCKEY"] = wckey
    return params


def set_runtime(
    node: "Node",
    workload_config: "WorkloadType",
    engine: "WorkflowEngine",
    task_resource: Optional["TaskResource"] = None,
):
    """Configure the slsubmit6 carrier on ``node``."""
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
    "slsubmit6_serial_job",
    "slsubmit6_parallel_job",
    "set_runtime",
]
