"""takflow jobspec layer — the job-run resource description contract in Python.

- :class:`ResourceSpec` — flat, 1:1 with the canonical schema and orvix keys.
- :class:`TaskResource` — app-friendly high-level model that compiles to it.
- :func:`to_orvix_directives` — render ``#ORVIX`` directive lines.
"""
from takflow.jobspec.model import CANONICAL_KEYS, ResourceSpec
from takflow.jobspec.highlevel import TaskResource
from takflow.jobspec.render import (
    MARKER,
    render_resource_block,
    to_orvix_directives,
)

__all__ = [
    "ResourceSpec",
    "CANONICAL_KEYS",
    "TaskResource",
    "to_orvix_directives",
    "render_resource_block",
    "MARKER",
]
