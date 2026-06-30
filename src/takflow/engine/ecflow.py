"""
ecflow 后端实现。

将统一后端接口映射到 light_ecflow API（一个纯 Python 的 ecflow .def 生成库）。
"""
from pathlib import Path
from typing import Any, Dict, List, Union

from light_ecflow import Defs, Suite, Family, Task, RepeatDate, RepeatDay, Clock, DState

from takflow.engine.backend import WorkflowBackend
from takflow.engine import Node, NodeType


class EcflowBackend(WorkflowBackend):
    """
    ecflow 工作流引擎后端。
    """

    @property
    def backend_type(self) -> str:
        return "ecflow"

    def create_suite(self, name: str) -> Any:
        return Suite(name)

    def create_family(self, name: str) -> Any:
        return Family(name)

    def create_task(self, name: str) -> Any:
        return Task(name)

    def add_family(self, parent: Node, family: Node) -> None:
        parent.raw.add_family(family.raw)

    def add_task(self, parent: Node, task: Node) -> None:
        parent.raw.add_task(task.raw)

    def add_variable(
        self,
        node: Node,
        name: str,
        value: Union[str, int, float, bool],
    ) -> None:
        node.raw.add_variable(name, str(value))

    def add_variables(
        self,
        node: Node,
        variables: Dict[str, Union[str, int, float, bool]],
    ) -> None:
        node.raw.add_variable({k: str(v) for k, v in variables.items()})

    def add_trigger(self, node: Node, expression: str) -> None:
        node.raw.add_trigger(expression)

    def add_complete_trigger(self, node: Node, expression: str) -> None:
        node.raw.add_complete(expression)

    def add_event(self, node: Node, name: str) -> None:
        node.raw.add_event(name)

    def add_meter(
        self,
        node: Node,
        name: str,
        min_value: int,
        max_value: int,
    ) -> None:
        node.raw.add_meter(name, min_value, max_value)

    def add_limit(self, node: Node, name: str, limit: int) -> None:
        node.raw.add_limit(name, limit)

    def add_inlimit(self, node: Node, limit_name: str, tokens: int = 1) -> None:
        node.raw.add_inlimit(limit_name)

    def add_repeat_date(
        self,
        node: Node,
        name: str,
        start_date: int,
        end_date: int,
    ) -> None:
        node.raw.add_repeat(RepeatDate(name, start_date, end_date))

    def add_repeat_day(self, node: Node, step: int = 1) -> None:
        node.raw.add_clock(Clock(True))
        node.raw.add_repeat(RepeatDay(step))

    def add_time(self, node: Node, time_str: str) -> None:
        node.raw.add_time(time_str)

    def set_defstatus_complete(self, node: Node) -> None:
        node.raw.add_defstatus(DState.complete)

    def set_defstatus_queued(self, node: Node) -> None:
        node.raw.add_defstatus(DState.queued)

    def save_suite(self, suite: Node, output_path: Path) -> None:
        defs = Defs()
        defs.add_suite(suite.raw)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        defs.save_as_defs(str(output_path))

    def node_path(self, node: Node) -> str:
        return node.raw.get_abs_node_path()

    def list_children(self, node: Node) -> List[Any]:
        return list(node.raw.nodes)

    def get_node_name(self, raw_node: Any) -> str:
        return raw_node.name()
