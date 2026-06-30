"""
takler 后端实现。

将统一后端接口映射到 takler Python API。
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Union

from takler.core import Bunch, Flow, NodeContainer, RepeatDate, NodeStatus
from takler.tasks.shell import ShellScriptTask

from takflow.engine.backend import WorkflowBackend
from takflow.engine import Node, NodeType


class TaklerBackend(WorkflowBackend):
    """
    takler 工作流引擎后端。
    """

    def __init__(self, host: str = None, port: Union[int, str] = None):
        self.host = host
        self.port = port
        self._bunch = Bunch(name="mcv", host=host, port=port)

    @property
    def backend_type(self) -> str:
        return "takler"

    def create_suite(self, name: str) -> Any:
        return Flow(name)

    def create_family(self, name: str) -> Any:
        return NodeContainer(name)

    def create_task(self, name: str) -> Any:
        return ShellScriptTask(name)

    def add_family(self, parent: Node, family: Node) -> None:
        parent.raw.append_child(family.raw)

    def add_task(self, parent: Node, task: Node) -> None:
        parent.raw.append_child(task.raw)

    def _maybe_set_script_path(
        self,
        node: Node,
        name: str,
        value: Union[str, int, float, bool],
    ) -> None:
        """
        当变量名为 TAKLER_SCRIPT 时，同步设置 ShellScriptTask.script_path。

        takler 的 ``ShellScriptTask`` 在运行时需要 ``script_path`` 属性来生成
        作业脚本。业务代码通过 ``add_variable("TAKLER_SCRIPT", path)`` 设置脚本
        路径，因此需要在此处把路径同步到底层 task 对象。
        """
        if name == "TAKLER_SCRIPT" and isinstance(value, (str, Path)):
            raw = node.raw
            if isinstance(raw, ShellScriptTask):
                raw.script_path = str(value)

    def add_variable(
        self,
        node: Node,
        name: str,
        value: Union[str, int, float, bool],
    ) -> None:
        node.raw.add_parameter(name, value)
        self._maybe_set_script_path(node, name, value)

    def add_variables(
        self,
        node: Node,
        variables: Dict[str, Union[str, int, float, bool]],
    ) -> None:
        node.raw.add_parameter(variables)
        for name, value in variables.items():
            self._maybe_set_script_path(node, name, value)

    def add_trigger(self, node: Node, expression: str) -> None:
        node.raw.add_trigger(expression)

    def add_complete_trigger(self, node: Node, expression: str) -> None:
        # takler 解析器不支持裸节点路径作为 complete trigger，
        # 对仅包含节点路径/变量路径的表达式自动补全为 "== complete"
        stripped = expression.strip()
        if not any(op in stripped for op in ("==", "!=", "<<", ">", "<=", ">=")):
            stripped = f"{stripped} == complete"
        node.raw.add_complete_trigger(stripped)

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
        node.raw.add_in_limit(limit_name, tokens=tokens)

    def add_late(
        self,
        node: Node,
        submitted: tuple[int, int] | None = None,
        active: tuple[int, int] | None = None,
        complete: tuple[int, int] | None = None,
        complete_relative: bool = False,
    ) -> None:
        # takler 未实现 Late；现阶段直接忽略。
        return

    def add_repeat_date(
        self,
        node: Node,
        name: str,
        start_date: int,
        end_date: int,
    ) -> None:
        repeat = RepeatDate(name, start_date, end_date)
        node.raw.add_repeat(repeat)

    def add_repeat_day(self, node: Node, step: int = 1) -> None:
        # takler 没有直接的 RepeatDay，先以变量形式保留配置
        node.raw.add_parameter("REPEAT_DAY_STEP", step)

    def add_time(self, node: Node, time_str: str) -> None:
        node.raw.add_time(time_str)

    def set_defstatus_complete(self, node: Node) -> None:
        node.raw.set_default_node_status(NodeStatus.complete)

    def set_defstatus_queued(self, node: Node) -> None:
        node.raw.set_default_node_status(NodeStatus.queued)

    def save_suite(self, suite: Node, output_path: Path) -> None:
        self._bunch.add_flow(suite.raw)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        data = self._bunch.to_dict()
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def node_path(self, node: Node) -> str:
        return node.raw.node_path

    def list_children(self, node: Node) -> List[Any]:
        return node.raw.children

    def get_node_name(self, raw_node: Any) -> str:
        return raw_node.name
