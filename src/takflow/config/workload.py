"""Generic workload models.

The app-agnostic workload description: which scheduler family a workflow targets
and its global defaults. App configs embed one of these as ``WorkloadType``.

This is the subset ``TaskResource`` (``takflow.jobspec.highlevel``) needs in
Phase 0; the full config base lands in a later phase.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field


class BaseWorkload(BaseModel):
    """Common base for all workload kinds."""

    workload_type: Literal["slurm", "shell"]


class ShellWorkload(BaseWorkload):
    """Plain-shell workload: tasks run directly, no batch scheduler."""

    workload_type: Literal["shell"] = "shell"


class SlurmWorkload(BaseWorkload):
    """Slurm (or orvix-translated) workload with global defaults.

    Note the canonical key is ``queue`` (orvix vocabulary), not ``partition``.
    """

    workload_type: Literal["slurm"] = "slurm"
    wckey: str
    default_serial_queue: str = "serial"
    default_parallel_queue: str = "normal"
    #: Optional application label (-> slurm --comment), e.g. "op_grapes_gfs".
    application: Optional[str] = None


WorkloadType = Annotated[
    Union[SlurmWorkload, ShellWorkload],
    Field(discriminator="workload_type"),
]

__all__ = [
    "BaseWorkload",
    "ShellWorkload",
    "SlurmWorkload",
    "WorkloadType",
]
