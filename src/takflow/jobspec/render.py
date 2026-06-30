"""Render a :class:`ResourceSpec` to ``#ORVIX`` directive lines.

This is the single resource carrier: takflow writes ``#ORVIX key=value`` lines
into job scripts, and orvix rewrites them to ``#SBATCH`` / ``#DSUB`` / etc. at
submit time.
"""
from __future__ import annotations

from typing import List, Optional

from takflow.jobspec.model import ResourceSpec

MARKER = "#ORVIX"


def _hyphenate(key: str) -> str:
    return key.replace("_", "-")


def _quote(value: str) -> str:
    # orvix accepts double- or single-quoted values; quote only when needed.
    if any(c.isspace() for c in value):
        return '"' + value + '"'
    return value


def _format(key: str, value) -> Optional[str]:
    """Return the ``key=value`` (or bare ``key``) fragment, or None to skip."""
    hkey = _hyphenate(key)
    if key == "exclusive":
        if value is True:
            return hkey  # bare flag
        if value is False:
            return None
        return f"{hkey}={_quote(str(value))}"
    if isinstance(value, bool):
        return f"{hkey}={'true' if value else 'false'}"
    return f"{hkey}={_quote(str(value))}"


def to_orvix_directives(
    spec: ResourceSpec,
    *,
    conditional_for: Optional[str] = None,
) -> List[str]:
    """Render ``spec`` to a list of ``#ORVIX`` directive lines.

    Parameters
    ----------
    spec:
        The flat resource description.
    conditional_for:
        When given (e.g. ``"slurm"``), each line is emitted as a conditional
        directive ``#ORVIX [scheduler=<name>] key=value``.
    """
    prefix = f"{MARKER} [scheduler={conditional_for}] " if conditional_for else f"{MARKER} "
    lines: List[str] = []
    for key, value in spec.iter_set_fields():
        fragment = _format(key, value)
        if fragment is None:
            continue
        lines.append(prefix + fragment)
    return lines


def render_resource_block(
    spec: ResourceSpec,
    *,
    conditional_for: Optional[str] = None,
) -> str:
    """Render ``spec`` to a single newline-joined ``#ORVIX`` block (no shebang)."""
    return "\n".join(to_orvix_directives(spec, conditional_for=conditional_for))


__all__ = ["to_orvix_directives", "render_resource_block", "MARKER"]
