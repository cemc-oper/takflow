"""Resolve and invoke business scripts from job templates."""
from __future__ import annotations

import io
import shlex
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from takflow.checks import GenerationCheckReport, check_input_file, check_relative_path
from takflow.jobs.provenance import source_block

if TYPE_CHECKING:
    from takflow.config import BaseWorkflowConfig


def _runtime_reference(value: str) -> bool:
    return any(marker in value for marker in ("$", "%", "{{", "{%", "://"))


def _check_script_reference(
    script_path: str, output_repo_base: str, config: "BaseWorkflowConfig",
    report: GenerationCheckReport, *, helper: str, stage: str,
) -> None:
    dynamic = _runtime_reference(script_path)
    script_file = check_relative_path(output_repo_base, script_path, stage=stage,
                                      report=report, object=helper if dynamic else None)
    if dynamic:
        report.unchecked("GEN_SCRIPT_DYNAMIC", stage, helper,
                         "script location contains an unresolved runtime or remote reference")
        return
    check_input_file(
        script_file, stage=stage, report=report,
        executable=helper == "invoke_script" and config.script_invoke_mode != "inline",
    )


def _script_template_helpers(
    config: BaseWorkflowConfig,
    output_repo_base: str,
    report: GenerationCheckReport,
    *,
    protect_input: Callable[[Path], None],
    script_input_check: Callable[[str], None] | None,
    script_source: Callable[[Path, bytes], str],
    legacy_renderer: bool,
) -> dict[str, Callable[..., str]]:
    """Bind script operations to the current render's input checks."""

    def embed_script(script_path: str, kind: str) -> str:
        script_file = check_relative_path(output_repo_base, script_path, stage="job.render",
                                          report=report)
        protect_input(script_file)
        if script_input_check is not None:
            script_input_check(script_path)
        check_input_file(script_file, stage="job.render", report=report)
        payload = script_file.read_bytes()
        with io.TextIOWrapper(io.BytesIO(payload), encoding=None if legacy_renderer else "utf-8") as f:
            content = f.read()
        if content.strip():
            mode = "takler" if kind == "include" and config.workflow_mode == "takler" else "shell"
            stage = "build" if config.workflow_mode == "ecflow" else None
            content = source_block(content, kind, script_source(script_file, payload), mode, stage=stage)

        # ecflow 模式下需用 %nopp/%end 包裹原生脚本内容，
        # 避免 ecflow 预处理器解析脚本中的 % 指令。
        # 注意：保留与 mcv 原实现一致的 12 空格空行，确保字节级输出不变。
        if config.workflow_mode == "ecflow":
            _pad = " " * 12
            content = f"%nopp\n{_pad}\n{content}\n{_pad}\n%end\n"
        return content

    def include_raw(script_path: str) -> str:
        return embed_script(script_path, "include")

    def invoke_script(script_path: str, *args: str) -> str:
        """Invoke a business script; arguments are literal strings, not shell code.

        Callbacks belong to the parent job. Keep exits, shell options,
        variables and directory changes inside the business invocation. Do not
        put this command in an if/AND/OR list: that can disable errexit inside.
        Configuration fragments should use include_raw instead.
        """
        arguments = " ".join(shlex.quote(arg) for arg in args)
        workflow = config.workflow_mode
        inline = config.script_invoke_mode == "inline"
        if workflow == "ecflow":
            # ecFlow substitutes %NAME% even inside shell quotes. %% is a literal %.
            arguments = arguments.replace("%", "%%")
        elif workflow == "takler" and args:
            # Pass the quoted shell words through takler's Jinja render as a string literal.
            arguments = "{{ " + repr(arguments) + " }}"
        if inline:
            invocation = embed_script(script_path, "script")
            if workflow == "takler":
                invocation = "{% raw %}\n" + invocation + "\n{% endraw %}"
            if args:
                invocation = f"set -- {arguments}\n{invocation}"
        else:
            _check_script_reference(script_path, output_repo_base, config, report,
                                    helper="invoke_script", stage="job.render")
            runtime_path = _runtime_reference(script_path)
            if not runtime_path:
                protect_input(Path(output_repo_base, script_path))
                if script_input_check is not None:
                    script_input_check(script_path)
            if legacy_renderer and runtime_path:
                # The legacy renderer allows runtime references in the path.
                invocation = f'"${{OUTPUT_REPO_BASE}}/{script_path}"'
            else:
                invocation = '"${OUTPUT_REPO_BASE}"/' + shlex.quote(script_path)
            if args:
                invocation += f" {arguments}"
        if inline or workflow == "ecflow":
            if workflow in ("ecflow", "takler"):
                invocation = (
                    "# Give ksh93 a real subshell so the parent can handle signals.\n"
                    "case ${KSH_VERSION:-} in\n"
                    "    *93*) trap : 0; trap - 0 ;;\n"
                    "esac\n"
                    + invocation
                )
            # A comment-only marker task still needs a command inside (...).
            return f"(\n:\n{invocation}\n)\n"
        return invocation

    return {"include_raw": include_raw, "invoke_script": invoke_script}
