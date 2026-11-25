"""Common workflow engine settings, script commands, and scheduling."""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict

if TYPE_CHECKING:
    from takflow.config import SchedulingConfig
    from takflow.flow import Node, WorkflowEngine


def _is_ecflow(engine: "WorkflowEngine") -> bool:
    """Return True if the engine backend is ecflow."""
    return engine.backend_type == "ecflow"


# ---------------------------------------------------------------------------
# Script command variables
# ---------------------------------------------------------------------------


def script_cmd_var_name(engine: "WorkflowEngine") -> str:
    """Return the variable name used to point a task at its script.

    ecflow uses ``ECF_SCRIPT_CMD``; takler uses ``TAKLER_SCRIPT``.
    """
    return "ECF_SCRIPT_CMD" if _is_ecflow(engine) else "TAKLER_SCRIPT"


def script_cmd_value(
    engine: "WorkflowEngine", jobs_dir, relative_path: str
) -> str:
    """Return the value for ``script_cmd_var_name``.

    ecflow mode returns ``cat {jobs_dir}/{relative_path}`` because ecflow
    embeds the script via ``%include``. takler mode returns the absolute path
    to the ``.sh`` script.
    """
    from pathlib import Path

    if _is_ecflow(engine):
        import shlex
        return "cat " + shlex.quote(f"{jobs_dir}/{relative_path}")
    relative_sh = relative_path.replace(".ecf", ".sh")
    return str(Path(jobs_dir) / relative_sh)


# ---------------------------------------------------------------------------
# Common settings
# ---------------------------------------------------------------------------


def common_setting(engine: "WorkflowEngine") -> Dict[str, str]:
    """Return engine-common settings attached to suites."""
    if _is_ecflow(engine):
        return {
            "ECF_TRIES": "2",
            "ECF_TIMEOUT": "600",
            "ECF_DENIED": "1",
            "ECF_MICRO": "%",
            "ECF_EXTN": ".ecf",
            "ECF_STATUS_CMD": "ps --sid %ECF_RID% -f",
        }
    return {}


def set_scheduling(
    node: "Node",
    scheduling_config: "SchedulingConfig",
    engine: "WorkflowEngine",
    repeat_date_variable_name: str = "YMD",
):
    """Attach scheduling (RepeatDate/RepeatDay) to a node."""
    scheduling_type = getattr(scheduling_config, "scheduling_type", None)
    if scheduling_type == "RepeatDate":
        node.add_repeat_date(
            repeat_date_variable_name,
            scheduling_config.start_date,
            scheduling_config.end_date,
        )
    elif scheduling_type == "RepeatDay":
        node.add_repeat_day(1)
    else:
        raise ValueError(f"scheduler type is not supported: {scheduling_type}")


__all__ = [
    "common_setting",
    "script_cmd_var_name",
    "script_cmd_value",
    "set_scheduling",
]
