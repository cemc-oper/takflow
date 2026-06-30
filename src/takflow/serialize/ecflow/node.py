"""
Node classes that mimic ``ecflow.Suite``, ``ecflow.Family`` and ``ecflow.Task``.
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional, Union

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
    Repeat,
    Time,
    Trigger,
    _quote,
)


class Node:
    """
    Base class for ``Suite``, ``Family`` and ``Task``.

    Provides the ecflow-style method API for building a node tree and attaching
    attributes. It also supports constructor-style attributes (``Edit``,
    ``Trigger``, ``Complete``, etc.) via ``*children``.

    Each node is responsible for rendering its own ``.def`` text via
    ``to_def(level)``. The top-level ``Defs`` object walks the tree and joins
    the lines.
    """

    INDENT = " " * 2
    _keyword = ""

    def __init__(self, name: str, *children: Any):
        self._name = name
        self._parent: Optional[Node] = None
        self._children: List[Node] = []

        self._variables: Dict[str, str] = {}
        self._trigger: Optional[str] = None
        self._completes: List[Complete] = []
        self._events: List[Event] = []
        self._meters: List[Meter] = []
        self._limits: List[Limit] = []
        self._inlimits: List[InLimit] = []
        self._repeats: List[Repeat] = []
        self._times: List[Time] = []
        self._lates: List[Late] = []
        self._clock: Optional[Clock] = None
        self._defstatus: Optional[DState] = None

        for child in children:
            self._add_child_object(child)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    def name(self) -> str:
        """Return the node name."""
        return self._name

    def get_abs_node_path(self) -> str:
        """Return the absolute ecFlow-style path, e.g. ``/suite/family/task``."""
        if self._parent is None:
            return f"/{self._name}"
        return f"{self._parent.get_abs_node_path()}/{self._name}"

    @property
    def nodes(self) -> List[Node]:
        """Return the direct child nodes."""
        return list(self._children)

    @property
    def parent(self) -> Optional[Node]:
        """Return the parent node."""
        return self._parent

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self._name!r})"

    # ------------------------------------------------------------------
    # Tree construction
    # ------------------------------------------------------------------
    def _add_child_object(self, child: Any) -> None:
        """Dispatch a constructor-style child object to the right handler."""
        if isinstance(child, (list, tuple)):
            for item in child:
                self._add_child_object(item)
            return

        if isinstance(child, Suite):
            raise TypeError("Suite cannot be nested inside another node")
        if isinstance(child, Family):
            self.add_family(child)
        elif isinstance(child, Task):
            self.add_task(child)
        elif isinstance(child, Edit):
            self.add_variable(child.variables)
        elif isinstance(child, Trigger):
            self.add_trigger(child.expression)
        elif isinstance(child, PartTrigger):
            self.add_part_trigger(child.expression, child.and_flag)
        elif isinstance(child, Complete):
            self.add_complete(child.expression)
        elif isinstance(child, DState):
            self.add_defstatus(child)
        elif isinstance(child, DefStatus):
            self.add_defstatus(child.state)
        elif isinstance(child, Event):
            self.add_event(child.name)
        elif isinstance(child, Meter):
            self.add_meter(child.name, child.min_value, child.max_value)
        elif isinstance(child, Limit):
            self.add_limit(child.name, child.value)
        elif isinstance(child, InLimit):
            self.add_inlimit(child.name, child.tokens)
        elif isinstance(child, Repeat):
            self.add_repeat(child)
        elif isinstance(child, Clock):
            self.add_clock(child)
        elif isinstance(child, Time):
            self.add_time(child.time_str)
        elif isinstance(child, Late):
            self.add_late(child)
        else:
            raise TypeError(f"Unsupported child type for {self.__class__.__name__}: {type(child)}")

    def add_family(self, family: Family) -> Family:
        """Mount a ``Family`` child node."""
        if not isinstance(family, Family):
            raise TypeError(f"Expected Family, got {type(family)}")
        family._parent = self
        self._children.append(family)
        return family

    def add_task(self, task: Task) -> Task:
        """Mount a ``Task`` child node."""
        if not isinstance(task, Task):
            raise TypeError(f"Expected Task, got {type(task)}")
        task._parent = self
        self._children.append(task)
        return task

    # ------------------------------------------------------------------
    # Attribute API
    # ------------------------------------------------------------------
    def add_variable(
        self,
        name_or_dict: Union[str, Dict[str, Any]],
        value: Any = None,
    ) -> Node:
        """
        Add one or more variables.

        Supports both ``add_variable("NAME", "value")`` and
        ``add_variable({"NAME": "value"})``.
        """
        if isinstance(name_or_dict, dict):
            for key, val in name_or_dict.items():
                self._variables[str(key)] = _stringify(val)
        else:
            if value is None:
                raise ValueError("add_variable requires a value when name is a string")
            self._variables[str(name_or_dict)] = _stringify(value)
        return self

    def add_trigger(self, expression: str) -> Node:
        """
        Set the trigger expression.

        A node can only have one trigger. To build a compound expression, use
        ``add_part_trigger`` after the initial ``add_trigger`` call.
        """
        if self._trigger is not None:
            raise ValueError(
                "Cannot call add_trigger() more than once on the same node. "
                "Use add_part_trigger() to extend the expression."
            )
        self._trigger = str(expression)
        return self

    def add_part_trigger(self, expression: str, and_flag: bool = True) -> Node:
        """
        Append a partial trigger expression.

        Parameters
        ----------
        expression : str
            The trigger fragment to append.
        and_flag : bool, optional
            If ``True`` (default), join with ``and``. Otherwise join with ``or``.
        """
        if self._trigger is None:
            self._trigger = str(expression)
        else:
            operator = "and" if and_flag else "or"
            self._trigger = f"{self._trigger} {operator} {expression}"
        return self

    def add_complete(self, expression: str) -> Node:
        """Add a complete expression."""
        self._completes.append(Complete(expression))
        return self

    def add_event(self, name: str) -> Node:
        """Add an event."""
        self._events.append(Event(name))
        return self

    def add_meter(
        self,
        name: str,
        min_value: int,
        max_value: int,
    ) -> Node:
        """Add a meter."""
        self._meters.append(Meter(str(name), int(min_value), int(max_value)))
        return self

    def add_limit(self, name: str, value: int) -> Node:
        """Add a limit."""
        self._limits.append(Limit(str(name), int(value)))
        return self

    def add_inlimit(self, name: str, tokens: int = 1) -> Node:
        """Add an in-limit reference."""
        self._inlimits.append(InLimit(str(name), int(tokens)))
        return self

    def add_repeat(self, repeat: Repeat) -> Node:
        """Add a repeat attribute."""
        self._repeats.append(repeat)
        return self

    def add_clock(self, clock: Clock) -> Node:
        """Add a clock (suite level)."""
        self._clock = clock
        return self

    def add_time(self, time_str: str) -> Node:
        """Add a time dependency."""
        self._times.append(Time(time_str))
        return self

    def add_late(self, late: Late) -> Node:
        """Add a late monitoring attribute."""
        self._lates.append(late)
        return self

    def add_defstatus(self, state: Union[DState, str]) -> Node:
        """Set the default status."""
        if isinstance(state, str):
            state = DState(state)
        self._defstatus = state
        return self

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def to_def(self, level: int = 0) -> Iterator[str]:
        """
        Yield the ``.def`` text lines for this node and its children.

        Parameters
        ----------
        level : int
            Indentation level (0 for suite, 1 for its direct children, etc.).
        """
        pad = self.INDENT * level
        keyword = self._keyword

        yield f"{pad}{keyword} {self._name}"

        # Suite-level clock.
        if keyword == "suite" and self._clock is not None:
            yield f"{pad}{self.INDENT}{self._clock.to_def()}"

        # Default status.
        if self._defstatus is not None:
            yield f"{pad}{self.INDENT}{DefStatus(self._defstatus).to_def()}"

        # Repeats.
        for repeat in self._repeats:
            yield f"{pad}{self.INDENT}{repeat.to_def()}"

        # Variables.
        for key, value in self._variables.items():
            yield f"{pad}{self.INDENT}edit {key} {_quote(value)}"

        # Attribute objects (limits, inlimits, events, meters, times, lates, completes).
        for limit in self._limits:
            yield f"{pad}{self.INDENT}{limit.to_def()}"
        for inlimit in self._inlimits:
            yield f"{pad}{self.INDENT}{inlimit.to_def()}"
        for event in self._events:
            yield f"{pad}{self.INDENT}{event.to_def()}"
        for meter in self._meters:
            yield f"{pad}{self.INDENT}{meter.to_def()}"
        for time_attr in self._times:
            yield f"{pad}{self.INDENT}{time_attr.to_def()}"
        for late in self._lates:
            yield f"{pad}{self.INDENT}{late.to_def()}"
        for complete in self._completes:
            yield f"{pad}{self.INDENT}{complete.to_def()}"

        # Trigger.
        if self._trigger is not None:
            yield f"{pad}{self.INDENT}{Trigger(self._trigger).to_def()}"

        # Children.
        for child in self._children:
            yield from child.to_def(level + 1)

        # Tasks are implicitly closed by the next sibling or endfamily/endsuite,
        # matching the output of the native ecflow C++ API.
        if keyword != "task":
            yield f"{pad}end{keyword}"

    # ------------------------------------------------------------------
    # Convenience add / += operators
    # ------------------------------------------------------------------
    def add(self, *children: Any) -> Node:
        """Add constructor-style children after the node is created."""
        for child in children:
            self._add_child_object(child)
        return self

    def __iadd__(self, other: Any) -> Node:
        """Support ``node += Edit(...)`` style usage."""
        if isinstance(other, (list, tuple)):
            for item in other:
                self._add_child_object(item)
        else:
            self._add_child_object(other)
        return self


def _stringify(value: Any) -> str:
    """Convert a variable value to its string representation."""
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


class Suite(Node):
    """Top-level suite node."""

    _keyword = "suite"


class Family(Node):
    """Container family node."""

    _keyword = "family"


class Task(Node):
    """Leaf task node."""

    _keyword = "task"

    def add_family(self, family: Family) -> Family:  # type: ignore[override]
        raise TypeError("Task cannot contain families")

    def add_task(self, task: Task) -> Task:  # type: ignore[override]
        raise TypeError("Task cannot contain tasks")
