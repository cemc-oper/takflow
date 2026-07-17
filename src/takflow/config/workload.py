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
    """Plain-shell workload: tasks run directly, no batch scheduler.

    ``submit_carrier`` selects how host-local tasks reach execution:
    ``"direct"`` (default) runs the script straight from the engine,
    ``"orvix"`` submits through the orvix ``local`` backend so submission,
    kill and status go through the same path as scheduled jobs.
    """

    workload_type: Literal["shell"] = "shell"
    submit_carrier: Literal["orvix", "direct"] = "direct"

    @classmethod
    def for_suite(cls, suite_workload: "WorkloadType") -> "ShellWorkload":
        """Derive the local-task workload from the suite workload.

        A suite submitted via the ``orvix`` carrier gets orvix-carried local
        tasks; every other suite keeps direct local execution.
        """
        carrier = getattr(suite_workload, "submit_carrier", None)
        return cls(submit_carrier="orvix" if carrier == "orvix" else "direct")


class SlurmWorkload(BaseWorkload):
    """Slurm (or orvix-translated) workload with global defaults.

    Note the canonical key is ``queue`` (orvix vocabulary), not ``partition``.

    ``submit_carrier`` selects how job resources reach the scheduler:
    ``"orvix"`` writes ``#ORVIX`` directives + ``orvix submit`` job command,
    ``"slsubmit6"`` keeps the legacy ``%QUEUE%``/``%NODES%`` ecFlow variables +
    ``slsubmit6``. ``scheduler`` is the orvix target family. Apps subclass this
    and override the defaults (mcv defaults to ``orvix``; gfs/meso will default
    to ``slsubmit6``).
    """

    workload_type: Literal["slurm"] = "slurm"
    wckey: str
    scheduler: Literal["slurm", "donau"] = "slurm"
    submit_carrier: Literal["orvix", "slsubmit6"] = "orvix"
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
