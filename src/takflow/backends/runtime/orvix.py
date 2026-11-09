"""ORVIX carrier: render resources as ``#ORVIX`` directives and set orvix commands."""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict

from takflow.jobspec.render import (
    MARKER,
    render_resource_block,
    to_orvix_directives,
)

if TYPE_CHECKING:
    from takflow.config import WorkloadType
    from takflow.flow import Node, WorkflowEngine
    from takflow.jobspec import TaskResource


def _is_ecflow(engine: "WorkflowEngine") -> bool:
    return engine.backend_type == "ecflow"


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
        "TAKLER_SHELL_JOB_CMD": f"orvix submit --scheduler {scheduler} {{{{ TAKLER_JOB | shquote }}}}",
        "TAKLER_SHELL_KILL_CMD": 'orvix kill {{ (TAKLER_JOB ~ ".info.yaml") | shquote }}',
        "ORVIX_SCHEDULER": scheduler,
    }


def set_runtime(
    node: "Node",
    workload_config: "WorkloadType",
    engine: "WorkflowEngine",
    task_resource: "TaskResource | None" = None,
):
    """Configure the orvix carrier on ``node``.

    ecFlow scripts reference QUEUE, WCKEY and APPLICATION at preprocessing time.
    Set global defaults when no task resource is supplied; resource-specific
    nodes override only QUEUE so project and application remain inherited.
    """
    scheduler = workload_config.scheduler or "slurm"
    node.add_variables(orvix_job(engine, scheduler))
    if _is_ecflow(engine):
        if task_resource is None:
            node.add_variables({
                "QUEUE": workload_config.default_serial_queue,
                "WCKEY": workload_config.wckey,
            })
            if workload_config.application is not None:
                node.add_variable("APPLICATION", workload_config.application)
        else:
            node.add_variable("QUEUE", task_resource.compile(workload_config).queue)


__all__ = [
    "MARKER",
    "to_orvix_directives",
    "render_resource_block",
    "orvix_job",
    "set_runtime",
]
