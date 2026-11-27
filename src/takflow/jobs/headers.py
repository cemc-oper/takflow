"""Render resource headers for job and configuration templates."""
from __future__ import annotations

import warnings
from typing import Optional, Union

from jinja2 import pass_context

from takflow.config import SlurmWorkload
from takflow.config.workload import RESOURCE_ALIAS_HINTS, ResourceAliasWarning, resolve_resource_alias
from takflow.jobs.provenance import ecflow_include
from takflow.jobs.submission.variables import RESOURCE_VARIABLES, ecflow_log_value
from takflow.jobspec import CANONICAL_KEYS, ResourceSpec, TaskResource
from takflow.jobspec.render import orvix_directive, slurm_directive


def _job_resource_spec(
    job_type="serial", *, queue=None, nodes=None, ntasks_per_node=None, time=None,
    memory=None, requeue=None, job_name=None, output=None, error=None,
    project=None, application=None, scheduler="slurm", exclusive=None,
) -> ResourceSpec:
    task = TaskResource(job_type=job_type, queue=queue, nodes=nodes, ntasks_per_node=ntasks_per_node,
                        time=time, memory=memory, requeue=requeue, job_name=job_name, output=output, error=error)
    workload = None if scheduler == "local" else SlurmWorkload(project=project or "", application=application)
    fields = task.compile(workload).model_dump()
    fields.update(scheduler=scheduler, project=project, application=application, exclusive=exclusive)
    return ResourceSpec(**fields)


def _ecflow_optional_line(variable: str, line: str, default_line: str | None = None) -> str:
    """Select a header line during native job creation.

    Inside %comment ecFlow tolerates a missing reference. Only a successful
    substitution unescapes %%end and %%comment before comment removal.
    """
    ref = f"%{variable}%"
    # Resolve a supplied value outside %comment too, so a broken reference in
    # its value fails job creation. Resetting the delimiter emits no job text.
    lines = [f"%%ecfmicro %% %{variable}:%", "%comment", f"%%end {ref}", line, f"%%comment {ref}"]
    if default_line is not None:
        # When the override resolved, keep the same comment open across the
        # default by temporarily changing its closing delimiter. Restore %
        # before the next job line. No scalar is interpreted as a directive.
        lines.extend((f"%%ecfmicro @ {ref}", "%end", default_line, "%comment", "@ecfmicro %"))
    lines.append("%end")
    return "\n".join(lines)


def _resource_directive(field: str, variable: str, fallback, mode: str, native_slurm: bool) -> str:
    key = field.replace("_", "-")
    prefix = f"#ORVIX {key}="
    if isinstance(fallback, bool):
        fallback = str(fallback).lower()
    if mode == "ecflow":
        if field == "requeue" and (native_slurm or fallback is None):
            fragment = "requeue" if native_slurm else "orvix-requeue"
            return ecflow_include(f"<common/{fragment}-%{variable}:{fallback or 'unset'}%.h>")
        ref = f"%{variable}%" if fallback is None else f"%{variable}:{fallback}%"
        if native_slurm:
            line = slurm_directive(field, ref, engine_reference=True)
        elif field == "job_name" or (fallback is not None and any(c.isspace() for c in str(fallback))):
            line = f'{prefix}"{ref}"'
        else:
            line = prefix + ref
        return _ecflow_optional_line(variable, line) if fallback is None else line
    else:
        expression = variable
        if fallback is not None:
            expression += f" | default({str(fallback)!r})"
        if field == "requeue":
            expression += " | lower"
        ref = "{{ " + expression + " }}"
        if fallback is None:
            if field == "job_name":
                ref = '"' + ref + '"'
            return ("{% if " + variable + " is defined and " + variable + " is not none %}"
                    + prefix + ref + "{% endif %}")
    if field == "job_name" or (fallback is not None and any(c.isspace() for c in str(fallback))):
        ref = '"' + ref + '"'
    return prefix + ref


def _engine_log_directive(field: str, fallback: str | None, mode: str, native_slurm: bool) -> str:
    """Keep the engine's job log expression available until job creation."""
    variable = RESOURCE_VARIABLES[field]
    if mode == "ecflow":
        def log_line(value):
            if native_slurm:
                return slurm_directive(field, value, engine_reference=True)
            return f'#ORVIX {field}="{value}"'

        if fallback is not None and "%" not in fallback:
            return log_line(f"%{variable}:{fallback}%")
        default = log_line(ecflow_log_value(fallback)) if fallback is not None else None
        return _ecflow_optional_line(variable, log_line(f"%{variable}%"), default)
    path = variable + ' | replace("{{ TAKLER_JOBOUT }}", TAKLER_JOBOUT | default(""))'
    line = f'#ORVIX {field}="{{{{ {path} }}}}"'
    default = f'{{% else %}}#ORVIX {field}="{fallback}"' if fallback is not None else ""
    return f"{{% if {variable} is defined and {variable} is not none %}}{line}{default}{{% endif %}}"


def _workflow_resource_block(spec: ResourceSpec, mode: str | None, job_type: str, *, native_slurm=False) -> str:
    if native_slurm and mode == "takler":
        raise ValueError("native Slurm resource headers support ecFlow and Shell")
    engine = mode in ("ecflow", "takler")
    lines = []
    for field in CANONICAL_KEYS:
        value = getattr(spec, field)
        if engine and field in ("output", "error"):
            lines.append(_engine_log_directive(field, value, mode, native_slurm))
            continue
        if engine and field in RESOURCE_VARIABLES:
            if job_type != "serial" or field not in ("nodes", "ntasks_per_node"):
                lines.append(_resource_directive(field, RESOURCE_VARIABLES[field], value, mode, native_slurm))
            continue
        if value is None:
            continue
        if native_slurm:
            line = slurm_directive(field, value, engine_reference=engine)
        elif field == "scheduler":
            line = f"#ORVIX scheduler={value}"
        else:
            line = orvix_directive(field, value)
        if line:
            lines.append(line)
    return "\n".join(lines)


def render_orvix_resource_block(
    job_type: str = "serial",
    queue: Optional[str] = None,
    partition: Optional[str] = None,
    nodes: Optional[Union[int, str]] = None,
    ntasks_per_node: Optional[Union[int, str]] = None,
    time: Optional[str] = None,
    walltime: Optional[str] = None,
    memory: Optional[str] = None,
    output: Optional[str] = None,
    error: Optional[str] = None,
    project: Optional[str] = None,
    wckey: Optional[str] = None,
    application: Optional[str] = None,
    scheduler: str = "slurm",
    requeue: Optional[bool] = None,
    workflow_mode: Optional[str] = None,
    *, job_name: str | None = None, exclusive: bool | str | None = None,
) -> str:
    """Render ORVIX directives with the existing optional input aliases."""
    spec = _job_resource_spec(
        job_type, queue=resolve_resource_alias("queue", queue, "partition", partition, nonblank=True),
        time=resolve_resource_alias("time", time, "walltime", walltime, nonblank=True),
        project=resolve_resource_alias("project", project, "wckey", wckey), nodes=nodes,
        ntasks_per_node=ntasks_per_node, memory=memory, output=output, error=error,
        application=application, scheduler=scheduler, requeue=requeue, job_name=job_name, exclusive=exclusive,
    )
    block = _workflow_resource_block(spec, workflow_mode, job_type)
    for name, value in (("partition", partition), ("walltime", walltime), ("wckey", wckey)):
        if value is not None:
            warnings.warn(RESOURCE_ALIAS_HINTS[f"render_orvix_resource_block.{name}"], ResourceAliasWarning, stacklevel=2)
    return block


def render_slurm_resource_block(*, job_type="serial", workflow_mode=None, **resources) -> str:
    """Render the supported native Slurm header fields using canonical input names."""
    return _workflow_resource_block(_job_resource_spec(job_type, **resources), workflow_mode, job_type,
                                    native_slurm=True)


def _workflow_resource_defaults(context, resources):
    config = context["config"]
    workload = config.workload
    job_type = resources.get("job_type", "serial")
    if resources.get("queue") is None and resources.get("partition") is None:
        resources["queue"] = getattr(workload, f"default_{job_type}_queue", None)
    if resources.get("project") is None and resources.get("wckey") is None:
        resources["project"] = getattr(workload, "project", None)
    if resources.get("application") is None:
        resources["application"] = getattr(workload, "application", None)
    resources.setdefault("scheduler", getattr(workload, "scheduler", "local"))
    for field, name in (("output", "output_std_log_path"), ("error", "output_stderr_log_path")):
        if resources.get(field) is None:
            resources[field] = context.get(name)
    resources["workflow_mode"] = config.workflow_mode
    return resources


@pass_context
def _render_workflow_orvix_resource_block(context, **resources) -> str:
    return render_orvix_resource_block(**_workflow_resource_defaults(context, resources))


@pass_context
def _render_workflow_slurm_resource_block(context, **resources) -> str:
    return render_slurm_resource_block(**_workflow_resource_defaults(context, resources))


RESOURCE_TEMPLATE_HELPERS = {
    "render_orvix_resource_block": _render_workflow_orvix_resource_block,
    "render_slurm_resource_block": _render_workflow_slurm_resource_block,
}


__all__ = ["RESOURCE_TEMPLATE_HELPERS", "render_orvix_resource_block", "render_slurm_resource_block"]
