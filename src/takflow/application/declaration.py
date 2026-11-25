"""Application declarations and extension registration ownership."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Generic

from takflow.application.context import BuildContext, ConfigT
from takflow.application.inputs import (
    ComponentSelection, ResourceEntry, ResourceLayer, ResourceRoot, TemplateOutput, _error, _relative,
)
from takflow.application.prepare import prepare_application
from takflow.build_info import get_build_info, get_build_info_lines
from takflow.config import BaseWorkflowConfig
from takflow.flow import Node, WorkflowEngine
from takflow.flow.hook import BaseHookRegistry


@dataclass(frozen=True)
class ApplicationBrand:
    """Explicit identity; target_model may include the domain model version."""

    tool_name: str
    version: str
    target_model: str | None = None

    def lines(self) -> Mapping[str, str]:
        lines = get_build_info_lines(get_build_info(self.version), self.tool_name)
        if self.target_model is not None:
            lines["info"] += f" (target model: {self.target_model})"
        return MappingProxyType(lines)


@dataclass(frozen=True)
class ApplicationExtension:
    """Registration initializer plus declarative local contributions.

    Initializers register functions on listed registries on *each* build.
    Import-only registration is insufficient because Python caches imports.
    They must not write artifacts, execute business code or load config.
    """

    name: str
    initialize: Callable[[], None] | None = None
    registries: tuple[BaseHookRegistry, ...] = ()
    resource_layers: tuple[ResourceLayer, ...] | Callable[[BaseWorkflowConfig], tuple[ResourceLayer, ...]] = ()
    context: Callable[[BuildContext], Mapping[str, Any]] | None = None
    outputs: tuple[TemplateOutput, ...] | Callable[[BaseWorkflowConfig], tuple[TemplateOutput, ...]] = ()


@dataclass(frozen=True)
class Application(Generic[ConfigT]):
    """Application declaration with no resource/config/job/workflow handlers."""

    config_type: type[ConfigT]
    resources: ResourceRoot
    brand: ApplicationBrand | Callable[[ConfigT], ApplicationBrand]
    suite_builder: Callable[[ConfigT, WorkflowEngine], Node] | None = None
    shell_template: str | None = None
    supported_modes: tuple[str, ...] = ("ecflow",)
    normalize_config: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None
    select_components: Callable[[ConfigT], ComponentSelection] | None = None
    variables: Callable[[ConfigT], Mapping[str, str]] | None = None
    context: Callable[[BuildContext[ConfigT]], Mapping[str, Any]] | None = None
    resource_layers: tuple[ResourceLayer, ...] | Callable[[ConfigT], tuple[ResourceLayer, ...]] = ()
    resource_entries: tuple[ResourceEntry, ...] = (
        ResourceEntry("scripts", "scripts", executable=True),
        ResourceEntry("ecflow/include", "ecflow/include"),
        ResourceEntry("takler/include", "takler/include"),
        ResourceEntry("utils", "utils"),
    )
    config_template: str = "config/config.sh.j2"
    outputs: tuple[TemplateOutput, ...] | Callable[[ConfigT], tuple[TemplateOutput, ...]] = ()
    extensions: tuple[ApplicationExtension, ...] = ()
    registries: tuple[BaseHookRegistry, ...] = ()
    require_machine: bool = False
    credential_enabled: bool | Callable[[ConfigT], bool] = False
    strict_fields: bool = False
    required_operations: Callable[[ConfigT], tuple[str, ...]] | None = None
    context_suite_builder: Callable[[BuildContext[ConfigT], WorkflowEngine], Node] | None = None
    required_machine_fragments: tuple[str, ...] | Callable[[ConfigT], tuple[str, ...]] = ()
    required_resource_inputs: tuple[str, ...] | Callable[[ConfigT], tuple[str, ...]] = ()
    use_public_resources: bool | Callable[[ConfigT], bool] = False

    def __post_init__(self):
        if not isinstance(self.config_type, type) or not issubclass(self.config_type, BaseWorkflowConfig):
            _error("APPLICATION_CONFIG_TYPE", "config_type", "config_type must subclass BaseWorkflowConfig",
                   "application.declaration")
        if self.resources is None or self.brand is None:
            _error("APPLICATION_INPUT_REQUIRED", "declaration", "resources and brand are required",
                   "application.declaration")
        if not self.supported_modes or set(self.supported_modes) - {"ecflow", "takler", "shell"}:
            _error("APPLICATION_MODES", "supported_modes", "declare supported ecflow, takler or shell modes",
                   "application.declaration")
        if self.suite_builder is not None and self.context_suite_builder is not None:
            _error("APPLICATION_BUILDER_CONFLICT", "suite_builder", "declare only one config or context suite builder",
                   "application.declaration")
        if set(self.supported_modes) - {"shell"} and not (callable(self.suite_builder) or callable(self.context_suite_builder)):
            _error("APPLICATION_BUILDER_REQUIRED", "suite_builder", "a suite builder is required for definition modes",
                   "application.declaration")
        if "shell" in self.supported_modes and self.shell_template is None:
            _error("APPLICATION_RUNNER_REQUIRED", "shell_template", "a domain runner template is required for shell mode",
                   "application.declaration")
        _relative(self.config_template)
        if self.shell_template is not None:
            _relative(self.shell_template)
        if not callable(self.required_machine_fragments):
            for fragment in self.required_machine_fragments:
                _relative(fragment)
        if not callable(self.required_resource_inputs):
            for resource in self.required_resource_inputs:
                _relative(resource)
        names = set()
        for extension in self.extensions:
            if not extension.name or extension.name in names:
                _error("APPLICATION_EXTENSION_DUPLICATE", "extensions", "extension names must be nonempty and unique",
                       "application.declaration")
            names.add(extension.name)

    def prepare(
        self, source: str | Path | Mapping[str, Any] | ConfigT, *,
        source_dir: str | Path | None = None,
        overrides: Mapping[str, Any] | None = None,
        output_repo_base: str | Path | None = None,
        workflow_repo_base: str | Path | None = None,
        output: str | Path | None = None,
    ) -> AbstractContextManager[BuildContext[ConfigT]]:
        """Prepare once and restore registration/brand scopes even on failure.

        File/mapping inputs accept canonical whole-field overrides before domain
        validators. Validated models preserve explicit-field state and reject
        overrides: use raw data to revalidate changed values instead.
        """
        return prepare_application(
            self, source, source_dir=source_dir, overrides=overrides,
            output_repo_base=output_repo_base, workflow_repo_base=workflow_repo_base,
            output=output,
        )
