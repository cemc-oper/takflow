"""Generic credential hook system and credential.sh rendering orchestration.

Priority-sorted hooks that each render a credential.sh fragment. App-specific
renderers register via :data:`register_credential_hook`; :func:`render_credential`
collects and writes the final ``config/credential.sh``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from contextvars import ContextVar
from enum import Enum
from pathlib import Path
from typing import Dict, Optional, TYPE_CHECKING

from jinja2 import Environment, FileSystemLoader

from takflow.config.validation import load_config_data
from takflow.flow.hook import BaseHookRegistry, create_hook_decorator
from takflow.jobs.provenance import resource_source, source_block

if TYPE_CHECKING:
    from takflow.config import BaseWorkflowConfig

logger = logging.getLogger(__name__)
_credential_resources = ContextVar("takflow_credential_resources", default=(None, ()))


def render_credential_template(
    repo_base: str,
    credential: dict,
    config: "BaseWorkflowConfig",
    template_name: str = "credential_workflow.sh.j2",
) -> str:
    """Render a credential fragment from ``{repo_base}/config/{template_name}``."""
    scoped, layers = _credential_resources.get()
    env = scoped if scoped is not None else Environment(
        loader=FileSystemLoader(f"{repo_base}/config"),
        lstrip_blocks=True,
        trim_blocks=True,
    )
    name = "config/" + template_name if scoped is not None and not template_name.startswith("config/") else template_name
    template = env.get_template(name)
    text = template.render(credential=credential, config=config)
    if template.filename is not None:
        source = resource_source(Path(template.filename), layers)
        if source is not None:
            stage = "build" if config.workflow_mode == "ecflow" else None
            return source_block(text, "include", source, stage=stage)
    return text


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


def render_credential(
    credential_file: str,
    config: "BaseWorkflowConfig",
    output_repo_base: str,
    build_info_lines: Dict[str, str],
    *, environment: Environment | None = None, source_layers: tuple[tuple[str, Path], ...] = (),
) -> None:
    """Write ``config/credential.sh`` at mode 0600 from all registered hooks.

    Parameters
    ----------
    credential_file : str
        Path to ``credential.yaml``.
    config : BaseWorkflowConfig
        Workflow config (or subclass).
    output_repo_base : str
        Output repo root.
    build_info_lines : dict
        ``{"warning": ..., "info": ...}`` header lines (app-branded).
    """
    credential = load_config_data(credential_file)

    parts = [
        "#!/usr/bin/env bash",
        "#",
        f"# {build_info_lines['warning']}",
        f"# {build_info_lines['info']}",
        "#",
        "# 敏感信息配置 - 请注意保护该文件",
        "#",
        "",
        'echo "BEGIN: credential.sh"',
        "",
    ]

    registry = get_credential_registry()
    context = CredentialContext(credential=credential, config=config)
    token = _credential_resources.set((environment, source_layers))
    try:
        rendered_parts = registry.execute(CredentialHookPoint.RENDER, context)
    finally:
        _credential_resources.reset(token)

    for part in rendered_parts:
        if part and part.strip():
            parts.append(part)
            parts.append("")

    parts.append('echo "END: credential.sh"')

    output_path = Path(output_repo_base) / "config" / "credential.sh"
    from takflow._files import write_text

    write_text(output_path, "\n".join(parts) + "\n", 0o600, Path(output_repo_base))

    logger.info(f"Generated credential.sh at {output_path}")


__all__ = [
    "CredentialHookPoint",
    "CredentialContext",
    "CredentialHookRegistry",
    "get_credential_registry",
    "register_credential_hook",
    "render_credential_template",
    "render_credential",
]
