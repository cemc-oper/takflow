"""Direct regression tests for the backend-neutral flow node abstraction."""
from __future__ import annotations

import importlib.util

import pytest

from takflow.backends.ecflow import EcflowBackend
from takflow.backends.runtime import script_cmd_value, script_cmd_var_name
from takflow.backends.takler import TaklerBackend
from takflow.flow import NodeType, WorkflowEngine


@pytest.fixture(
    params=[
        pytest.param(EcflowBackend, id="ecflow"),
        pytest.param(
            TaklerBackend,
            id="takler",
            marks=pytest.mark.skipif(
                importlib.util.find_spec("takler") is None,
                reason=(
                    "takler is not installed; install the optional takler "
                    "dependency to run shared backend cases"
                ),
            ),
        ),
    ]
)
def engine(request) -> WorkflowEngine:
    return WorkflowEngine(request.param())


@pytest.mark.parametrize(
    ("factory_name", "node_type"),
    [
        ("Suite", NodeType.SUITE),
        ("Family", NodeType.FAMILY),
        ("Task", NodeType.TASK),
    ],
)
def test_engine_factories_create_detached_nodes(engine, factory_name, node_type):
    node = getattr(engine, factory_name)("node")

    assert node.name == "node"
    assert node.node_type is node_type
    assert node.engine is engine
    assert node.raw is not None
    assert node.parent is None
    assert node.children == []
    assert node.path == "/node"


def test_string_creation_builds_wrapper_and_backend_trees(engine):
    suite = engine.Suite("suite")
    first = suite.add_family("first")
    second = suite.add_family("second")
    task = first.add_task("run")

    assert first.node_type is NodeType.FAMILY
    assert second.node_type is NodeType.FAMILY
    assert task.node_type is NodeType.TASK
    assert suite.parent is None
    assert first.parent is suite
    assert second.parent is suite
    assert task.parent is first
    assert suite.children == [first, second]
    assert first.children == [task]
    assert second.children == []
    assert suite.path == "/suite"
    assert first.path == "/suite/first"
    assert task.path == "/suite/first/run"
    assert [
        engine.backend.get_node_name(child)
        for child in engine.backend.list_children(suite)
    ] == ["first", "second"]

    children_snapshot = suite.children
    children_snapshot.clear()
    assert suite.children == [first, second]


def test_precreated_nodes_can_be_mounted(engine):
    suite = engine.Suite("suite")
    family = engine.Family("family")
    task = engine.Task("task")

    assert suite.add_family(family) is family
    assert family.add_task(task) is task
    assert family.parent is suite
    assert task.parent is family
    assert suite.children == [family]
    assert family.children == [task]
    assert task.path == "/suite/family/task"
    assert engine.backend.list_children(suite) == [family.raw]
    assert engine.backend.list_children(family) == [task.raw]


def test_common_capability_subset_supports_chaining_and_save(engine, tmp_path):
    suite = engine.Suite("common")
    assert suite.add_variable("STRING", "value") is suite
    assert suite.add_variables({"NUMBER": 3, "FLAG": True}) is suite
    assert suite.add_event("ready") is suite
    assert suite.add_meter("progress", 0, 10) is suite
    assert suite.add_limit("slots", 2) is suite

    dated = suite.add_family("dated")
    assert dated.add_repeat_date("YMD", 20260101, 20260102) is dated
    assert dated.set_defstatus_complete() is dated
    assert dated.set_defstatus_queued() is dated

    prepare = dated.add_task("prepare")
    assert prepare.add_event("started") is prepare
    assert prepare.add_inlimit("slots") is prepare
    assert prepare.add_time("00:30") is prepare

    run = dated.add_task("run")
    result = (
        run.add_trigger("/common/dated/prepare == complete")
        .add_complete_trigger("/common/dated/prepare")
        .set_defstatus_complete()
        .add_variable(
            script_cmd_var_name(engine),
            script_cmd_value(engine, "jobs", "run.ecf"),
        )
    )

    assert result is run
    assert run.path == "/common/dated/run"
    suffix = "def" if engine.backend_type == "ecflow" else "json"
    output = tmp_path / f"common.{suffix}"
    assert engine.save_suite(suite, output) is None
    assert output.is_file()
    assert output.stat().st_size > 0
