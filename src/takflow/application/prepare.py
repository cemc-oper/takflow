"""Resolve one application's effective inputs inside isolated scopes."""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from importlib.resources import files
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from takflow.application.context import BuildContext, BuildPaths, ConfigT, MachineContext
from takflow.application.inputs import (
    ComponentSelection, ResolvedResourceLayer, ResourceLayer, _error, _local_path, _relative,
)
from takflow.build_info import build_info_scope
from takflow.checks import preflight_generation
from takflow.config import BaseWorkflowConfig, validate_config
from takflow.config.validation import apply_config_overrides, load_config_data
from takflow.toolkit.credential import get_credential_registry

if TYPE_CHECKING:
    from takflow.application.declaration import Application


_RESERVED_CONTEXT = frozenset({
    "config", "paths", "brand", "components", "machine", "variables",
    "build_info_warning", "build_info_detail", "include_raw", "invoke_script",
    "include_machine", "render_orvix_resource_block", "render_slurm_resource_block", "stdout", "stderr",
})


@contextmanager
def prepare_application(
    application: "Application[ConfigT]", source: str | Path | Mapping[str, Any] | ConfigT, *,
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
        registries = [get_credential_registry(), *application.registries]
        for extension in application.extensions:
            registries.extend(extension.registries)
        seen = set()
        for registry in registries:
            if id(registry) not in seen:
                stack.enter_context(registry.isolated())
                seen.add(id(registry))
        for extension in application.extensions:
            if extension.initialize is not None:
                extension.initialize()

        base = _local_path(source_dir, cwd, "source_dir") if source_dir is not None else None
        if isinstance(source, BaseWorkflowConfig):
            if not isinstance(source, application.config_type):
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
            data = apply_config_overrides(data, application.config_type, overrides=effective_overrides)
            if application.normalize_config is not None:
                data = dict(application.normalize_config(data))
            for name in ("output_repo_base_dir", "workflow_repo_base_dir"):
                field_info = application.config_type.model_fields[name]
                key = field_info.validation_alias or field_info.alias or name
                if isinstance(key, str):
                    if key not in data and name in data:
                        key = name
                    value = data.get(key, field_info.default)
                    if value is not None and (key in data or isinstance(value, (str, Path))):
                        data[key] = str(_local_path(value, cwd if name in effective_overrides else base, name))
            explicit_machine_dir = data.get("machine_dir") is not None
            config = validate_config(data, application.config_type, strict_fields=application.strict_fields)

        if config.output_repo_base_dir is None:
            _error("APPLICATION_OUTPUT_REQUIRED", "output_repo_base_dir", "an output root is required")
        output_root = _local_path(config.output_repo_base_dir, base, "output_repo_base_dir")
        base_resources = (application.resources if config.workflow_repo_base_dir is None else
                          _local_path(config.workflow_repo_base_dir, base, "workflow_repo_base_dir"))
        # Select only data, using the same validated config and final base.
        base_resources = base_resources() if callable(base_resources) else base_resources
        base_resources = _local_path(base_resources, cwd, "resource_layers")
        config.workflow_repo_base_dir = str(base_resources)

        def declared_layers():
            use_public = application.use_public_resources
            if callable(use_public):
                use_public = use_public(config)
            if use_public:
                yield ResourceLayer("takflow", Path(str(files("takflow").joinpath("resources"))))
            yield ResourceLayer("base", base_resources)
            # Resolve each contribution before asking the next selector.
            # Later extensions can derive roots from earlier config fields.
            yield from application.resource_layers(config) if callable(application.resource_layers) else application.resource_layers
            for extension in application.extensions:
                yield from extension.resource_layers(config) if callable(extension.resource_layers) else extension.resource_layers

        layers = []
        layer_names = set()
        for layer in declared_layers():
            if not layer.name or layer.name in layer_names:
                _error("APPLICATION_LAYER_DUPLICATE", "resource_layers", "resource layer names must be nonempty and unique")
            layer_names.add(layer.name)
            configured = None
            if layer.config_field is not None:
                if layer.config_field not in application.config_type.model_fields:
                    _error("APPLICATION_LAYER_CONFIG_FIELD", "resource_layers", "resource layer field must name a declared config field")
                configured = getattr(config, layer.config_field)
            if configured is not None:
                # A config path is relative to its source; a canonical
                # explicit override uses the caller's cwd, like base.
                overridden = not isinstance(source, BaseWorkflowConfig) and layer.config_field in effective_overrides
                root = _local_path(configured, cwd if overridden else base, layer.config_field)
            else:
                root = layer.root() if callable(layer.root) else layer.root
                root = _local_path(root, cwd, "resource_layers")
            if layer.config_field is not None:
                setattr(config, layer.config_field, str(root))
            layers.append(ResolvedResourceLayer(layer.name, root, layer.required_inputs))
        config.workflow_repo_base_dir = str(base_resources)
        config.output_repo_base_dir = str(output_root)
        report = preflight_generation(
            config, supported_modes=application.supported_modes,
            required_operations=application.required_operations(config) if application.required_operations else (),
        )
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
        elif config.machine_dir is not None or application.require_machine:
            _error("APPLICATION_MACHINE_REQUIRED", "machine_name", "a machine name is required for the selected capability")
        brand = application.brand(config) if callable(application.brand) else application.brand
        components = application.select_components(config) if application.select_components else ComponentSelection()
        variables = dict(application.variables(config)) if application.variables else {}
        if not all(isinstance(key, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
                   and isinstance(value, str) for key, value in variables.items()):
            _error("APPLICATION_VARIABLE_TYPE", "variables", "variable names must be identifiers and values must be strings")
        if machine is not None:
            if variables.keys() & machine.variables.keys():
                _error("APPLICATION_VARIABLE_CONFLICT", "variables", "machine variables are reserved")
            variables.update(machine.variables)
        outputs = application.outputs(config) if callable(application.outputs) else application.outputs
        for extension in application.extensions:
            outputs += extension.outputs(config) if callable(extension.outputs) else extension.outputs
        fragments = (application.required_machine_fragments(config) if callable(application.required_machine_fragments)
                     else application.required_machine_fragments)
        for fragment in fragments:
            _relative(fragment)
        context = BuildContext(application, config, base, paths, brand, brand.lines(), components, machine,
                               MappingProxyType(variables), outputs, report, required_machine_fragments=tuple(fragments))
        stack.enter_context(build_info_scope(context.build_info))
        contributions = {}
        for contribute in [application.context, *(extension.context for extension in application.extensions)]:
            if contribute is not None:
                values = dict(contribute(context))
                if values.keys() & (_RESERVED_CONTEXT | contributions.keys()):
                    _error("APPLICATION_CONTEXT_CONFLICT", "context", "domain context conflicts with a reserved or contributed name")
                contributions.update(values)
        yield replace(context, domain_context=MappingProxyType(contributions))
