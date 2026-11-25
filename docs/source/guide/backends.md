# 后端与资源载体

本页说明工作流后端的能力差异，以及 orvix/slsubmit6 等资源载体如何把作业提交到目标环境。后端和载体是正交维度；领域节点树见[流程与钩子](flow-and-hooks.md)，作业资源字段见[jobspec](jobspec.md)。

## 选择后端

标准应用在 `Application` 中声明 suite builder，由标准构建的 workflow 阶段通过 `takflow.flow.generate` 按 `workflow_mode` 选择后端和默认后缀。直接使用低层生成服务时，应用显式调用同一入口（toyflow 的 `src/toyflow/generate.py` 是这种旧入口的薄适配）：

```python
from takflow.flow.generate import generate_workflow

result = generate_workflow(config, suite_builder=create_suite)
output_path = result.output_path  # ecFlow: .def；takler: .json
```

需要绕过生成服务、直接使用后端的低层 API 时，仍可自行实例化 `WorkflowEngine(EcflowBackend())` 或
`WorkflowEngine(TaklerBackend())` 并调用 `save_suite()`；后端能力边界不变。

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

同一限制通过 `WorkflowBackend.unsupported_operations` / `TaklerBackend.unsupported_operations` 的方法名集合提供给生成预检。消费者可声明 `required_operations`，在输出前拒绝已知不支持操作；它不是应用或组件注册表，也不替代原方法的异常契约。完整检查边界见[生成检查](generation-checks.md)。

## 资源载体

**工作流后端与资源载体是正交维度。** `orvix` 和 `slsubmit6` 只负责作业资源、提交和终止命令，
不创建 suite/节点树，也不是 `WorkflowBackend`。

在 slurm workload 下，任务资源通过 `submit_carrier` 决定如何抵达调度器。suite 构建时调用一次
`set_runtime` 即可（对应 toyflow `flow.py` 的 `setup()`）：

```python
from takflow.jobs.submission import set_runtime
from takflow.jobs.submission.variables import set_resource_variables

set_runtime(suite, config.workload, engine=engine)
set_resource_variables(task, tr)
```

| Carrier | 生成内容 | 适用场景 |
|---------|----------|----------|
| `orvix` | `#ORVIX key=value` 指令 + `orvix submit` | MCV、GFS 及其两个 oper 扩展、TYM ecFlow 和 Shell 的 Slurm 调度默认值 |
| `slsubmit6` | `%QUEUE%` / `%NODES%` / `%WCKEY%` 变量 + `slsubmit6` | GFS 和 TYM 的显式历史 ecFlow 配置，`meso-post` 默认 |

ecFlow 的两种载体使用相同的 `TaskResource` 输入。takler 的调度任务使用 `orvix`，配置 `slsubmit6` 会在构建定义前报错。

- **ORVIX** 从节点继承 `ORVIX_SCHEDULER`。ecFlow 提交命令为 `orvix submit --scheduler "%ORVIX_SCHEDULER%" "%ECF_JOB%"`，取消命令为 `orvix kill "%ECF_JOB%.info.yaml"`。takler 在每次 attempt 展开 `TAKLER_JOB`、继承的 scheduler 和该 job 对应的 `.info.yaml`。当前 takler 提供取消命令变量，引擎发起作业取消仍待上游入口。
- **ecFlow 历史 Slurm 载体**通过 `slsubmit6` 提交，使用 `slcancel4` 和本次作业的 `ECF_RID` 取消。
- **本地任务**省略载体或选择 `direct` 时直接执行 job，选择 `orvix` 时通过 ORVIX 的 local 后端提交。

下级任务可继承提交和取消命令。队列、时限、内存、并行规模及 requeue 可以声明在 suite、family 或 task 上。[资源字段与回退](jobspec.md)

## 迁移提交入口

模块重组后，应用和框架需要配套更新以下导入。

| 原入口 | 新入口 |
|---|---|
| `takflow.backends.runtime.set_runtime` 及各载体的 `set_runtime` | `takflow.jobs.submission.set_runtime`，按 workload 选择载体 |
| `takflow.backends.runtime` 的 `set_resource_variables`、`ecflow_resource_variables` | `takflow.jobs.submission.variables` |
| `takflow.backends.runtime`、`takflow.toolkit.util` 和 `takflow.toolkit` 的 `shell_job` | `takflow.jobs.submission.direct.shell_job` |
| `takflow.backends.runtime.orvix.orvix_job` | `takflow.jobs.submission.orvix.orvix_job` |
| `takflow.backends.runtime.slsubmit` 的 `slsubmit6_serial_job`、`slsubmit6_parallel_job` | `takflow.jobs.submission.slsubmit6` |
| `takflow.backends.runtime.orvix` 的 `to_orvix_directives`、`render_resource_block`、`MARKER` | `takflow.jobspec` |
