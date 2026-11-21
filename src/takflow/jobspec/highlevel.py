"""``TaskResource`` — the app-friendly high-level resource model.

Domain configs keep speaking ``serial``/``parallel`` (defaults pulled from the
global :class:`~takflow.config.workload.SlurmWorkload`); ``compile()`` flattens
that to a :class:`~takflow.jobspec.model.ResourceSpec`.

NAMING COLLISION (important): ``TaskResource.job_type`` is a takflow *selector*
(serial/parallel) that chooses the default queue and whether to set
``nodes``/``ntasks_per_node``. It is **not** orvix's ``job-type`` directive
(e.g. donau ``cosched``). ``compile()`` never emits it as a directive.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Literal, Optional

from pydantic import BaseModel, WrapValidator, field_validator
from pydantic_core import PydanticCustomError

from takflow.config.workload import SlurmWorkload, nonblank_resource_text
from takflow.jobspec.model import ResourceSpec


class TaskResource(BaseModel):
    """High-level, app-facing resource description (replaces SlurmTaskConfig)."""

    job_type: Literal["serial", "parallel"] = "serial"
    queue: Optional[str] = None
    nodes: Optional[int] = None
    ntasks_per_node: Optional[int] = None
    time: Optional[str] = None
    memory: Optional[str] = None
    #: None leaves the requeue policy to an applicable default or parent.
    requeue: Optional[bool] = None

    _validate_resource_text = field_validator("queue", "time", "memory")(nonblank_resource_text)

    @field_validator("nodes", "ntasks_per_node")
    @classmethod
    def _check_positive_count(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value <= 0:
            raise PydanticCustomError(
                "resource_positive", "must be a positive integer or None",
            )
        return value

    def compile(self, workload: SlurmWorkload) -> ResourceSpec:
        """Compile this high-level resource against a slurm workload.

        Resolves the queue from ``job_type`` defaults when not set explicitly,
        and threads the global project and application labels.
        """
        if self.queue is not None:
            queue = self.queue
        elif self.job_type == "parallel":
            queue = workload.default_parallel_queue
        else:
            queue = workload.default_serial_queue

        spec = ResourceSpec(
            scheduler="slurm",
            queue=queue,
            project=workload.project,
            application=workload.application,
            time=self.time,
            memory=self.memory,
            requeue=self.requeue,
        )
        if self.job_type == "parallel":
            if self.nodes is not None:
                spec.nodes = str(self.nodes)
            if self.ntasks_per_node is not None:
                spec.ntasks_per_node = str(self.ntasks_per_node)
        # NOTE: self.job_type (serial/parallel) is deliberately NOT mapped to
        # ResourceSpec.job_type (the orvix directive).
        return spec


def task_resource_defaults(factory: Callable[[], TaskResource]) -> WrapValidator:
    """Apply an application's defaults to a raw, partial task workload mapping."""
    def resolve(raw, validate):
        resource = validate(raw)
        if not isinstance(raw, Mapping):
            return resource

        defaults = factory()
        values = defaults.model_dump(exclude_none=True)
        if raw.get("job_type", defaults.job_type) != defaults.job_type:
            for field in ("queue", "nodes", "ntasks_per_node"):
                values.pop(field, None)
        updates = {field: value for field, value in values.items() if raw.get(field) is None}
        if not updates:
            return resource
        effective = resource.model_copy(update=updates)
        effective.model_fields_set.intersection_update(resource.model_fields_set)
        return effective

    return WrapValidator(resolve)


__all__ = ["TaskResource", "task_resource_defaults"]
