"""Generic workload models.

The app-agnostic workload description: which scheduler family a workflow targets
and its global defaults. App configs embed one of these as ``WorkloadType``.

This is the subset ``TaskResource`` (``takflow.jobspec.highlevel``) needs in
Phase 0; the full config base lands in a later phase.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal, Optional, Union
import warnings

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError


class ResourceAliasWarning(FutureWarning):
    """Migration notice for a legacy resource input accepted by takflow."""


RESOURCE_ALIAS_HINTS = {
    old: f"{old} is deprecated. Use {new}. No removal version or date has been set."
    for old, new in (
        ("workload.wckey", "workload.project"),
        ("render_orvix_resource_block.partition", "queue"),
        ("render_orvix_resource_block.walltime", "time"),
        ("render_orvix_resource_block.wckey", "project"),
    )
}


def nonblank_resource_text(value: Optional[str]) -> Optional[str]:
    if value is not None and not value.strip():
        raise PydanticCustomError("resource_blank", "must contain a non-whitespace character")
    return value


def resolve_resource_alias(
    name: str, value: Optional[str], alias: str, legacy: Optional[str], *, nonblank: bool = False,
) -> Optional[str]:
    """Resolve two spellings while both original inputs are still available."""
    if value is not None and legacy is not None:
        if nonblank:
            for spelling, candidate in ((name, value), (alias, legacy)):
                if isinstance(candidate, str) and not candidate.strip():
                    raise PydanticCustomError("resource_blank", f"{spelling} must contain a non-whitespace character")
        raise PydanticCustomError(f"resource_{name}_conflict", f"use only one of {name} and {alias}")
    return value if value is not None else legacy


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
    project: str
    scheduler: Literal["slurm", "donau"] = "slurm"
    submit_carrier: Literal["orvix", "slsubmit6"] = "orvix"
    default_serial_queue: str = "serial"
    default_parallel_queue: str = "normal"
    #: Optional application label (-> slurm --comment), e.g. "op_grapes_gfs".
    application: Optional[str] = None

    _validate_queues = field_validator("default_serial_queue", "default_parallel_queue")(nonblank_resource_text)

    @model_validator(mode="wrap")
    @classmethod
    def _accept_wckey(cls, data, handler):
        if isinstance(data, Mapping) and "wckey" in data:
            values = dict(data)
            legacy = values.pop("wckey")
            values["project"] = resolve_resource_alias("project", values.get("project"), "wckey", legacy)
            workload = handler(values)
            if legacy is not None:
                warnings.warn(RESOURCE_ALIAS_HINTS["workload.wckey"], ResourceAliasWarning, stacklevel=2)
            return workload
        return handler(data)

    @property
    def wckey(self) -> str:
        """Compatibility spelling for the Slurm project label."""
        return self.project

    @wckey.setter
    def wckey(self, value: str) -> None:
        self.project = value


WorkloadType = Annotated[
    Union[SlurmWorkload, ShellWorkload],
    Field(discriminator="workload_type"),
]

__all__ = [
    "BaseWorkload",
    "ShellWorkload",
    "SlurmWorkload",
    "WorkloadType",
    "resolve_resource_alias",
]
