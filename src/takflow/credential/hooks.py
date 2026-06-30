"""Generic credential hook system.

Priority-sorted hooks that each render a credential.sh fragment. App-specific
renderers register via :data:`register_credential_hook`; the orchestration in
:mod:`takflow.credential.render` collects and writes them.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, TYPE_CHECKING

from jinja2 import Environment, FileSystemLoader

from takflow.hooks.base import BaseHookRegistry, create_hook_decorator

if TYPE_CHECKING:
    from takflow.config import BaseWorkflowConfig


def render_credential_template(
    repo_base: str,
    credential: dict,
    config: "BaseWorkflowConfig",
    template_name: str = "credential_workflow.sh.j2",
) -> str:
    """Render a credential fragment from ``{repo_base}/config/{template_name}``."""
    env = Environment(loader=FileSystemLoader(f"{repo_base}/config"))
    template = env.get_template(template_name)
    return template.render(credential=credential, config=config)


class CredentialHookPoint(str, Enum):
    """Credential render hook points."""

    RENDER = "credential.render"


@dataclass
class CredentialContext:
    """Context passed to credential hooks.

    Attributes
    ----------
    credential : dict
        Parsed ``credential.yaml`` contents.
    config : BaseWorkflowConfig
        The workflow config (or a subclass).
    """

    credential: dict
    config: "BaseWorkflowConfig"


class CredentialHookRegistry(BaseHookRegistry[CredentialContext, str]):
    """Singleton credential hook registry."""

    _instance: Optional["CredentialHookRegistry"] = None

    @classmethod
    def get_instance(cls) -> "CredentialHookRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


def get_credential_registry() -> CredentialHookRegistry:
    """Return the global credential hook registry singleton."""
    return CredentialHookRegistry.get_instance()


register_credential_hook = create_hook_decorator(get_credential_registry)


__all__ = [
    "CredentialHookPoint",
    "CredentialContext",
    "CredentialHookRegistry",
    "get_credential_registry",
    "register_credential_hook",
    "render_credential_template",
]
