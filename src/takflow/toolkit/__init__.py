"""takflow toolkit — reusable CLI building blocks for workflow generators."""
from takflow.toolkit.config import render_config_template
from takflow.toolkit.credential import (
    CredentialContext,
    CredentialHookPoint,
    CredentialHookRegistry,
    get_credential_registry,
    register_credential_hook,
    render_credential,
    render_credential_template,
)
from takflow.toolkit.resource import copy_resource_entries, copy_resources_to_output, make_scripts_executable
from takflow.toolkit.observability import (
    ObservabilityConfigError,
    TaskMapping,
    execution_environment,
    expand_task_parameters,
    export_definition_manifest,
    write_definition_manifest,
)
from takflow.toolkit.util import (
    common_setting,
    script_cmd_var_name,
    script_cmd_value,
    set_scheduling,
)

__all__ = [
    "render_config_template",
    "copy_resources_to_output",
    "copy_resource_entries",
    "make_scripts_executable",
    "render_credential",
    "render_credential_template",
    "register_credential_hook",
    "CredentialContext",
    "CredentialHookPoint",
    "CredentialHookRegistry",
    "get_credential_registry",
    "common_setting",
    "script_cmd_var_name",
    "script_cmd_value",
    "set_scheduling",
    "ObservabilityConfigError",
    "TaskMapping",
    "execution_environment",
    "expand_task_parameters",
    "export_definition_manifest",
    "write_definition_manifest",
]
