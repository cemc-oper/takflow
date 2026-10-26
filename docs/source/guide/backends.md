# 后端与资源载体

## 选择后端

`takflow` 通过 `backends/` 提供具体后端实现。应用通常按 `workflow_mode` 从映射表中取后端类，
切换后端只需更换 `WorkflowEngine` 构造参数（对应 toyflow 的 `src/toyflow/generate.py`）：

```python
from pathlib import Path

from takflow.flow import WorkflowEngine
from takflow.backends.ecflow import EcflowBackend
from takflow.backends.takler import TaklerBackend

_BACKEND_MAP = {
    "ecflow": EcflowBackend,
    "takler": TaklerBackend,
}
_DEFAULT_SUFFIX = {
    "ecflow": ".def",
    "takler": ".json",
}

mode = config.workflow_mode
engine = WorkflowEngine(_BACKEND_MAP[mode]())
suite = create_suite(config, engine=engine)  # 节点树构建见"流程与钩子"

output_path = Path(
    config.output_repo_base_dir,
    f"{config.workflow_name}{_DEFAULT_SUFFIX[mode]}",
)
engine.save_suite(suite, output_path)
```

## 后端能力矩阵

当前只有 `ecflow` 和 `takler` 两个 `WorkflowBackend`。`shell` 是应用的顺序脚本生成模式，
不实例化工作流后端，也不应列为第三种后端。

下表只描述**生成期公共 API 的当前契约**，不代表已在 HPC 调度器中实跑。状态含义：

- **支持**：操作已实现，并有当前生成或 definition 契约测试覆盖；
- **显式不支持**：调用公共 API 会稳定抛出 `NotImplementedError`，不做静默忽略或模拟；
- **语义不同**：操作存在，但输入、输出或附加行为不能直接视为跨后端等价，可与“支持”并列。

“支持”的验证依据是 `tests/test_backend_capabilities.py`、
`tests/test_takler_current_contract.py` 以及现有 toyflow/ecFlow 生成测试；未覆盖的运行时能力不在此表中
外推。

| `WorkflowBackend` / `Node` 公共操作 | ecFlow | takler | 当前边界 |
|---|---|---|---|
| `create_suite/family/task`，`Node.add_family/add_task` | 支持 | 支持 | 分别映射为 Suite/Family/Task 与 Flow/NodeContainer/ShellScriptTask |
| `Node.name/parent/children/path`，后端名称、路径和子节点查询 | 支持 | 支持 | 节点路径使用 `/suite/family/task` 形式；parent/children 包装关系由公共 `Node` 层维护 |
| `add_variable` / `add_variables` | 支持；语义不同 | 支持；语义不同 | ecFlow 将值转成字符串；takler 在 definition 中保留字符串、整数和布尔值类型 |
| `add_trigger` | 支持 | 支持 | 表达式交给各自引擎；不承诺两种引擎的全部表达式语法等价 |
| `add_complete_trigger` | 支持 | 支持；语义不同 | takler 对裸节点/变量路径自动补 `== complete`；ecFlow 按输入写出 complete 表达式 |
| `add_event` | 支持 | 支持 | 当前覆盖事件名称的生成与 definition 导出 |
| `add_label` | 支持 | **显式不支持** | takler 抛出 `takler backend does not support labels (ecflow-only attribute)` |
| `add_meter` | 支持 | 支持 | 当前覆盖名称及最小值、最大值 |
| `add_limit` / `add_inlimit` | 支持 | 支持 | tokens 均保留；takler load 契约还会解析并绑定 limit 引用 |
| `add_late` | 支持 | **显式不支持** | takler 抛出 `takler backend does not support late`；不为填平能力而静默忽略 |
| `add_repeat_date` | 支持 | 支持 | 当前公共接口使用默认 step 1 |
| `add_repeat_day` | 支持 | **显式不支持** | takler 抛出 `takler backend does not support repeat_day`；因此 `set_scheduling` 的 `RepeatDay` 分支也不可用于 takler |
| `add_time` | 支持 | 支持 | 当前覆盖时间字符串的 definition 导出 |
| `set_defstatus_complete` / `set_defstatus_queued` | 支持 | 支持 | 分别生成 complete/queued 默认状态 |
| `script_cmd_var_name` / `script_cmd_value` + 任务脚本变量 | 支持；语义不同 | 支持；语义不同 | ecFlow 使用 `ECF_SCRIPT_CMD=cat <job>.ecf`；takler 使用 `TAKLER_SCRIPT=<job>.sh`，并同步 `ShellScriptTask.script_path` |
| `save_suite` | 支持；格式不同 | 支持；格式不同 | ecFlow 输出文本 `.def`；takler 输出 `takler.definition` JSON（当前 `schema_version` 为 1），后缀由应用选择 |

takler 的三个显式不支持路径在 `test_takler_current_contract.py` 中断言完整异常文本；
修改异常语义时必须同步更新该契约和本矩阵。后端的新能力只有在 definition 导出及相应消费者
验证完成后，才能从“显式不支持”改为“支持”。

## 资源载体

**工作流后端与资源载体是正交维度。** `orvix` 和 `slsubmit6` 只负责作业资源、提交和终止命令，
不创建 suite/节点树，也不是 `WorkflowBackend`。

在 slurm workload 下，任务资源通过 `submit_carrier` 决定如何抵达调度器。suite 构建时调用一次
`set_runtime` 即可（对应 toyflow `flow.py` 的 `setup()`）：

```python
from takflow.backends.runtime import set_runtime

set_runtime(suite, config.workload, engine=engine)
# slsubmit6 carrier 还需要任务级资源:set_runtime(node, workload, engine=engine, task_resource=tr)
```

| Carrier | 生成内容 | 适用场景 |
|---------|----------|----------|
| `orvix` | `#ORVIX key=value` 指令 + `orvix submit` | `mcv-workflow` 默认 |
| `slsubmit6` | `%QUEUE%` / `%NODES%` / `%WCKEY%` 变量 + `slsubmit6` | `gfs-post` / `meso-post` 默认 |

两种 carrier 使用相同的 `TaskResource` 输入，切换只需改 YAML 中的 `workload.submit_carrier`。

`set_runtime` 按 carrier 注入的提交/终止命令：

- **`orvix` 载体**：ecFlow 下设 `ECF_JOB_CMD=orvix submit --scheduler %ORVIX_SCHEDULER% %ECF_JOB%`、
  `ECF_KILL_CMD=orvix kill %ECF_JOB%.info.yaml`（takler 下对应 `TAKLER_SHELL_JOB_CMD`/
  `TAKLER_SHELL_KILL_CMD`）；`ORVIX_SCHEDULER` 由 workload 的 `scheduler` 字段推导为 suite 变量。
- **`slsubmit6` 载体**：任务级 `set_runtime` 把 `TaskResource` 展开为 ecFlow 变量
  `%QUEUE%`/`%NODES%`/`%TASKS_PER_NODE%`/`%WCKEY%`，并设 `ECF_JOB_CMD=slsubmit6 ...`、
  `ECF_KILL_CMD=slcancel4 ...`；`#SBATCH` 的最终转译由作业 include 的 `workload.h` 完成。

载体与后端的组合不表示提交语义完全等价：orvix 的 ecFlow/takler 命令分别由现有生成契约覆盖；
`slsubmit6` 的 takler 分支当前使用 `TAKLER_SHELL_JOB_CMD=sbatch ...` 和
`TAKLER_SHELL_KILL_CMD=scancel ...`，属于**语义不同**，不宣称与 ecFlow 的 slsubmit6/slcancel4
链路等价。资源载体测试不替代真实调度器提交验证。
