"""Bind job submission commands and resource declarations to workflow nodes."""
from __future__ import annotations

from typing import TYPE_CHECKING

from . import direct, orvix, slsubmit6, variables

if TYPE_CHECKING:
    from takflow.config import WorkloadType
    from takflow.flow import Node, WorkflowEngine
    from takflow.jobspec import TaskResource


def set_runtime(
    node: Node,
    workload_config: WorkloadType,
    engine: WorkflowEngine,
    task_resource: TaskResource | None = None,
) -> None:
    """Configure runtime/submission variables on ``node``.

    With no task_resource, install the carrier at this scope (including an
    intentional carrier switch). A Slurm task_resource selects job resources
    under that carrier. Use set_resource_variables for local declarations
    that also inherit the parent queue, including in a parallel family.
    """
    if workload_config.workload_type == "shell":
        carrier = getattr(workload_config, "submit_carrier", "direct")
        if carrier == "orvix":
            node.add_variables(orvix.orvix_job(engine, "local"))
        elif carrier == "direct":
            node.add_variables(direct.shell_job(engine))
        else:
            raise ValueError(f"shell workload does not support submit carrier: {carrier}")
        return

    if workload_config.workload_type != "slurm":
        raise ValueError(f"workload type is not supported: {workload_config}")

    carrier = workload_config.submit_carrier
    if carrier == "orvix":
        commands = orvix.orvix_job(engine, workload_config.scheduler or "slurm")
    elif carrier == "slsubmit6":
        commands = slsubmit6.slsubmit6_serial_job(engine)
    else:
        raise ValueError(f"submit carrier is not supported: {carrier}")
    variables.configure_slurm_node(node, workload_config, task_resource, commands)


__all__ = ["set_runtime"]
