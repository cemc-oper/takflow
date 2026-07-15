"""
takflow 流程定义抽象层。

提供与后端无关的通用流程定义 API，包括节点抽象、引擎入口和钩子基础设施。
"""
from takflow.flow.backend import WorkflowBackend
from takflow.flow.hook import (
    BaseHookRegistry,
    HookFunction,
    create_hook_decorator,
)
from takflow.flow.node import Node, NodeType, WorkflowEngine

__all__ = [
    "WorkflowBackend",
    "Node",
    "NodeType",
    "WorkflowEngine",
    "BaseHookRegistry",
    "HookFunction",
    "create_hook_decorator",
    "register_hook",
]

# 为兼容旧路径 takflow.hooks.base 保留别名
register_hook = create_hook_decorator
