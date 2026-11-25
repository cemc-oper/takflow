"""Optional Sledra configuration and legacy definition export."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from string import Formatter
from typing import Any, Mapping, Sequence

from takflow.config.workflow import ObservabilityConfig
from takflow.flow.node import Node, NodeType


SCHEMA_VERSION = "1.0.0"
# Canonical JSON digest of the Sledra 1.0.0 published definition schema.
_SCHEMA_SHA256 = "e1ecd0e3807064a6cc5f125905e397a6b381287a47299a1c2ef7214d60dc3582"


class ObservabilityConfigError(ValueError):
    """Enabled definition export has invalid configuration or mapping."""


def execution_environment(config: ObservabilityConfig) -> dict[str, str]:
    """Return target-host values for an explicitly enabled Execution adapter.

    This is data, not shell code. The application quotes it for its source
    templates and skips its adapter entirely for an empty mapping. No files,
    roots, identities or legacy manifests are created here.
    """
    if not config.enabled or config.mode != "execution-v2":
        return {}
    return {
        "SLEDRA_MODE": "execution-v2",
        "SLEDRA_BIN": config.recorder_bin,
        "SLEDRA_BASH_LIBRARY": config.bash_library,
        "SLEDRA_ROOT": config.root,
    }


@dataclass(frozen=True)
class TaskMapping:
    """Application-owned stable identity for one generated task node."""

    node: Node
    task_key: str
    task_kind: str
    stage_key: str
    parameters: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    depends_on: Sequence[str] = ()
    engine_path_template: str | None = None


def _normalized(value: Any) -> Any:
    if isinstance(value, str):
        result = unicodedata.normalize("NFC", value)
        if any(0xD800 <= ord(c) <= 0xDFFF for c in result):
            raise ObservabilityConfigError("unpaired Unicode surrogate")
        return result
    if value is None or isinstance(value, bool):
        return value
    if type(value) is int and -(1 << 63) <= value < 1 << 63:
        return value
    if isinstance(value, list):
        return [_normalized(item) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ObservabilityConfigError("JSON keys must be strings")
            key = _normalized(key)
            if key in result:
                raise ObservabilityConfigError("JSON keys collide after NFC normalization")
            result[key] = _normalized(item)
        return result
    raise ObservabilityConfigError("unsupported Sledra JSON value")


def _canonical(value: Any) -> bytes:
    encoded = json.dumps(_normalized(value), ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False)
    return encoded.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029").encode("utf-8")


def _validator(config: ObservabilityConfig):
    if not config.spec_dir:
        raise ObservabilityConfigError("enabled observability requires spec_dir")
    path = Path(config.spec_dir)
    if not path.is_absolute():
        raise ObservabilityConfigError("spec_dir must be an absolute published Sledra 1.0.0 directory")
    try:
        import jsonschema
    except ImportError as exc:
        raise ObservabilityConfigError("enabled observability requires jsonschema") from exc
    try:
        schema = json.loads((path / "definition_manifest.schema.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ObservabilityConfigError("Sledra definition schema is unavailable") from exc
    if hashlib.sha256(_canonical(schema)).hexdigest() != _SCHEMA_SHA256:
        raise ObservabilityConfigError("Sledra definition schema is incompatible with 1.0.0")
    return jsonschema.Draft202012Validator(schema)


def expand_task_parameters(task: Mapping[str, Any], values: Mapping[str, Any]) -> dict[str, Any]:
    """Expand defaults and reject values that cannot identify a task instance."""
    rules = task["parameters"]
    values = _normalized(dict(values))
    unknown = set(values) - set(rules)
    if unknown:
        raise ObservabilityConfigError(f"undeclared parameters: {sorted(unknown)}")
    for name, rule in rules.items():
        if name not in values:
            if "default" in rule:
                values[name] = rule["default"]
            elif rule["required"]:
                raise ObservabilityConfigError(f"required parameter missing: {name}")
        if name not in values:
            continue
        value = values[name]
        valid = ((rule["type"] == "string" and isinstance(value, str)) or
                 (rule["type"] == "boolean" and type(value) is bool) or
                 (rule["type"] == "integer" and type(value) is int and
                  -(1 << 63) <= value < 1 << 63))
        if not valid or ("enum" in rule and value not in rule["enum"]):
            raise ObservabilityConfigError(f"invalid parameter: {name}")
    return values


def export_definition_manifest(
    root: Node,
    mappings: Sequence[TaskMapping],
    *,
    observability: ObservabilityConfig,
    application_revision: str,
    config_revision: str,
    mapping_version: str,
    generator_version: str,
    script_invoke_mode: str,
    product_rule_refs: Sequence[Mapping[str, str]] = (),
) -> dict[str, Any] | None:
    """Export a static definition; disabled mode leaves the generated tree untouched.

    The application supplies every task key and dependency. This function never
    creates a Run, Attempt, runtime context, or recorder event.
    """
    if not observability.enabled or observability.mode != "legacy-v1":
        return None
    validator = _validator(observability)
    if not all((application_revision, config_revision, mapping_version, generator_version)):
        raise ObservabilityConfigError("application, config, mapping and generator revisions are required")
    if script_invoke_mode not in ("inline", "external"):
        raise ObservabilityConfigError("script_invoke_mode must be inline or external")

    def walk(node: Node) -> list[Node]:
        return [node] + [descendant for child in node.children for descendant in walk(child)]

    nodes = walk(root)
    task_nodes = {id(node): node for node in nodes if node.node_type is NodeType.TASK}
    if len(mappings) != len(task_nodes) or {id(item.node) for item in mappings} != set(task_nodes):
        raise ObservabilityConfigError("every generated task needs exactly one explicit mapping")
    if any(item.node.node_type is not NodeType.TASK for item in mappings):
        raise ObservabilityConfigError("only task nodes may be mapped")

    tasks = []
    for item in mappings:
        path = item.engine_path_template or item.node.path
        try:
            parts = list(Formatter().parse(path))
        except ValueError as exc:
            raise ObservabilityConfigError("invalid engine path template") from exc
        if any(field_name is not None and (format_spec or conversion or not field_name.isidentifier())
               for _, field_name, format_spec, conversion in parts):
            raise ObservabilityConfigError("path template supports only simple parameter names")
        fields = {field_name for _, field_name, _, _ in parts if field_name is not None}
        if fields - set(item.parameters):
            raise ObservabilityConfigError(f"path template has undeclared parameters: {sorted(fields - set(item.parameters))}")
        if any(not item.parameters[name].get("required") and "default" not in item.parameters[name]
               for name in fields):
            raise ObservabilityConfigError("path parameters must be required or have defaults")
        task = {
            "task_key": item.task_key,
            "task_kind": item.task_kind,
            "stage_key": item.stage_key,
            "parameters": _normalized(dict(item.parameters)),
            "engine_path_template": path,
            "depends_on": list(item.depends_on),
        }
        tasks.append(_normalized(task))
    tasks.sort(key=lambda task: task["task_key"])
    if len({task["task_key"] for task in tasks}) != len(tasks):
        raise ObservabilityConfigError("task_key must be unique")
    if len({task["engine_path_template"] for task in tasks}) != len(tasks):
        raise ObservabilityConfigError("engine path template must be unique")
    keys = {task["task_key"] for task in tasks}
    for task in tasks:
        if set(task["depends_on"]) - keys:
            raise ObservabilityConfigError(f"unknown dependency for {task['task_key']}")
        for name, rule in task["parameters"].items():
            if "default" in rule:
                expand_task_parameters({"parameters": {name: rule}}, {})
            for value in rule.get("enum", []):
                expand_task_parameters({"parameters": {name: rule}}, {name: value})

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "kind": "definition_manifest",
        "generator": {"name": "takflow", "version": generator_version},
        "application_revision": application_revision,
        "mapping_version": mapping_version,
        "tasks": tasks,
        "stage_definitions": sorted({task["stage_key"] for task in tasks}),
        "product_rule_refs": [dict(ref) for ref in product_rule_refs],
        "extensions": {"takflow.generation": {
            "config_revision": config_revision,
            "script_invoke_mode": script_invoke_mode,
        }},
    }
    manifest = _normalized(manifest)
    errors = list(validator.iter_errors(manifest | {"definition_id": "pending", "content_sha256": "0" * 64}))
    if errors:
        raise ObservabilityConfigError(f"Sledra definition schema rejected mapping: {errors[0].message}")
    digest = hashlib.sha256(_canonical(manifest)).hexdigest()
    manifest["content_sha256"] = digest
    manifest["definition_id"] = "def_" + digest
    return manifest


def write_definition_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    """Write a fully validated definition after generation succeeds."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(dict(manifest)) + b"\n")
