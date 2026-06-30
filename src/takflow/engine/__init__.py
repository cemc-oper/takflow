"""
工作流引擎抽象层。

提供统一的节点操作接口，屏蔽 ecflow 和 takler 的 API 差异。
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from takflow.engine.backend import WorkflowBackend


class NodeType(str, Enum):
    """
    引擎节点类型。
    """
    SUITE = "suite"
    FAMILY = "family"
    TASK = "task"


class Node:
    """
    通用工作流节点。

    包装底层 ecflow.Suite/Family/Task 或 takler.Flow/NodeContainer/Task，
    对外提供类似 ecflow 的树形构建 API。

    Attributes
    ----------
    raw : Any
        底层引擎节点对象。
    node_type : NodeType
        节点类型。
    engine : WorkflowEngine
        所属的引擎实例。
    name : str
        节点名称。
    parent : Node | None
        父节点。
    children : list[Node]
        子节点列表。
    path : str
        节点完整路径。
    """

    def __init__(
        self,
        raw_node: Any,
        node_type: NodeType,
        engine: "WorkflowEngine",
    ):
        self._raw = raw_node
        self._type = node_type
        self._engine = engine
        self._parent: Optional["Node"] = None
        self._children: List["Node"] = []

    @property
    def raw(self) -> Any:
        return self._raw

    @property
    def node_type(self) -> NodeType:
        return self._type

    @property
    def engine(self) -> "WorkflowEngine":
        return self._engine

    @property
    def name(self) -> str:
        return self._engine.backend.get_node_name(self._raw)

    @property
    def parent(self) -> Optional["Node"]:
        return self._parent

    @property
    def children(self) -> List["Node"]:
        return list(self._children)

    @property
    def path(self) -> str:
        return self._engine.backend.node_path(self)

    def __enter__(self) -> "Node":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    def __repr__(self) -> str:
        return f"Node({self._type.value}, {self.name})"

    # ------------------------------------------------------------------
    # 树挂载
    # ------------------------------------------------------------------
    def add_family(self, family: Union["Node", str]) -> "Node":
        """
        挂载 Family 节点。

        Parameters
        ----------
        family : Node | str
            已创建的 Family 节点，或要创建并挂载的 Family 名称。

        Returns
        -------
        Node
            挂载后的 Family 节点。
        """
        if isinstance(family, str):
            family = self._engine.Family(family)
        self._engine.backend.add_family(self, family)
        family._parent = self
        self._children.append(family)
        return family

    def add_task(self, task: Union["Node", str]) -> "Node":
        """
        挂载 Task 节点。

        Parameters
        ----------
        task : Node | str
            已创建的 Task 节点，或要创建并挂载的 Task 名称。

        Returns
        -------
        Node
            挂载后的 Task 节点。
        """
        if isinstance(task, str):
            task = self._engine.Task(task)
        self._engine.backend.add_task(self, task)
        task._parent = self
        self._children.append(task)
        return task

    # ------------------------------------------------------------------
    # 节点属性（委托给后端）
    # ------------------------------------------------------------------
    def add_variable(
        self,
        name: str,
        value: Union[str, int, float, bool],
    ) -> "Node":
        """添加单个变量。"""
        self._engine.backend.add_variable(self, name, value)
        return self

    def add_variables(
        self,
        variables: Dict[str, Union[str, int, float, bool]],
    ) -> "Node":
        """批量添加变量。"""
        self._engine.backend.add_variables(self, variables)
        return self

    def add_trigger(self, expression: str) -> "Node":
        """添加触发器。"""
        self._engine.backend.add_trigger(self, expression)
        return self

    def add_complete_trigger(self, expression: str) -> "Node":
        """添加完成触发器。"""
        self._engine.backend.add_complete_trigger(self, expression)
        return self

    def add_event(self, name: str) -> "Node":
        """添加事件。"""
        self._engine.backend.add_event(self, name)
        return self

    def add_meter(
        self,
        name: str,
        min_value: int,
        max_value: int,
    ) -> "Node":
        """添加标尺。"""
        self._engine.backend.add_meter(self, name, min_value, max_value)
        return self

    def add_limit(self, name: str, limit: int) -> "Node":
        """添加限制。"""
        self._engine.backend.add_limit(self, name, limit)
        return self

    def add_inlimit(self, limit_name: str, tokens: int = 1) -> "Node":
        """添加 in-limit。"""
        self._engine.backend.add_inlimit(self, limit_name, tokens)
        return self

    def add_repeat_date(
        self,
        name: str,
        start_date: int,
        end_date: int,
    ) -> "Node":
        """添加日期重复。"""
        self._engine.backend.add_repeat_date(self, name, start_date, end_date)
        return self

    def add_repeat_day(self, step: int = 1) -> "Node":
        """添加按天重复。"""
        self._engine.backend.add_repeat_day(self, step)
        return self

    def add_time(self, time_str: str) -> "Node":
        """添加时间属性。"""
        self._engine.backend.add_time(self, time_str)
        return self

    def set_defstatus_complete(self) -> "Node":
        """设置默认状态为 complete。"""
        self._engine.backend.set_defstatus_complete(self)
        return self

    def set_defstatus_queued(self) -> "Node":
        """设置默认状态为 queued。"""
        self._engine.backend.set_defstatus_queued(self)
        return self


class WorkflowEngine:
    """
    通用工作流引擎。

    作为树形构建器的入口，提供类似 ecflow 的工厂方法：
    ``engine.Suite("name")``、``engine.Family("name")``、``engine.Task("name")``。

    Attributes
    ----------
    backend : WorkflowBackend
        底层后端实例。
    backend_type : str
        后端类型标识。
    """

    def __init__(self, backend: WorkflowBackend):
        self._backend = backend

    @property
    def backend(self) -> WorkflowBackend:
        return self._backend

    @property
    def backend_type(self) -> str:
        return self._backend.backend_type

    def Suite(self, name: str) -> Node:
        """创建 Suite / Flow 节点。"""
        raw = self._backend.create_suite(name)
        return Node(raw, NodeType.SUITE, self)

    def Family(self, name: str) -> Node:
        """创建 Family / NodeContainer 节点。"""
        raw = self._backend.create_family(name)
        return Node(raw, NodeType.FAMILY, self)

    def Task(self, name: str) -> Node:
        """创建 Task 节点。"""
        raw = self._backend.create_task(name)
        return Node(raw, NodeType.TASK, self)

    def save_suite(self, suite: Node, output_path: Path) -> None:
        """保存工作流定义到文件。"""
        self._backend.save_suite(suite, output_path)


__all__ = [
    "Node",
    "NodeType",
    "WorkflowEngine",
    "WorkflowBackend",
]
