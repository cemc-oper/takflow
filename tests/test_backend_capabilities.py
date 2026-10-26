"""Generation-time coverage for the documented backend capability matrix."""
from __future__ import annotations

import importlib.util
import json

import pytest

from takflow.backends.ecflow import EcflowBackend
from takflow.backends.runtime import script_cmd_var_name, script_cmd_value
from takflow.backends.takler import TaklerBackend
from takflow.flow import WorkflowEngine


def _build_common_suite(engine: WorkflowEngine):
    suite = engine.Suite("capability")
    suite.add_variable("STRING", "value")
    suite.add_variables({"NUMBER": 3, "FLAG": True})
    suite.add_event("ready")
    suite.add_meter("progress", 0, 10)
    suite.add_limit("slots", 2)

    dated = suite.add_family("dated")
    dated.add_repeat_date("YMD", 20260101, 20260102)
    dated.set_defstatus_complete()
    dated.set_defstatus_queued()

    prepare = dated.add_task("prepare")
    prepare.add_event("started")
    prepare.add_inlimit("slots", tokens=2)
    prepare.add_time("00:30")

    run = dated.add_task("run")
    run.add_trigger("/capability/dated/prepare == complete")
    run.add_complete_trigger("/capability/dated/prepare")
    run.set_defstatus_complete()
    run.add_variable(
        script_cmd_var_name(engine),
        script_cmd_value(engine, "jobs", "run.ecf"),
    )
    return suite, dated, run


def _assert_tree_api(engine, suite, dated, run, suite_children):
    assert suite.name == "capability"
    assert dated.parent is suite
    assert run.parent is dated
    assert run in dated.children
    assert run.path == "/capability/dated/run"
    assert [child.name for child in suite.children] == suite_children
    assert [
        engine.backend.get_node_name(child)
        for child in engine.backend.list_children(suite)
    ] == suite_children


def test_ecflow_backend_capability_matrix(tmp_path):
    engine = WorkflowEngine(EcflowBackend())
    suite, dated, run = _build_common_suite(engine)
    suite.add_label("owner", "research")
    run.add_late(
        submitted=(0, 10),
        active=(0, 20),
        complete=(0, 30),
        complete_relative=True,
    )
    suite.add_family("daily").add_repeat_day(2)
    _assert_tree_api(engine, suite, dated, run, ["dated", "daily"])

    output = tmp_path / "capability.def"
    engine.save_suite(suite, output)
    text = output.read_text(encoding="utf-8")
    for expected in (
        "suite capability",
        "edit STRING 'value'",
        "edit NUMBER '3'",
        "edit FLAG 'True'",
        'label owner "research"',
        "event ready",
        "meter progress 0 10",
        "limit slots 2",
        "family dated",
        "defstatus queued",
        "repeat date YMD 20260101 20260102 1",
        "task prepare",
        "event started",
        "inlimit slots 2",
        "time 00:30",
        "task run",
        "defstatus complete",
        "late -s 00:10 -a 00:20 -c +00:30",
        "complete /capability/dated/prepare",
        "trigger /capability/dated/prepare == complete",
        "edit ECF_SCRIPT_CMD 'cat jobs/run.ecf'",
        "repeat day 2",
        "endsuite",
    ):
        assert expected in text


@pytest.mark.skipif(
    importlib.util.find_spec("takler") is None,
    reason="takler is not installed",
)
def test_takler_backend_capability_matrix(tmp_path):
    engine = WorkflowEngine(TaklerBackend())
    suite, dated, run = _build_common_suite(engine)
    _assert_tree_api(engine, suite, dated, run, ["dated"])

    output = tmp_path / "capability.json"
    engine.save_suite(suite, output)
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["kind"] == "takler.definition"
    assert document["schema_version"] == 1

    root = document["root"]
    assert root["name"] == "capability"
    assert root["type_id"] == "takler.flow"
    assert root["user_parameters"] == [
        {"name": "STRING", "value": "value"},
        {"name": "NUMBER", "value": 3},
        {"name": "FLAG", "value": True},
    ]
    assert root["events"] == [{"name": "ready", "initial_value": False}]
    assert root["meters"] == [
        {"name": "progress", "min_value": 0, "max_value": 10}
    ]
    assert root["limits"] == [{"name": "slots", "limit": 2}]

    dated_data = root["children"][0]
    assert dated_data["type_id"] == "takler.container"
    assert dated_data["default_node_status"] == "queued"
    assert dated_data["repeat"] == {
        "type_id": "takler.repeat.date",
        "name": "YMD",
        "start_date": "20260101",
        "end_date": "20260102",
        "step": 1,
    }

    prepare_data, run_data = dated_data["children"]
    assert prepare_data["type_id"] == "takler.shell"
    assert prepare_data["events"] == [{"name": "started", "initial_value": False}]
    assert prepare_data["in_limits"] == [
        {"limit_name": "slots", "node_path": None, "tokens": 2}
    ]
    assert prepare_data["times"] == [{"time": "00:30"}]
    assert run_data["default_node_status"] == "complete"
    assert run_data["trigger"] == "/capability/dated/prepare == complete"
    assert run_data["complete_trigger"] == "/capability/dated/prepare == complete"
    assert run_data["user_parameters"] == [
        {"name": "TAKLER_SCRIPT", "value": "jobs/run.sh"}
    ]
    assert run_data["script_path"] == "jobs/run.sh"
