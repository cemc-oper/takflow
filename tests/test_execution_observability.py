"""P3-01: public opt-in config without v1 registration or target-host IO."""

import json
import subprocess
import sys

import pytest
from pydantic import ValidationError

from takflow.config import (
    BaseWorkflowConfig,
    ObservabilityConfig,
    load_config_from_file,
)
from takflow.toolkit import execution_environment
from takflow.toolkit.observability import export_definition_manifest


def settings(**overrides):
    return (
        dict(
            enabled=True,
            mode="execution-v2",
            recorder_bin="/opt/sledra/bin/sledra",
            bash_library="/opt/sledra/share/sledra-execution.sh",
            root="/shared/observations/synthetic",
        )
        | overrides
    )


def test_disabled_and_existing_enabled_configs_keep_legacy_semantics():
    assert ObservabilityConfig().enabled is False
    assert ObservabilityConfig(enabled=True).mode == "legacy-v1"
    for config in [
        ObservabilityConfig(),
        ObservabilityConfig(enabled=True),
        ObservabilityConfig(mode="execution-v2", root="relative-unused"),
    ]:
        assert execution_environment(config) == {}


@pytest.mark.parametrize("field", ["recorder_bin", "bash_library", "root"])
@pytest.mark.parametrize(
    "bad", [None, "", "relative/path", "/absolute\npath", "/a\x00b", "/a\x7fb"]
)
def test_enabled_execution_requires_absolute_target_paths(field, bad):
    with pytest.raises(ValidationError, match=field):
        ObservabilityConfig(**settings(**{field: bad}))


def test_unknown_mode_is_rejected():
    with pytest.raises(ValidationError):
        ObservabilityConfig(mode="execution")


def test_new_mode_has_no_legacy_export_or_host_filesystem_requirement(
    monkeypatch, tmp_path
):
    from takflow.toolkit import observability

    def reject_legacy(*args):
        pytest.fail("Execution must not load the legacy schema")

    monkeypatch.setattr(observability, "_validator", reject_legacy)
    config = ObservabilityConfig(**settings(root=str(tmp_path / "not-created")))
    assert (
        export_definition_manifest(
            None,
            (),
            observability=config,
            application_revision="",
            config_revision="",
            mapping_version="",
            generator_version="",
            script_invoke_mode="inline",
        )
        is None
    )
    assert execution_environment(config) == {
        "SLEDRA_MODE": "execution-v2",
        "SLEDRA_BIN": config.recorder_bin,
        "SLEDRA_BASH_LIBRARY": config.bash_library,
        "SLEDRA_ROOT": config.root,
    }
    assert list(tmp_path.iterdir()) == []


def test_yaml_workflow_inherits_config_and_preserves_literal_paths(tmp_path):
    path = tmp_path / "config.yaml"
    values = dict(
        project_base_dir="/program",
        run_base_dir="/business",
        workload={"workload_type": "shell"},
        observability=settings(root="/shared/a space/$(touch literal);'quote'"),
    )
    # JSON is a YAML subset; this tests the real public loader too.
    path.write_text(json.dumps(values))
    workflow = load_config_from_file(str(path))
    assert isinstance(workflow, BaseWorkflowConfig)
    assert workflow.observability.spec_dir is None
    assert (
        execution_environment(workflow.observability)["SLEDRA_ROOT"]
        == values["observability"]["root"]
    )
    assert not (tmp_path / "literal").exists()


def test_public_import_does_not_require_jsonschema_or_sledra():
    # Block optional dependencies in a fresh process, including transitive imports.
    script = """
import sys
class Block:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'jsonschema', 'sledra_analysis', 'ecflow'}:
            raise AssertionError(fullname)
sys.meta_path.insert(0, Block())
from takflow.config import ObservabilityConfig
from takflow.toolkit import execution_environment
config = ObservabilityConfig(**SETTINGS)
assert execution_environment(config)['SLEDRA_MODE'] == 'execution-v2'
""".replace("SETTINGS", repr(settings()))
    subprocess.run([sys.executable, "-c", script], check=True, capture_output=True)
