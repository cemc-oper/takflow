"""Publish the manifest for a completed standard build."""
from __future__ import annotations

import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
import platform
import tempfile

from takflow import __version__
from takflow._files import make_parents
from takflow.application import BuildContext
from takflow.build.result import BuildResult
from takflow.spec.jobspec import contract_version


_IMPLEMENTATION_FILES = (
    "application/declaration.py", "application/inputs.py", "application/context.py", "application/prepare.py",
    "build/pipeline.py", "build/assets.py", "build/runtime_config.py", "build/result.py", "build/manifest.py",
    "config/credentials.py", "_files.py", "build_info.py",
    "checks/diagnostics.py", "checks/preflight.py", "checks/artifacts.py", "checks/_native.py",
    "flow/generate.py", "flow/node.py", "flow/hook.py", "flow/backend.py", "flow/scheduling.py",
    "flow/backends/ecflow/_job_paths.py", "flow/backends/ecflow/serializer/attributes.py",
    "jobs/render.py", "jobs/scripts.py", "jobs/headers.py", "jobs/provenance.py",
)


def publish_manifest(context: BuildContext, result: BuildResult, path: Path) -> None:
    """Write the success manifest atomically and mark the result complete."""
    package = files("takflow")
    public_inputs = {
        "mode": result.mode,
        "workflow_name": context.config.workflow_name,
        "script_invoke_mode": context.config.script_invoke_mode,
        "components": sorted(context.components.enabled),
    }
    fingerprint = hashlib.sha256(json.dumps(public_inputs, sort_keys=True).encode()).hexdigest()
    payload = result.as_dict()
    payload.update(
        schema_version=1,
        complete=True,
        manifest_path=str(path),
        versions={
            "takflow": __version__,
            "python": platform.python_version(),
            "application": context.brand.version,
            "tool_name": context.brand.tool_name,
            "target_model": context.brand.target_model,
            "jobspec": contract_version(),
            "orvix_pin": package.joinpath("spec/jobspec/ORVIX_VERSION").read_text().strip(),
            "takler_pin": package.joinpath("spec/takler/TAKLER_VERSION").read_text().strip(),
        },
        config_fingerprint={"scope": "public-generation-options", "sha256": fingerprint},
        resource_layers=[{"name": layer.name, "root": str(layer.root)} for layer in context.paths.resource_layers],
        implementation_sha256={
            name: hashlib.sha256(package.joinpath(name).read_bytes()).hexdigest()
            for name in _IMPLEMENTATION_FILES
        },
    )
    make_parents(path, result.output_root)
    descriptor, temporary = tempfile.mkstemp(prefix=".generation_manifest.", dir=result.output_root)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            Path(temporary).unlink(missing_ok=True)
        except OSError:
            pass
    result.manifest_path = path
    result.complete = True
