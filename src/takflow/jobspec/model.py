"""``ResourceSpec`` — the flat job-run resource description.

Fields are 1:1 with the canonical contract (``spec/jobspec/jobspec.schema.json``)
and with orvix's directive vocabulary. This is the *flat* layer; the app-friendly
``TaskResource`` (``takflow.jobspec.highlevel``) compiles down to it.

Keys are snake_case here and emitted hyphenated as ``#ORVIX`` directives by
``takflow.jobspec.render``.
"""
from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict

#: Render order for ``#ORVIX`` directives. Mirrors orvix's slurm generator order
#: so rendered scripts are deterministic. ``scheduler`` is emitted first because
#: it selects the backend. ``job_type`` here is the orvix scheduler job-type
#: directive (e.g. donau ``cosched``) — NOT the high-level serial/parallel
#: selector on ``TaskResource``.
CANONICAL_KEYS: tuple[str, ...] = (
    "scheduler",
    "job_name",
    "output",
    "error",
    "nodes",
    "ntasks",
    "ntasks_per_node",
    "cpus_per_task",
    "time",
    "queue",
    "account",
    "project",
    "application",
    "exclusive",
    "nodelist",
    "job_type",
    "memory",
    "dependency",
    "requeue",
)


class ResourceSpec(BaseModel):
    """Flat job-run resource description, 1:1 with the jobspec contract."""

    model_config = ConfigDict(extra="forbid")

    scheduler: Literal["slurm", "donau", "local"] = "local"
    job_name: Optional[str] = None
    output: Optional[str] = None
    error: Optional[str] = None
    nodes: Optional[str] = None
    ntasks: Optional[str] = None
    ntasks_per_node: Optional[str] = None
    cpus_per_task: Optional[str] = None
    time: Optional[str] = None
    queue: Optional[str] = None
    account: Optional[str] = None
    project: Optional[str] = None
    application: Optional[str] = None
    exclusive: Optional[Union[bool, str]] = None
    nodelist: Optional[str] = None
    job_type: Optional[str] = None
    memory: Optional[str] = None
    dependency: Optional[str] = None
    requeue: Optional[bool] = None

    def iter_set_fields(self):
        """Yield ``(key, value)`` for fields that are set, in canonical order.

        ``scheduler`` is yielded only when it differs from the default
        ``"local"`` so that an unset scheduler does not pin the script.
        """
        for key in CANONICAL_KEYS:
            value = getattr(self, key)
            if value is None:
                continue
            if key == "scheduler" and value == "local":
                continue
            yield key, value


__all__ = ["ResourceSpec", "CANONICAL_KEYS"]
