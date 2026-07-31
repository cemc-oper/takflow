"""toyflow 的 hook 定义。

演示 takflow 钩子系统的两层用法：

1. **应用自有 engine hook 注册表**：takflow 只提供通用基类
   （``BaseHookRegistry`` + ``create_hook_decorator``），hook 点的词汇表
   由应用自己定义——toyflow 在这里声明 ``AFTER_FORECAST`` hook 点，
   扩展包（相当于 mcv-oper-workflow 的角色）可以在预报任务之后注入任务。

2. **takflow 共享 credential hook**：注册到 takflow 的全局注册表，
   渲染 ``credential.sh`` 的一个片段。

hook 在 **import 时** 通过装饰器注册，因此 CLI 在构建流程前 import 本模块即可。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, Optional

from takflow.flow.hook import BaseHookRegistry, create_hook_decorator
from takflow.toolkit.credential import (
    CredentialContext,
    CredentialHookPoint,
    register_credential_hook,
)

if TYPE_CHECKING:
    from takflow.flow import Node, WorkflowEngine


# ---------------------------------------------------------------------------
# 1. 应用自有 engine hook
# ---------------------------------------------------------------------------

class EngineHookPoint(str, Enum):
    """toyflow 的 engine hook 点（应用词汇表，takflow 不预定义）。"""

    #: 预报任务构建完成后触发，可向 main family 注入额外任务。
    AFTER_FORECAST = "main.after_forecast"


@dataclass
class EngineHookContext:
    """engine hook 的上下文。"""

    node: "Node"
    engine: "WorkflowEngine"
    kwargs: Dict[str, Any] = field(default_factory=dict)


class EngineHookRegistry(BaseHookRegistry[EngineHookContext, None]):
    """toyflow engine hook 注册表（单例）。"""

    _instance: Optional["EngineHookRegistry"] = None

    @classmethod
    def get_instance(cls) -> "EngineHookRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


def get_engine_hook_registry() -> EngineHookRegistry:
    return EngineHookRegistry.get_instance()


register_engine_hook = create_hook_decorator(get_engine_hook_registry)


@register_engine_hook(EngineHookPoint.AFTER_FORECAST, priority=10)
def add_verify_task(context: EngineHookContext) -> None:
    """在预报任务之后注入一个检验任务（演示扩展点的效果）。

    扩展包注入任务时通常也同时提供对应的作业模板
    （见 ``resources/jobs/main/verify.sh.j2``）。
    """
    from takflow.backends.runtime import script_cmd_value, script_cmd_var_name

    main_family = context.node
    verify = main_family.add_task("verify")
    verify.add_trigger("forecast == complete")

    jobs_dir = context.kwargs["jobs_dir"]
    suffix = ".ecf" if context.engine.backend_type == "ecflow" else ".sh"
    verify.add_variable(
        script_cmd_var_name(context.engine),
        script_cmd_value(context.engine, jobs_dir, f"main/verify{suffix}"),
    )


# ---------------------------------------------------------------------------
# 2. takflow 共享 credential hook
# ---------------------------------------------------------------------------

@register_credential_hook(CredentialHookPoint.RENDER, priority=10)
def render_toyflow_credential(context: CredentialContext) -> str:
    """把 credential.yaml 中的 toyflow 段渲染为 credential.sh 片段。"""
    toyflow = context.credential.get("toyflow", {})
    return "\n".join(
        [
            "# toyflow API 凭证",
            f'export TOYFLOW_API_HOST="{toyflow.get("api_host", "")}"',
            f'export TOYFLOW_API_KEY="{toyflow.get("api_key", "")}"',
        ]
    )
