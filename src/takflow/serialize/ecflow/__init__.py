"""takflow.serialize.ecflow: pure-Python ecFlow ``.def`` file generator.

Originally ``light_ecflow``; folded into takflow as one serialization backend.
Exposes a small subset of the ecFlow Python API without the C++ dependency.
"""

try:
    from takflow._version import version as __version__
except ImportError:  # pragma: no cover
    __version__ = "unknown"

from .attributes import (
    Clock,
    Complete,
    DState,
    DefStatus,
    Edit,
    Event,
    InLimit,
    Late,
    Limit,
    Meter,
    PartTrigger,
    RepeatDate,
    RepeatDay,
    Time,
    Trigger,
)
from .defs import Defs
from .node import Family, Node, Suite, Task

__all__ = [
    "__version__",
    "Clock",
    "Complete",
    "DState",
    "DefStatus",
    "Defs",
    "Edit",
    "Event",
    "Family",
    "InLimit",
    "Late",
    "Limit",
    "Meter",
    "Node",
    "PartTrigger",
    "RepeatDate",
    "RepeatDay",
    "Suite",
    "Task",
    "Time",
    "Trigger",
]
