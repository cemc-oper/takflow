"""Direct execution of a workflow engine's job script."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from takflow.flow import WorkflowEngine


def shell_job(engine: WorkflowEngine) -> dict[str, str]:
    """Return the direct submission and cancellation commands for the engine."""
    if engine.backend_type == "ecflow":
        return {
            "ECF_JOB_CMD": '"%ECF_JOB%" 1> "%ECF_JOBOUT%" 2>&1',
            "ECF_KILL_CMD": "kill -15 %ECF_RID%",
        }
    from takler.tasks.shell.constant import DEFAULT_TAKLER_SHELL_KILL_CMD

    return {
        "TAKLER_SHELL_JOB_CMD": "{{ TAKLER_JOB | shquote }} 1> {{ TAKLER_JOBOUT | shquote }} 2>&1",
        "TAKLER_SHELL_KILL_CMD": DEFAULT_TAKLER_SHELL_KILL_CMD,
    }


__all__ = ["shell_job"]
