"""Standard pipeline against the real optional takler definition contract."""
import json
import pytest

pytest.importorskip("takler")

from test_build import application, data, resources
from takflow.build import build


def test_takler_pipeline_uses_real_native_json(tmp_path, resources):
    with application(resources).prepare(data(tmp_path / "out", "takler")) as context:
        result = build(context)
    assert result.complete
    definition = json.loads(result.workflow_output.read_text())
    assert definition["root"]["name"] == "test_workflow"
    assert any(item["code"] == "GEN_TAKLER_DEFINITION_VALID" for item in result.diagnostics)
