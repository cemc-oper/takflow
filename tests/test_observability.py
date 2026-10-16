"""SLD-17: optional static definition export against published Sledra resources."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from takflow.backends.ecflow import EcflowBackend
from takflow.config import ObservabilityConfig
from takflow.flow import WorkflowEngine
from takflow.toolkit.observability import (
    ObservabilityConfigError,
    TaskMapping,
    expand_task_parameters,
    export_definition_manifest,
)


def tree():
    engine = WorkflowEngine(EcflowBackend())
    suite = engine.Suite("synthetic")
    family = suite.add_family("main")
    prepare = family.add_task("prepare")
    forecast = family.add_task("forecast")
    mappings = [
        TaskMapping(prepare, "main.prepare", "prepare", "prepare"),
        TaskMapping(
            forecast, "main.forecast", "forecast", "forecast",
            {"member": {"type": "string", "required": True},
             "lead_seconds": {"type": "integer", "required": True},
             "domain": {"type": "string", "required": False, "default": "global"}},
            ("main.prepare",),
            "/synthetic/main/{member}/forecast",
        ),
    ]
    return suite, mappings


def export(suite, mappings, config, **overrides):
    arguments = dict(
        observability=config, application_revision="toy-app-revision-1",
        config_revision="config-1", mapping_version="1", generator_version="0.1.0",
        script_invoke_mode="external",
    )
    arguments.update(overrides)
    return export_definition_manifest(suite, mappings, **arguments)


def published_spec():
    pytest.importorskip("jsonschema")
    path = os.environ.get("SLEDRA_SPEC_DIR")
    if not path:
        pytest.skip("set SLEDRA_SPEC_DIR to a published Sledra 1.0.0 spec directory")
    return Path(path)


def test_disabled_does_not_load_contract_or_require_mapping():
    suite, _ = tree()
    assert export(suite, (), ObservabilityConfig(spec_dir="/missing")) is None


def test_enabled_requires_compatible_resources(tmp_path):
    suite, mappings = tree()
    with pytest.raises(ObservabilityConfigError, match="requires spec_dir"):
        export(suite, mappings, ObservabilityConfig(enabled=True))
    pytest.importorskip("jsonschema")
    with pytest.raises(ObservabilityConfigError, match="unavailable"):
        export(suite, mappings, ObservabilityConfig(enabled=True, spec_dir=str(tmp_path)))
    (tmp_path / "definition_manifest.schema.json").write_text("{}")
    with pytest.raises(ObservabilityConfigError, match="incompatible"):
        export(suite, mappings, ObservabilityConfig(enabled=True, spec_dir=str(tmp_path)))


def test_manifest_is_stable_and_matches_published_contract():
    suite, mappings = tree()
    config = ObservabilityConfig(enabled=True, spec_dir=str(published_spec()))
    first = export(suite, mappings, config)
    assert first == export(suite, list(reversed(mappings)), config)
    assert first["definition_id"] == "def_" + first["content_sha256"]
    assert first["tasks"][0]["depends_on"] == ["main.prepare"]
    assert first["tasks"][0]["engine_path_template"] == "/synthetic/main/{member}/forecast"
    assert first["extensions"]["takflow.generation"]["config_revision"] == "config-1"

    import jsonschema
    import json
    import unicodedata

    spec = json.loads((published_spec() / "definition_manifest.schema.json").read_text())
    jsonschema.validate(first, spec)
    content = {key: value for key, value in first.items() if key not in ("definition_id", "content_sha256")}
    raw = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    raw = unicodedata.normalize("NFC", raw).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    assert first["content_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    assert first["definition_id"] != export(suite, mappings, config, config_revision="config-2")["definition_id"]


def test_mapping_and_parameter_identity():
    suite, mappings = tree()
    config = ObservabilityConfig(enabled=True, spec_dir=str(published_spec()))
    with pytest.raises(ObservabilityConfigError, match="every generated task"):
        export(suite, mappings[:1], config)
    with pytest.raises(ObservabilityConfigError, match="task_key must be unique"):
        export(suite, [mappings[0], TaskMapping(mappings[1].node, "main.prepare", "forecast", "forecast")], config)
    optional_path = TaskMapping(mappings[1].node, "main.forecast", "forecast", "forecast",
                                {"member": {"type": "string", "required": False}},
                                ("main.prepare",), "/synthetic/{member}/forecast")
    with pytest.raises(ObservabilityConfigError, match="path parameters must be required"):
        export(suite, [mappings[0], optional_path], config)
    task = export(suite, mappings, config)["tasks"][0]
    assert expand_task_parameters(task, {"member": "e\u0301", "lead_seconds": 0}) == {
        "member": "é", "lead_seconds": 0, "domain": "global"
    }
    assert expand_task_parameters(task, {"member": "01", "lead_seconds": 0}) != expand_task_parameters(
        task, {"member": "02", "lead_seconds": 0})
    assert expand_task_parameters(task, {"member": "01", "lead_seconds": 0}) != expand_task_parameters(
        task, {"member": "01", "lead_seconds": 3600})
    for values, message in [
        ({"member": "01"}, "required parameter missing"),
        ({"member": "01", "lead_seconds": 0, "extra": 1}, "undeclared parameters"),
        ({"member": "01", "lead_seconds": True}, "invalid parameter"),
    ]:
        with pytest.raises(ObservabilityConfigError, match=message):
            expand_task_parameters(task, values)
