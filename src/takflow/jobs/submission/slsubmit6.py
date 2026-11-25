"""slsubmit6 carrier: flatten resources to ecFlow variables and slsubmit6 commands."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .variables import RESOURCE_VARIABLES

if TYPE_CHECKING:
    from takflow.flow import WorkflowEngine


def slsubmit6_serial_job(
    engine: WorkflowEngine,
    class_name: str | None = None,
    wckey: str | None = None,
) -> dict[str, str]:
    """Return slsubmit6 carrier serial job variables/commands."""
    if engine.backend_type != "ecflow":
        raise ValueError(f"{engine.backend_type} does not support slsubmit6. Use orvix for scheduled jobs.")
    params = {
        "ECF_JOB_CMD": 'slsubmit6 "%ECF_JOB%" "%ECF_NAME%" "%ECF_TRIES%" "%ECF_TRYNO%" "%ECF_HOST%" "%ECF_PORT%"',
        "ECF_KILL_CMD": 'slcancel4 "%ECF_RID%" "%ECF_NAME%" "%ECF_HOST%" "%ECF_PORT%"',
    }
    if class_name is not None:
        params[RESOURCE_VARIABLES["queue"]] = class_name
    if wckey is not None:
        params[RESOURCE_VARIABLES["project"]] = wckey
    return params


def slsubmit6_parallel_job(
    engine: WorkflowEngine,
    nodes: int | str,
    tasks_per_node: int | str,
    class_name: str | None = None,
    wckey: str | None = None,
) -> dict[str, str]:
    """Return slsubmit6 carrier parallel job variables/commands."""
    params = slsubmit6_serial_job(engine, class_name, wckey)
    params[RESOURCE_VARIABLES["nodes"]] = str(nodes)
    params[RESOURCE_VARIABLES["ntasks_per_node"]] = str(tasks_per_node)
    return params


__all__ = [
    "slsubmit6_serial_job",
    "slsubmit6_parallel_job",
]
