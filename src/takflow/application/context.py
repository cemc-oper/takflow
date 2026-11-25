"""Prepared workflow paths, machine settings, and template context."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from takflow.application.inputs import ComponentSelection, ResolvedResourceLayer, TemplateOutput
from takflow.checks import GenerationCheckReport
from takflow.config import BaseWorkflowConfig

if TYPE_CHECKING:
    from takflow.application.declaration import Application, ApplicationBrand


ConfigT = TypeVar("ConfigT", bound=BaseWorkflowConfig)


@dataclass(frozen=True)
class MachineContext:
    """Target-side directory; external paths are never probed locally."""

    name: str
    directory: PurePosixPath
    external: bool

    @property
    def variables(self) -> Mapping[str, str]:
        return MappingProxyType({"MACHINE_NAME": self.name, "MACHINE_DIR": str(self.directory)})


@dataclass(frozen=True)
class BuildPaths:
    output_root: Path
    resource_layers: tuple[ResolvedResourceLayer, ...]
    workflow_output: Path
    mode: str

    @property
    def config_dir(self) -> Path:
        return self.output_root / "config"

    @property
    def config_file(self) -> Path:
        return self.config_dir / ("config.h" if self.mode == "ecflow" else "config.sh")

    @property
    def jobs_dir(self) -> Path:
        return self.output_root / "jobs"

    @property
    def scripts_dir(self) -> Path:
        return self.output_root / "scripts"

    @property
    def ecflow_include(self) -> Path:
        return self.output_root / "ecflow/include"

    @property
    def takler_include(self) -> Path:
        return self.output_root / "takler/include"


@dataclass(frozen=True)
class BuildContext(Generic[ConfigT]):
    """Effective inputs, valid within the owning prepare scope.

    Config is an owned copy, read-only by contract. TC-06 owns stage results
    and artifact output. A check report here is not a success manifest.
    """

    application: Application[ConfigT]
    config: ConfigT
    source_dir: Path | None
    paths: BuildPaths
    brand: ApplicationBrand
    build_info: Mapping[str, str]
    components: ComponentSelection
    machine: MachineContext | None
    variables: Mapping[str, str]
    outputs: tuple[TemplateOutput, ...]
    checks: GenerationCheckReport
    domain_context: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    required_machine_fragments: tuple[str, ...] = ()

    def template_context(self) -> Mapping[str, Any]:
        return MappingProxyType({
            "config": self.config, "paths": self.paths, "brand": self.brand,
            "components": self.components, "machine": self.machine,
            "variables": self.variables,
            "build_info_warning": self.build_info["warning"],
            "build_info_detail": self.build_info["info"],
            **self.domain_context,
        })
