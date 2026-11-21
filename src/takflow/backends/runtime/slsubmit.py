"""slsubmit6 carrier: flatten resources to ecFlow variables and slsubmit6 commands."""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Optional, Union

from takflow.backends.runtime.resources import configure_slurm_node

if TYPE_CHECKING:
    from takflow.config import WorkloadType
    from takflow.flow import Node, WorkflowEngine
    from takflow.jobspec import TaskResource


def slsubmit6_serial_job(
    engine: "WorkflowEngine",
    class_name: Optional[str] = None,
    wckey: Optional[str] = None,
) -> Dict[str, str]:
    """Return slsubmit6 carrier serial job variables/commands."""
    if engine.backend_type != "ecflow":
        raise ValueError(f"{engine.backend_type} does not support slsubmit6. Use orvix for scheduled jobs.")
    params = {
        "ECF_JOB_CMD": 'slsubmit6 "%ECF_JOB%" "%ECF_NAME%" "%ECF_TRIES%" "%ECF_TRYNO%" "%ECF_HOST%" "%ECF_PORT%"',
        "ECF_KILL_CMD": 'slcancel4 "%ECF_RID%" "%ECF_NAME%" "%ECF_HOST%" "%ECF_PORT%"',
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
    params = slsubmit6_serial_job(engine, class_name, wckey)
    params["NODES"] = str(nodes)
    params["TASKS_PER_NODE"] = str(tasks_per_node)
    return params


def set_runtime(
    node: "Node",
    workload_config: "WorkloadType",
    engine: "WorkflowEngine",
    task_resource: Optional["TaskResource"] = None,
):
    """Install the carrier or declare a job's resources under its existing scope."""
    configure_slurm_node(node, workload_config, task_resource, slsubmit6_serial_job(engine))


__all__ = [
    "slsubmit6_serial_job",
    "slsubmit6_parallel_job",
    "set_runtime",
]
