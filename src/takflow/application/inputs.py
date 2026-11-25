"""Resource layers, component selection, and generated template declarations."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath

from takflow.config import ConfigDiagnostic, ConfigValidationError


ResourceRoot = str | Path | Callable[[], str | Path]


def _error(code: str, path: str, reason: str, stage: str = "application.context") -> None:
    raise ConfigValidationError((ConfigDiagnostic(code, (path,), reason, stage),)) from None


def _relative(value: str) -> None:
    if (not value or PurePosixPath(value).is_absolute() or ".." in PurePosixPath(value).parts
            or value == "." or "\\" in value or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        _error("APPLICATION_RELATIVE_PATH", "declaration", "a nonempty relative POSIX path without '..' is required",
               "application.declaration")


def _local_path(value: str | Path, base: Path | None, field_name: str) -> Path:
    if not isinstance(value, (str, Path)) or not str(value):
        _error("APPLICATION_PATH_TYPE", field_name, "local paths must be nonempty strings or Paths")
    path = Path(value)
    if any(ord(c) < 32 or ord(c) == 127 for c in str(path)):
        _error("APPLICATION_PATH_INVALID", field_name, "local paths must not contain control characters")
    if not path.is_absolute():
        if base is None:
            _error("APPLICATION_SOURCE_REQUIRED", field_name, "relative configuration paths require source_dir")
        path = base / path
    # Lexical normalization only; target-side paths never pass through here.
    return Path(os.path.abspath(path))


@dataclass(frozen=True)
class ResourceLayer:
    """A named source layer; later declared layers override earlier ones."""

    name: str
    root: ResourceRoot
    config_field: str | None = None
    required_inputs: tuple[str, ...] = ()

    def __post_init__(self):
        for relative in self.required_inputs:
            _relative(relative)


@dataclass(frozen=True)
class ResolvedResourceLayer:
    name: str
    root: Path
    required_inputs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResourceEntry:
    """Static source-to-output mapping, consumed by the resource stage."""

    source: str
    destination: str
    executable: bool = False
    required: bool = False

    def __post_init__(self):
        _relative(self.source)
        _relative(self.destination)


@dataclass(frozen=True)
class TemplateOutput:
    """An additional rendered artifact, not a rendering callback."""

    template: str
    output: str
    required: bool = True
    mode: int = 0o644

    def __post_init__(self):
        _relative(self.template)
        _relative(self.output)
        if self.mode not in (0o644, 0o755, 0o600):
            _error("APPLICATION_OUTPUT_MODE", "mode", "artifact mode must be 0644, 0755 or 0600",
                   "application.declaration")


def _no_component(path: Path) -> str | None:
    return None


@dataclass(frozen=True)
class ComponentSelection:
    """One selection shared by resource and job stages.

    Classifiers return the component of a resource-root/job-root relative path,
    or None for shared files. They must not read files or perform generation.
    """

    enabled: frozenset[str] = frozenset()
    resource_component: Callable[[Path], str | None] = _no_component
    job_component: Callable[[Path], str | None] = _no_component

    def keep_resource(self, path: str | Path) -> bool:
        component = self.resource_component(Path(path))
        return component is None or component in self.enabled

    def keep_job(self, path: str | Path) -> bool:
        component = self.job_component(Path(path))
        return component is None or component in self.enabled
