"""Declarative application inputs and a scoped, write-free build context.

``Application.prepare`` initializes extensions, loads one effective config and
resolves shared inputs. It does not copy, render, save, submit or run scripts.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
import os
import re
from types import MappingProxyType
from typing import Any, Generic, TypeVar

from takflow.build_info import build_info_scope, get_build_info, get_build_info_lines
from takflow.checks import GenerationCheckReport, preflight_generation
from takflow.config import BaseWorkflowConfig, ConfigDiagnostic, ConfigValidationError, validate_config
from takflow.config.validation import apply_config_overrides, load_config_data
from takflow.flow import Node, WorkflowEngine
from takflow.flow.hook import BaseHookRegistry
from takflow.toolkit.credential import get_credential_registry


ConfigT = TypeVar("ConfigT", bound=BaseWorkflowConfig)
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
class ResourceLayer:
    """A named source layer; later declared layers override earlier ones."""

    name: str
    root: ResourceRoot


@dataclass(frozen=True)
class ResolvedResourceLayer:
    name: str
    root: Path


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
class ApplicationExtension:
    """Registration initializer plus declarative local contributions.

    Initializers register functions on listed registries on *each* build.
    Import-only registration is insufficient because Python caches imports.
    They must not write artifacts, execute business code or load config.
    """

    name: str
    initialize: Callable[[], None] | None = None
    registries: tuple[BaseHookRegistry, ...] = ()
    resource_layers: tuple[ResourceLayer, ...] = ()
    context: Callable[[BuildContext], Mapping[str, Any]] | None = None
    outputs: tuple[TemplateOutput, ...] = ()


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

    def template_context(self) -> Mapping[str, Any]:
        return MappingProxyType({
            "config": self.config, "paths": self.paths, "brand": self.brand,
            "components": self.components, "machine": self.machine,
            "variables": self.variables,
            "build_info_warning": self.build_info["warning"],
            "build_info_detail": self.build_info["info"],
            **self.domain_context,
        })


_RESERVED_CONTEXT = frozenset({
    "config", "paths", "brand", "components", "machine", "variables",
    "build_info_warning", "build_info_detail", "include_raw", "invoke_script",
    "include_machine", "render_orvix_resource_block", "stdout", "stderr",
})


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
    resource_layers: tuple[ResourceLayer, ...] = ()
    resource_entries: tuple[ResourceEntry, ...] = (
        ResourceEntry("scripts", "scripts", executable=True),
        ResourceEntry("ecflow/include", "ecflow/include"),
        ResourceEntry("takler/include", "takler/include"),
        ResourceEntry("utils", "utils"),
    )
    config_template: str = "config/config.sh.j2"
    outputs: tuple[TemplateOutput, ...] = ()
    extensions: tuple[ApplicationExtension, ...] = ()
    registries: tuple[BaseHookRegistry, ...] = ()
    require_machine: bool = False
    credential_enabled: bool = False
    strict_fields: bool = False
    required_operations: Callable[[ConfigT], tuple[str, ...]] | None = None
    context_suite_builder: Callable[[BuildContext[ConfigT], WorkflowEngine], Node] | None = None

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
        names = set()
        for extension in self.extensions:
            if not extension.name or extension.name in names:
                _error("APPLICATION_EXTENSION_DUPLICATE", "extensions", "extension names must be nonempty and unique",
                       "application.declaration")
            names.add(extension.name)

    @contextmanager
    def prepare(
        self, source: str | Path | Mapping[str, Any] | ConfigT, *,
        source_dir: str | Path | None = None,
        overrides: Mapping[str, Any] | None = None,
        output_repo_base: str | Path | None = None,
        workflow_repo_base: str | Path | None = None,
        output: str | Path | None = None,
    ) -> Iterator[BuildContext[ConfigT]]:
        """Prepare once and restore registration/brand scopes even on failure.

        File/mapping inputs accept canonical whole-field overrides before domain
        validators. Validated models preserve explicit-field state and reject
        overrides: use raw data to revalidate changed values instead.
        """
        cwd = Path.cwd()
        with ExitStack() as stack:
            registries = [get_credential_registry(), *self.registries]
            for extension in self.extensions:
                registries.extend(extension.registries)
            seen = set()
            for registry in registries:
                if id(registry) not in seen:
                    stack.enter_context(registry.isolated())
                    seen.add(id(registry))
            for extension in self.extensions:
                if extension.initialize is not None:
                    extension.initialize()

            base = _local_path(source_dir, cwd, "source_dir") if source_dir is not None else None
            if isinstance(source, BaseWorkflowConfig):
                if not isinstance(source, self.config_type):
                    _error("APPLICATION_CONFIG_TYPE", "source", "model does not match the declared config type")
                if overrides or output_repo_base is not None or workflow_repo_base is not None:
                    _error("APPLICATION_MODEL_OVERRIDES", "overrides", "use raw mapping/file input to validate overrides")
                config = source.model_copy(deep=True)
                for name in ("output_repo_base_dir", "workflow_repo_base_dir"):
                    value = getattr(config, name)
                    if value is not None:
                        setattr(config, name, str(_local_path(value, base, name)))
                explicit_machine_dir = "machine_dir" in source.model_fields_set and source.machine_dir is not None
            else:
                if isinstance(source, (str, Path)):
                    config_file = _local_path(source, cwd, "config_file")
                    base = config_file.parent
                    data = load_config_data(config_file)
                else:
                    data = source
                # normalize_config is a pure domain adapter, called after
                # canonical overrides and before the original validators.
                if overrides is not None and not isinstance(overrides, Mapping):
                    _error("CONFIG_OVERRIDES_TYPE", "overrides", "overrides must be a mapping", "config.overrides")
                effective_overrides = dict(overrides or {})
                for name, value in (("output_repo_base_dir", output_repo_base), ("workflow_repo_base_dir", workflow_repo_base)):
                    if value is not None:
                        effective_overrides[name] = str(value)
                data = apply_config_overrides(data, self.config_type, overrides=effective_overrides)
                if self.normalize_config is not None:
                    data = dict(self.normalize_config(data))
                for name in ("output_repo_base_dir", "workflow_repo_base_dir"):
                    field_info = self.config_type.model_fields[name]
                    key = field_info.validation_alias or field_info.alias or name
                    if isinstance(key, str):
                        if key not in data and name in data:
                            key = name
                        value = data.get(key, field_info.default)
                        if value is not None and (key in data or isinstance(value, (str, Path))):
                            data[key] = str(_local_path(value, cwd if name in effective_overrides else base, name))
                explicit_machine_dir = data.get("machine_dir") is not None
                config = validate_config(data, self.config_type, strict_fields=self.strict_fields)

            if config.output_repo_base_dir is None:
                _error("APPLICATION_OUTPUT_REQUIRED", "output_repo_base_dir", "an output root is required")
            output_root = _local_path(config.output_repo_base_dir, base, "output_repo_base_dir")
            base_resources = (self.resources if config.workflow_repo_base_dir is None else
                              _local_path(config.workflow_repo_base_dir, base, "workflow_repo_base_dir"))
            raw_layers = [ResourceLayer("base", base_resources), *self.resource_layers]
            for extension in self.extensions:
                raw_layers.extend(extension.resource_layers)
            layers = []
            layer_names = set()
            for layer in raw_layers:
                if not layer.name or layer.name in layer_names:
                    _error("APPLICATION_LAYER_DUPLICATE", "resource_layers", "resource layer names must be nonempty and unique")
                layer_names.add(layer.name)
                root = layer.root() if callable(layer.root) else layer.root
                layers.append(ResolvedResourceLayer(layer.name, _local_path(root, cwd, "resource_layers")))
            config.workflow_repo_base_dir = str(layers[0].root)
            config.output_repo_base_dir = str(output_root)
            report = preflight_generation(
                config, supported_modes=self.supported_modes,
                required_operations=self.required_operations(config) if self.required_operations else (),
            )
            if not config.observability.enabled:
                report.passed("APPLICATION_OBSERVABILITY_DISABLED", "application.context", "observability",
                              "optional observability is not enabled")
            suffix = ".def" if config.workflow_mode == "ecflow" else ".json"
            if config.workflow_mode == "shell":
                if output is not None:
                    _error("APPLICATION_OUTPUT_UNSUPPORTED", "output", "shell runner uses the standard run_workflow.sh path")
                workflow_output = output_root / "run_workflow.sh"
            else:
                _relative(config.workflow_name)
                if len(PurePosixPath(config.workflow_name).parts) != 1:
                    _error("APPLICATION_WORKFLOW_NAME", "workflow_name", "workflow name must be one path component")
                workflow_output = _local_path(output, output_root, "output") if output is not None else output_root / (config.workflow_name + suffix)
            paths = BuildPaths(output_root, tuple(layers), workflow_output, config.workflow_mode)
            machine = None
            if config.machine_name is not None:
                if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", config.machine_name):
                    _error("APPLICATION_MACHINE_NAME", "machine_name", "machine name must be one safe path component")
                directory = PurePosixPath(config.machine_dir) if explicit_machine_dir else PurePosixPath(str(output_root / "machine" / config.machine_name))
                if not directory.is_absolute() or any(ord(c) < 32 or ord(c) == 127 for c in str(directory)):
                    _error("APPLICATION_MACHINE_DIR", "machine_dir", "machine directory must be an absolute target path without control characters")
                machine = MachineContext(config.machine_name, directory, explicit_machine_dir)
            elif config.machine_dir is not None or self.require_machine:
                _error("APPLICATION_MACHINE_REQUIRED", "machine_name", "a machine name is required for the selected capability")
            brand = self.brand(config) if callable(self.brand) else self.brand
            components = self.select_components(config) if self.select_components else ComponentSelection()
            variables = dict(self.variables(config)) if self.variables else {}
            if not all(isinstance(key, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
                       and isinstance(value, str) for key, value in variables.items()):
                _error("APPLICATION_VARIABLE_TYPE", "variables", "variable names must be identifiers and values must be strings")
            if machine is not None:
                if variables.keys() & machine.variables.keys():
                    _error("APPLICATION_VARIABLE_CONFLICT", "variables", "machine variables are reserved")
                variables.update(machine.variables)
                report.unchecked("APPLICATION_MACHINE_RUNTIME_UNCHECKED", "application.context", "machine_dir",
                                 "target-side visibility and fragment execution are not checked")
            outputs = self.outputs + tuple(item for extension in self.extensions for item in extension.outputs)
            context = BuildContext(self, config, base, paths, brand, brand.lines(), components, machine,
                                   MappingProxyType(variables), outputs, report)
            stack.enter_context(build_info_scope(context.build_info))
            contributions = {}
            for contribute in [self.context, *(extension.context for extension in self.extensions)]:
                if contribute is not None:
                    values = dict(contribute(context))
                    if values.keys() & (_RESERVED_CONTEXT | contributions.keys()):
                        _error("APPLICATION_CONTEXT_CONFLICT", "context", "domain context conflicts with a reserved or contributed name")
                    contributions.update(values)
            yield replace(context, domain_context=MappingProxyType(contributions))


__all__ = [
    "Application", "ApplicationBrand", "ApplicationExtension", "BuildContext", "BuildPaths",
    "ComponentSelection", "MachineContext", "ResourceLayer", "ResolvedResourceLayer",
    "ResourceEntry", "TemplateOutput",
]
