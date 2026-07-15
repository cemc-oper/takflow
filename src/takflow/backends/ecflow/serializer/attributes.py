"""
ecFlow-style attribute objects for the light-ecflow stub.

These classes represent the constructs that can be attached to a node, either
via the method API (``add_trigger(...)``) or via the constructor-style API
(``Task("t1", Trigger("..."))``).
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional, Union


class DState(str, Enum):
    """Default node states supported by ``defstatus``."""

    complete = "complete"
    queued = "queued"
    suspended = "suspended"
    aborted = "aborted"
    active = "active"
    unknown = "unknown"


class Edit:
    """Represents one or more variables attached to a node."""

    def __init__(self, **variables: Any):
        self.variables: Dict[str, Any] = variables

    def __repr__(self) -> str:
        return f"Edit({self.variables!r})"


class Trigger:
    """Represents a trigger expression."""

    def __init__(self, expression: str):
        self.expression = expression

    def to_def(self) -> str:
        return f"trigger {self.expression}"

    def __repr__(self) -> str:
        return f"Trigger({self.expression!r})"


class PartTrigger:
    """Represents a partial trigger expression used with ``add_part_trigger``."""

    def __init__(self, expression: str, and_flag: bool = True):
        self.expression = expression
        self.and_flag = and_flag

    def __repr__(self) -> str:
        return f"PartTrigger({self.expression!r}, and_flag={self.and_flag})"


class Complete:
    """Represents a complete expression."""

    def __init__(self, expression: str):
        self.expression = expression

    def to_def(self) -> str:
        return f"complete {self.expression}"

    def __repr__(self) -> str:
        return f"Complete({self.expression!r})"


class DefStatus:
    """Represents a default node status."""

    def __init__(self, state: Union[DState, str]):
        if isinstance(state, str):
            state = DState(state)
        self.state: DState = state

    def to_def(self) -> str:
        return f"defstatus {self.state.value}"

    def __repr__(self) -> str:
        return f"DefStatus({self.state.value!r})"


class Event:
    """Represents an event attached to a node."""

    def __init__(self, name: str):
        self.name = name

    def to_def(self) -> str:
        return f"event {self.name}"

    def __repr__(self) -> str:
        return f"Event({self.name!r})"


class Meter:
    """Represents a meter attached to a node."""

    def __init__(self, name: str, min_value: int, max_value: int):
        self.name = name
        self.min_value = min_value
        self.max_value = max_value

    def to_def(self) -> str:
        return f"meter {self.name} {self.min_value} {self.max_value}"

    def __repr__(self) -> str:
        return f"Meter({self.name!r}, {self.min_value}, {self.max_value})"


class Limit:
    """Represents a limit attached to a node."""

    def __init__(self, name: str, value: int):
        self.name = name
        self.value = value

    def to_def(self) -> str:
        return f"limit {self.name} {self.value}"

    def __repr__(self) -> str:
        return f"Limit({self.name!r}, {self.value})"


class InLimit:
    """Represents an in-limit attached to a node."""

    def __init__(self, name: str, tokens: int = 1):
        self.name = name
        self.tokens = tokens

    def to_def(self) -> str:
        if self.tokens == 1:
            return f"inlimit {self.name}"
        return f"inlimit {self.name} {self.tokens}"

    def __repr__(self) -> str:
        return f"InLimit({self.name!r}, tokens={self.tokens})"


class Time:
    """Represents a time dependency attached to a node."""

    def __init__(self, time_str: str):
        self.time_str = time_str

    def to_def(self) -> str:
        return f"time {self.time_str}"

    def __repr__(self) -> str:
        return f"Time({self.time_str!r})"


class Late:
    """Represents a "late" monitoring attribute attached to a node.

    Mirrors the native ecFlow ``Late`` object used by GFS/MESO post
    graph builders:

    - ``late.submitted(h, m)``  -> ``late -s HH:MM``
    - ``late.complete(h, m, relative=False)`` -> ``late -c HH:MM``;
      with ``relative=True`` -> ``late -c +HH:MM``.
    - ``late.active(h, m, relative=False)`` -> ``late -a HH:MM`` / ``late -a +HH:MM``.

    Attributes are serialized in the order submitted/active/complete, matching
    native ecFlow output.
    """

    def __init__(self):
        self.submitted_time: Optional[tuple[int, int]] = None
        self.active_time: Optional[tuple[int, int]] = None
        self.complete_time: Optional[tuple[int, int]] = None
        self.complete_relative: bool = False
        self.active_relative: bool = False

    def submitted(self, hours: int, minutes: int) -> "Late":
        self.submitted_time = (hours, minutes)
        return self

    def active(self, hours: int, minutes: int, relative: bool = False) -> "Late":
        self.active_time = (hours, minutes)
        self.active_relative = relative
        return self

    def complete(self, hours: int, minutes: int, relative: bool = False) -> "Late":
        self.complete_time = (hours, minutes)
        self.complete_relative = relative
        return self

    @staticmethod
    def _fmt(value: tuple[int, int]) -> str:
        h, m = value
        return f"{h:02d}:{m:02d}"

    def to_def(self) -> str:
        parts = ["late"]
        if self.submitted_time is not None:
            parts.append(f"-s {self._fmt(self.submitted_time)}")
        if self.active_time is not None:
            prefix = "+" if self.active_relative else ""
            parts.append(f"-a {prefix}{self._fmt(self.active_time)}")
        if self.complete_time is not None:
            prefix = "+" if self.complete_relative else ""
            parts.append(f"-c {prefix}{self._fmt(self.complete_time)}")
        return " ".join(parts)

    def __repr__(self) -> str:
        return f"Late({self.to_def()!r})"


class Repeat:
    """Base class for repeat attributes."""

    def to_def(self) -> str:
        raise NotImplementedError


class RepeatDate(Repeat):
    """Represents a date-based repeat attribute."""

    def __init__(self, name: str, start: int, end: int, step: int = 1):
        self.name = name
        self.start = int(start)
        self.end = int(end)
        self.step = int(step)

    def to_def(self) -> str:
        return f"repeat date {self.name} {self.start} {self.end} {self.step}"

    def __repr__(self) -> str:
        return (
            f"RepeatDate({self.name!r}, {self.start}, {self.end}, step={self.step})"
        )


class RepeatDay(Repeat):
    """Represents a day-based repeat attribute (suite level, tied to clock)."""

    def __init__(self, step: int = 1):
        self.step = int(step)

    def to_def(self) -> str:
        return f"repeat day {self.step}"

    def __repr__(self) -> str:
        return f"RepeatDay({self.step})"


class Clock:
    """
    Represents a suite clock.

    Supports several calling conventions:

    - ``Clock(True)``  -> hybrid clock, no initial date/time.
    - ``Clock(False)`` -> real clock, no initial date/time.
    - ``Clock("hybrid", date_str, time_str)``
    - ``Clock("real", time_str)``
    """

    def __init__(self, *args: Any):
        self.kind: str = "hybrid"
        self.date: Optional[str] = None
        self.time: Optional[str] = None

        if not args:
            return

        first = args[0]
        if isinstance(first, bool):
            self.kind = "hybrid" if first else "real"
            remaining = args[1:]
        elif isinstance(first, str):
            self.kind = first.lower()
            remaining = args[1:]
        else:
            raise TypeError(f"Unexpected Clock argument type: {type(first)}")

        if len(remaining) == 1:
            self.time = str(remaining[0])
        elif len(remaining) == 2:
            self.date = str(remaining[0])
            self.time = str(remaining[1])
        elif len(remaining) > 2:
            raise TypeError(f"Clock accepts at most 3 arguments, got {len(args)}")

    def to_def(self) -> str:
        parts = ["clock", self.kind]
        if self.date:
            parts.append(self.date)
        if self.time:
            parts.append(self.time)
        return " ".join(parts)

    def __repr__(self) -> str:
        return f"Clock({self.to_def()!r})"


def _quote(value: str) -> str:
    """
    Quote a variable value in single quotes, matching the native ecflow output.

    Values containing single quotes are wrapped in double quotes instead.
    """
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    escaped = value.replace("'", "\\'")
    return f"'{escaped}'"
