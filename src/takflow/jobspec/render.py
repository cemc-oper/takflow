"""Render ORVIX resource directives and the shared native Slurm option subset."""
from __future__ import annotations

from typing import List, Optional

from takflow.jobspec.model import ResourceSpec

MARKER = "#ORVIX"

# Fields shared by the two historical Slurm submission paths.
SLURM_OPTIONS = {
    "job_name": "job-name", "output": "output", "error": "error",
    "nodes": "nodes", "ntasks_per_node": "ntasks-per-node", "time": "time",
    "queue": "partition", "project": "wckey", "application": "comment",
    "memory": "mem",
}


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


def orvix_directive(field: str, value, *, prefix: str = "#ORVIX ") -> Optional[str]:
    fragment = _format(field, value)
    return prefix + fragment if fragment is not None else None


def slurm_directive(field: str, value, *, engine_reference: bool = False) -> Optional[str]:
    """Render a supported Slurm option, including its flag-specific boolean rules."""
    if value is None:
        return None
    if field == "requeue":
        return "#SBATCH --no-requeue" if value is False else None
    if field == "exclusive":
        option = _format(field, value)
        return f"#SBATCH --{option}" if option else None
    option = SLURM_OPTIONS.get(field)
    if option is None:
        return None
    dynamic_text = engine_reference and field in {"job_name", "queue", "application", "project", "output", "error"}
    argument = f'"{value}"' if dynamic_text else _quote(str(value))
    return f"#SBATCH --{option}={argument}"


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
        line = orvix_directive(key, value, prefix=prefix)
        if line is not None:
            lines.append(line)
    return lines


def render_resource_block(
    spec: ResourceSpec,
    *,
    conditional_for: Optional[str] = None,
) -> str:
    """Render ``spec`` to a single newline-joined ``#ORVIX`` block (no shebang)."""
    return "\n".join(to_orvix_directives(spec, conditional_for=conditional_for))


__all__ = ["to_orvix_directives", "render_resource_block", "MARKER"]
