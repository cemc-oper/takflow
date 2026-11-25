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
]
