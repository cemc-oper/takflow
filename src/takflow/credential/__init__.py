"""takflow credential layer.

Generic credential hook system + ``credential.sh`` rendering orchestration.
App-specific credential renderers register via ``register_credential_hook``.
"""
from takflow.credential.hooks import (
    CredentialContext,
    CredentialHookPoint,
    CredentialHookRegistry,
    get_credential_registry,
    register_credential_hook,
    render_credential_template,
)
from takflow.credential.render import render_credential

__all__ = [
    "CredentialContext",
    "CredentialHookPoint",
    "CredentialHookRegistry",
    "get_credential_registry",
    "register_credential_hook",
    "render_credential_template",
    "render_credential",
]
