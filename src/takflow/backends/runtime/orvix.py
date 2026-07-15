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
        "TAKLER_SHELL_JOB_CMD": f"orvix submit --scheduler {scheduler} {{ TAKLER_JOB }}",
        "TAKLER_SHELL_KILL_CMD": "orvix kill {{ TAKLER_JOB }}.info.yaml",
        "ORVIX_SCHEDULER": scheduler,
    }


def set_runtime(
    node: "Node",
    workload_config: "WorkloadType",
    engine: "WorkflowEngine",
    task_resource=None,
):
    """Configure the orvix carrier on ``node``.

    ``task_resource`` is accepted for signature compatibility but ignored here:
    orvix resources are rendered into the job script separately.
    """
    scheduler = workload_config.scheduler or "slurm"
    node.add_variables(orvix_job(engine, scheduler))


__all__ = [
    "MARKER",
    "to_orvix_directives",
    "render_resource_block",
    "orvix_job",
    "set_runtime",
]
