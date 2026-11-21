"""Resource declarations at a single workflow node, independently of its carrier."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING

from takflow.flow import NodeType
from takflow.jobspec import TaskResource
from takflow.jobspec.render import slurm_directive

if TYPE_CHECKING:
    from takflow.config import SlurmWorkload
    from takflow.flow import Node

RESOURCE_VARIABLES = {
    "job_name": "JOB_NAME",
    "output": "JOB_OUTPUT",
    "error": "JOB_ERROR",
    "nodes": "NODES",
    "ntasks_per_node": "TASKS_PER_NODE",
    "time": "WALLTIME",
    "queue": "QUEUE",
    "project": "WCKEY",
    "application": "APPLICATION",
    "memory": "MEMORY",
    "requeue": "REQUEUE",
}

# Do not consume the next placeholder's opening percent in %A_%a or %j%j.
_ECFLOW_LOG_TOKEN = re.compile(r"(%(?![aAbBJjNnstuXx]_*%)[A-Za-z_][A-Za-z0-9_]*(?::[^%]*)?%)|%")


def ecflow_log_value(value: str) -> str:
    """Keep named ecFlow references and pass Slurm filename patterns through job creation."""
    return _ECFLOW_LOG_TOKEN.sub(lambda match: match[1] or "%%", value)


def ecflow_resource_variables(
    variables: Mapping[str, str | int | float | bool | None],
) -> dict[str, str | int | float | bool]:
    """Encode node edits for ecFlow, including optional whole-line directives.

    The returned edits also work with native ecflow.Node.add_variable(dict)
    when introducing an optional field on an already loaded definition.
    """
    edits = {name: value for name, value in variables.items() if value is not None}
    for field, variable in RESOURCE_VARIABLES.items():
        if variable not in edits:
            continue
        if field == "requeue":
            if isinstance(edits[variable], bool):
                edits[variable] = str(edits[variable]).lower()
        else:
            key = field.replace("_", "-")
            reference = f"%{variable}%"
            if field in ("output", "error"):
                if f"{variable}_PREFIX" not in variables:
                    edits[variable] = ecflow_log_value(str(edits[variable]))
                # A log fallback may itself contain %ECF_JOBOUT%. Keep it out
                # of a nested %VAR:default% and comment it when an override exists.
                edits[f"{variable}_PREFIX"] = "##"
            if field in ("output", "error", "job_name"):
                reference = f'"{reference}"'
            edits.setdefault(f"ORVIX_{variable}", f"#ORVIX {key}={reference}")
            edits.setdefault(f"SLURM_{variable}", slurm_directive(field, f"%{variable}%", engine_reference=True))
    return edits


def set_resource_variables(
    node: Node, resource: TaskResource, *, project: str | None = None,
    application: str | None = None,
) -> None:
    """Declare the supplied values here. Omitted values remain inheritable.

    Pass a local declaration, not the result of compiling a task against its
    workload. The caller chooses the scope, including equal-valued overrides.
    """
    values = resource.model_dump(include=set(RESOURCE_VARIABLES), exclude_none=True)
    if resource.job_type == "serial":
        values.pop("nodes", None)
        values.pop("ntasks_per_node", None)
    values.update(project=project, application=application)
    node.add_variables({RESOURCE_VARIABLES[field]: value for field, value in values.items()
                        if value is not None})


def configure_slurm_node(node: Node, workload: SlurmWorkload, resource: TaskResource | None,
                         commands: dict[str, str]) -> None:
    """Install a carrier at its scope, or declare resources for an inherited job."""
    if resource is None or node.node_type == NodeType.SUITE:
        node.add_variables(commands)
        set_resource_variables(node, TaskResource(queue=workload.default_serial_queue),
                               project=workload.project, application=workload.application)
    if resource is None:
        return

    # The combined job-type API selects the parallel queue on a mixed suite.
    # A homogeneous family can use set_resource_variables at either level.
    if resource.job_type == "parallel" and resource.queue is None:
        resource = resource.model_copy(update={"queue": workload.default_parallel_queue})
    set_resource_variables(node, resource)
