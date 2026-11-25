"""Apply workflow scheduling configuration to engine nodes."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from takflow.config import SchedulingConfig
    from takflow.flow.node import Node, WorkflowEngine


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


__all__ = ["set_scheduling"]
