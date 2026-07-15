"""
Top-level ``Defs`` container that mimics ``ecflow.Defs``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

from .node import Suite


class Defs:
    """
    Container for one or more suites.

    Example:

        defs = Defs()
        defs.add_suite(Suite("my_suite"))
        defs.save_as_defs("my_suite.def")
    """

    def __init__(self, *suites: Suite):
        self._suites: list[Suite] = list(suites)

    def add_suite(self, suite: Suite) -> Suite:
        """Add a suite to the definition."""
        self._suites.append(suite)
        return suite

    def to_def(self) -> str:
        """Return the full ``.def`` text."""
        lines: list[str] = []
        for suite in self._suites:
            lines.extend(suite.to_def(0))
        text = "\n".join(lines)
        if text and not text.endswith("\n"):
            text += "\n"
        return text

    def save_as_defs(self, path: Union[str, Path]) -> None:
        """Write the definition tree to an ecFlow ``.def`` file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_def(), encoding="utf-8")

    def __str__(self) -> str:
        return self.to_def()

    def __repr__(self) -> str:
        return f"Defs(suites={len(self._suites)})"
