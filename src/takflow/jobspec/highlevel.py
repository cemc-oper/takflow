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

from typing import Literal, Optional

from pydantic import BaseModel

from takflow.config.workload import SlurmWorkload
from takflow.jobspec.model import ResourceSpec


class TaskResource(BaseModel):
    """High-level, app-facing resource description (replaces SlurmTaskConfig)."""

    job_type: Literal["serial", "parallel"] = "serial"
    queue: Optional[str] = None
    nodes: Optional[int] = None
    ntasks_per_node: Optional[int] = None
    time: Optional[str] = None
    memory: Optional[str] = None
    #: Whether the scheduler may auto-requeue. None = scheduler default.
    requeue: Optional[bool] = None

    def compile(self, workload: SlurmWorkload) -> ResourceSpec:
        """Compile this high-level resource against a slurm workload.

        Resolves the queue from ``job_type`` defaults when not set explicitly,
        and threads global workload labels (``wckey`` -> project, application).
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
            project=workload.wckey,
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


__all__ = ["TaskResource"]
