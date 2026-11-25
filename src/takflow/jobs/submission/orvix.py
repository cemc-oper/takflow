"""Submission and cancellation commands for the orvix carrier."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from takflow.flow import WorkflowEngine


def orvix_job(engine: WorkflowEngine, scheduler: str) -> dict[str, str]:
    """Return the ``orvix`` carrier submission/kill commands.

    The actual resource requirements live inside the script as ``#ORVIX``
    directives.
    """
    if engine.backend_type == "ecflow":
        return {
            "ECF_JOB_CMD": 'orvix submit --scheduler "%ORVIX_SCHEDULER%" "%ECF_JOB%"',
            "ECF_KILL_CMD": 'orvix kill "%ECF_JOB%.info.yaml"',
            "ORVIX_SCHEDULER": scheduler,
        }
    # takler
    return {
        "TAKLER_SHELL_JOB_CMD": "orvix submit --scheduler {{ ORVIX_SCHEDULER | shquote }} {{ TAKLER_JOB | shquote }}",
        "TAKLER_SHELL_KILL_CMD": 'orvix kill {{ (TAKLER_JOB ~ ".info.yaml") | shquote }}',
        "ORVIX_SCHEDULER": scheduler,
    }


__all__ = ["orvix_job"]
