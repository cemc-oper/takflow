"""
工作流后端抽象基类。

定义所有工作流引擎后端必须实现的接口，屏蔽 ecflow 与 takler 的底层差异。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Union


class WorkflowBackend(ABC):
    """
    工作流引擎后端抽象基类。

    所有后端（ecflow、takler）必须实现此接口。接口中的 ``node`` 参数
    均为统一的 ``Node`` 对象，具体底层节点通过 ``node.raw`` 获取。
    """

    @property
    @abstractmethod
    def backend_type(self) -> str:
        """返回后端类型标识，如 ``"ecflow"``、``"takler"``。"""
        ...

    # ------------------------------------------------------------------
    # 节点创建
    # ------------------------------------------------------------------
    @abstractmethod
    def create_suite(self, name: str) -> Any:
        """创建 Suite / Flow 底层节点，不挂载到任何父节点。"""
        ...

    @abstractmethod
    def create_family(self, name: str) -> Any:
        """创建 Family / NodeContainer 底层节点，不挂载到任何父节点。"""
        ...

    @abstractmethod
    def create_task(self, name: str) -> Any:
        """创建 Task 底层节点，不挂载到任何父节点。"""
        ...

    # ------------------------------------------------------------------
    # 树挂载
    # ------------------------------------------------------------------
    @abstractmethod
    def add_family(self, parent: "Node", family: "Node") -> None:
        """将 family 节点挂载到 parent 下。"""
        ...

    @abstractmethod
    def add_task(self, parent: "Node", task: "Node") -> None:
        """将 task 节点挂载到 parent 下。"""
        ...

    # ------------------------------------------------------------------
    # 节点属性
    # ------------------------------------------------------------------
    @abstractmethod
    def add_variable(
        self,
        node: "Node",
        name: str,
        value: Union[str, int, float, bool],
    ) -> None:
        """为节点添加单个变量。"""
        ...

    @abstractmethod
    def add_variables(
        self,
        node: "Node",
        variables: Dict[str, Union[str, int, float, bool]],
    ) -> None:
        """为节点批量添加变量。"""
        ...

    @abstractmethod
    def add_trigger(self, node: "Node", expression: str) -> None:
        """添加触发器。"""
        ...

    @abstractmethod
    def add_complete_trigger(self, node: "Node", expression: str) -> None:
        """添加完成触发器。"""
        ...

    @abstractmethod
    def add_event(self, node: "Node", name: str) -> None:
        """添加事件。"""
        ...

    @abstractmethod
    def add_meter(
        self,
        node: "Node",
        name: str,
        min_value: int,
        max_value: int,
    ) -> None:
        """添加标尺。"""
        ...

    @abstractmethod
    def add_limit(self, node: "Node", name: str, limit: int) -> None:
        """添加限制。"""
        ...

    @abstractmethod
    def add_inlimit(self, node: "Node", limit_name: str, tokens: int = 1) -> None:
        """添加 in-limit。"""
        ...

    @abstractmethod
    def add_late(
        self,
        node: "Node",
        submitted: tuple[int, int] | None = None,
        active: tuple[int, int] | None = None,
        complete: tuple[int, int] | None = None,
        complete_relative: bool = False,
    ) -> None:
        """添加 late 监控属性（ecflow 后端实现；takler 后端可 no-op）。"""
        ...

    @abstractmethod
    def add_repeat_date(
        self,
        node: "Node",
        name: str,
        start_date: int,
        end_date: int,
    ) -> None:
        """添加日期重复。"""
        ...

    @abstractmethod
    def add_repeat_day(self, node: "Node", step: int = 1) -> None:
        """添加按天重复。"""
        ...

    @abstractmethod
    def add_time(self, node: "Node", time_str: str) -> None:
        """添加时间属性。"""
        ...

    @abstractmethod
    def set_defstatus_complete(self, node: "Node") -> None:
        """设置默认状态为 complete。"""
        ...

    @abstractmethod
    def set_defstatus_queued(self, node: "Node") -> None:
        """设置默认状态为 queued。"""
        ...

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    @abstractmethod
    def save_suite(self, suite: "Node", output_path: Path) -> None:
        """保存工作流定义到文件。"""
        ...

    @abstractmethod
    def node_path(self, node: "Node") -> str:
        """获取节点完整路径。"""
        ...

    @abstractmethod
    def list_children(self, node: "Node") -> List[Any]:
        """列出节点的底层子节点。"""
        ...

    @abstractmethod
    def get_node_name(self, raw_node: Any) -> str:
        """获取底层节点名称。"""
        ...
