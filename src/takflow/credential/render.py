"""Generic credential.sh rendering orchestration.

Collects fragments from all registered credential hooks and writes a single
``config/credential.sh`` (mode 0o700). Build-info branding is supplied by the
caller via ``build_info_lines`` so takflow stays app-agnostic.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, TYPE_CHECKING

import yaml

from takflow.credential.hooks import (
    CredentialContext,
    CredentialHookPoint,
    get_credential_registry,
)

if TYPE_CHECKING:
    from takflow.config import BaseWorkflowConfig

logger = logging.getLogger(__name__)


def render_credential(
    credential_file: str,
    config: "BaseWorkflowConfig",
    output_repo_base: str,
    build_info_lines: Dict[str, str],
) -> None:
    """Render and merge ``config/credential.sh`` from all registered hooks.

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
    with open(credential_file, "r") as f:
        credential = yaml.safe_load(f)

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
    rendered_parts = registry.execute(CredentialHookPoint.RENDER, context)

    for part in rendered_parts:
        if part and part.strip():
            parts.append(part)
            parts.append("")

    parts.append('echo "END: credential.sh"')

    output_path = Path(output_repo_base) / "config" / "credential.sh"
    output_path.parent.mkdir(exist_ok=True, parents=True)
    output_path.write_text("\n".join(parts))

    os.chmod(output_path, 0o700)

    logger.info(f"Generated credential.sh at {output_path}")


__all__ = ["render_credential"]
