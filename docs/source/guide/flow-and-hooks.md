# 流程与钩子

## 定义运行流程

运行流程通过 `takflow.flow` 中的抽象 API 定义，与后端无关（对应 toyflow 的 `src/toyflow/flow.py`）：

```python
from takflow.flow import WorkflowEngine
from takflow.backends.ecflow import EcflowBackend
from takflow.backends.runtime import common_setting, set_runtime, set_scheduling

engine = WorkflowEngine(EcflowBackend())

suite = engine.Suite(config.workflow_name)

# 资源载体(提交命令)+ 引擎公共设置
set_runtime(suite, config.workload, engine=engine)
suite.add_variables(common_setting(engine=engine))

# admin/ 运维开关
fm_admin = suite.add_family("admin")
fm_admin.set_defstatus_complete()
fm_admin.add_task("toggles")

# time_triggers/ 时间调度
fm_time = suite.add_family("time_triggers")
set_scheduling(fm_time, config.scheduling, engine=engine)
fm_time.add_task("00").add_time("00:00")

# obs -> main -> post 依赖链
fm_obs = suite.add_family("obs")
fm_obs.add_task("prepare")

fm_main = suite.add_family("main")
fcst = fm_main.add_task("forecast")
fcst.add_trigger(f"/{config.workflow_name}/obs/prepare == complete")

fm_post = suite.add_family("post")
plot = fm_post.add_task("plot")
plot.add_trigger(f"/{config.workflow_name}/main/forecast == complete")
```

同一套节点树可以通过不同的后端输出为 ecFlow `.def` 或 takler JSON。

## 扩展流程：钩子

takflow 只提供通用基类（`BaseHookRegistry` + `create_hook_decorator`），hook 点的词汇表由应用
自己定义（对应 toyflow 的 `src/toyflow/hooks.py`）：

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from takflow.flow import Node, WorkflowEngine
from takflow.flow.hook import BaseHookRegistry, create_hook_decorator


class EngineHookPoint(str, Enum):
    """应用自己的 hook 点(takflow 不预定义)。"""

    AFTER_FORECAST = "main.after_forecast"


@dataclass
class EngineHookContext:
    """engine hook 的上下文:当前 node、engine 及附加参数。"""

    node: Node
    engine: WorkflowEngine
    kwargs: Dict[str, Any] = field(default_factory=dict)


class EngineHookRegistry(BaseHookRegistry[EngineHookContext, None]):
    """应用自有的 engine hook 注册表(单例)。"""

    _instance: Optional["EngineHookRegistry"] = None

    @classmethod
    def get_instance(cls) -> "EngineHookRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


register_engine_hook = create_hook_decorator(EngineHookRegistry.get_instance)


@register_engine_hook(EngineHookPoint.AFTER_FORECAST, priority=10)
def add_verify_task(context: EngineHookContext) -> None:
    """在预报任务之后注入一个检验任务。"""
    verify = context.node.add_task("verify")
    verify.add_trigger("forecast == complete")
```

hook 在 **import 时** 通过装饰器注册；流程构建代码在相应位置执行：

```python
context = EngineHookContext(node=fm_main, engine=engine, kwargs={})
EngineHookRegistry.get_instance().execute(EngineHookPoint.AFTER_FORECAST, context)
```

这也是 `mcv-oper-workflow` 等"业务扩展包"的接入方式：扩展包的 CLI 先 import 自己的 hooks 模块
触发注册，再调用基础包的流程构建函数。
