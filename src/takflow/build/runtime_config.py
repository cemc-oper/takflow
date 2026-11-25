"""Render declared runtime configuration and extra templates."""
from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from takflow.build.pipeline import _Pipeline


def render_runtime_config(pipeline: _Pipeline, skipped_outputs: list[str]) -> None:
    context = pipeline.context
    planned = [(context.application.config_template, context.paths.config_file, "config", 0o644, True)]
    planned.extend((item.template, pipeline.root / item.output, "extra", item.mode, item.required) for item in context.outputs)
    seen = set()
    for _, path, role, _, _ in planned:
        if path in seen:
            pipeline.fail("BUILD_OUTPUT_COLLISION", path, "multiple configured artifacts share a destination")
        seen.add(path)
        pipeline.reserve(path, role)
    for template, path, role, mode, required in planned:
        text = pipeline.render(template, required=required)
        if text is None:
            skipped_outputs.append(str(path))
            continue
        if role == "config":
            lines = []
            for name, value in pipeline.variables.items():
                encoded = (f"%{name}%" if context.config.workflow_mode == "ecflow"
                           else shlex.quote(value))
                lines.append(f"export {name}={encoded}")
            text = "\n".join(lines) + "\n" + text
        pipeline.write(path, text, role, mode)
        pipeline.record(path, role, source={"template": pipeline.template_sources[template]})
