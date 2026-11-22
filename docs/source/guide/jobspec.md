# 作业资源描述（jobspec）

配置中的任务资源使用 `TaskResource` 作为面向应用的串行/并行模型，再编译为与 `orvix` 对齐的
扁平 `ResourceSpec`，由模板渲染为 `#ORVIX`，或在历史 Slurm 提交路径中渲染为 `#SBATCH`。

## TaskResource → ResourceSpec → #ORVIX

```python
from takflow.config import SlurmWorkload
from takflow.jobspec import TaskResource, to_orvix_directives

workload = SlurmWorkload(project="toyflow")  # 其余字段取默认值

tr = TaskResource(
    job_type="parallel",
    nodes=2,
    ntasks_per_node=16,
    time="01:00:00",
)

spec = tr.compile(workload)
print("\n".join(to_orvix_directives(spec)))
```

输出：

```text
#ORVIX scheduler=slurm
#ORVIX nodes=2
#ORVIX ntasks-per-node=16
#ORVIX time=01:00:00
#ORVIX queue=normal
#ORVIX project=toyflow
```

## 编译规则与字段语义

`TaskResource.compile(workload)` 的取值规则：

- `queue` 缺省时按 `job_type` 取 `workload.default_serial_queue`（serial）或
  `default_parallel_queue`（parallel）；
- `project` 取自 `workload.project`（→ Slurm `--wckey`），`application` 取自
  `workload.application`（→ slurm `--comment`）；
- `requeue=false` 时 slurm 后端发 `--no-requeue`（donau/local 各自映射或忽略）；
- `nodes`/`ntasks_per_node` 等整数字段编译时转成字符串——指令层不做数值转换，与 orvix
  解析器保持一致。

`to_orvix_directives(spec, conditional_for="slurm")` 可生成条件指令
`#ORVIX [scheduler=slurm] key=value`，只在指定调度器下生效。

`queue`、`time`、`memory` 要求字符串至少含一个非空白字符。`time="0"`、`memory="0"` 和 `requeue=False` 均保留。既有 ORVIX 模板辅助接受 `queue`/`partition`、`time`/`walltime`、`project`/`wckey`。每对名称最多提供一个非 None 值，同时提供两个值会报错，即使两者相同。

`render_orvix_resource_block` 成功接受旧参数后，Python 发出 `ResourceAliasWarning`，标准 CLI 显示替代名。将 `partition` 改为 `queue`、`walltime` 改为 `time`、`wckey` 改为 `project`。Slurm workload 的配置输入相应改为 `workload.project`。省略旧名或传入 None 均无迁移提示。旧名移除版本和日期待定。原生 Slurm helper 使用规范参数，提交指令仍按 Slurm 语法输出 `--partition` 和 `--wckey`，引擎继续通过 `WCKEY` 继承项目值。

应用可为某个任务的资源字段声明局部缺省。例如 `Annotated[TaskResource, task_resource_defaults(forecast_defaults)]` 中的工厂返回应用自己的 `TaskResource`。仅调整时间时会沿用任务原有的类型与规模。显式切换类型时，旧类型的队列和规模缺省随之退出。允许省略整个字段时，在该字段上配置同一 `default_factory`。这些值供资源编译使用，本级节点变量仍由应用声明。

> **命名冲突（务必注意）：** `TaskResource.job_type`（serial/parallel）是 takflow 的
> **高层选择器**，只用来决定取哪个默认 queue；它**不**对应 orvix 的 `job-type` 指令
> （后者是 donau `cosched` 一类调度属性）。`compile()` 绝不会把高层 `job_type` 当作
> `#ORVIX job-type` 发出。orvix 的 `job-type`/`dependency`/`nodelist`
> 目前各应用均未使用，作为 `ResourceSpec` 的可选透传字段保留。
>
> 同理，规范名是 **`queue`**；旧名 `partition` 不是契约键，orvix 解析器会**静默丢弃**它。

## 在作业模板中使用

Jinja2 作业模板在第一条可执行语句之前调用 `render_orvix_resource_block(...)`。ecFlow＋slsubmit6 和 Shell 直接 Slurm 的兼容模板可在同一位置改用 `render_slurm_resource_block(...)`。两者使用同一组取值，普通 build 在 Python 中生成资源头。

| 规范参数 | 原生 Slurm 参数 |
| --- | --- |
| `job_name`、`output`、`error` | `--job-name`、`--output`、`--error` |
| `queue`、`time`、`memory` | `--partition`、`--time`、`--mem` |
| `nodes`、`ntasks_per_node` | `--nodes`、`--ntasks-per-node` |
| `project`、`application` | `--wckey`、`--comment` |
| `requeue` | False 写 `--no-requeue`，True 或最终缺省时省略 |
| `exclusive` | True 写 `--exclusive`，字符串模式（例如 `user`）写 `--exclusive=user`，False 或 None 时省略 |

应用模板可传 `job_name`、`output`、`error`，或在任务的 `TaskResource` 中指定。作业上下文提供默认 stdout/stderr。ecFlow 与 takler 的默认值分别引用当前 `ECF_JOBOUT`、`TAKLER_JOBOUT`。Shell Slurm 默认使用 `logs/<作业>.%j.out` 和 `.err`，Shell 本地默认使用 `logs/<作业>.out` 和 `.err`。配置本地 workload 后，ORVIX 源作业保留 `scheduler=local` 和已有资源值，缺失的队列与规模省略。
ecFlow 和 takler 在创建 job 时从 task 向上查找最近的节点值，再采用模板回退。Shell 源作业直接包含本次有效资源。串行模板省略并行规模。

```python
from takflow.backends.runtime import set_resource_variables, set_runtime
from takflow.jobspec import TaskResource

set_runtime(suite, config.workload, engine)
set_resource_variables(family, TaskResource(job_type="parallel", queue="batch", nodes=4, ntasks_per_node=32))
set_resource_variables(task, TaskResource(time="00:40:00"))
```

以上 task 只固定墙钟。需要固定与父节点相同的队列或规模时，也在本级显式声明。已有混合队列应用使用的 `set_runtime(node, workload, engine, task_resource)` 保留按 parallel 选择默认并行队列的行为。载体切换由不带 task_resource 的 `set_runtime` 调用声明。

ecFlow 使用 `WALLTIME`、`MEMORY`、`NODES`、`TASKS_PER_NODE`、`QUEUE`、`WCKEY`、`APPLICATION`、`JOB_NAME`、`JOB_OUTPUT`、`JOB_ERROR` 和小写布尔值的 `REQUEUE`。有模板值时，例如 `%WALLTIME:06:00:00%`，可直接修改节点的标量。没有模板值的可选文本或数量字段由节点携带整行引用，例如 `ORVIX_MEMORY` 和 `SLURM_MEMORY` 分别包含引用 `%MEMORY%` 的完整指令。通过 takflow 的节点 API 声明资源会一并生成引用。在已加载的原生定义上首次增加此类字段，可以调用 `parent.add_variable(ecflow_resource_variables({"MEMORY": "8G"}))`，其中 `ecflow_resource_variables` 来自 `takflow.backends.runtime`。普通字段后续可直接修改标量。调整日志路径时每次用同一函数传入原始文本，如 `{"JOB_OUTPUT": "/log dir/%A_%a.%j.out"}`。它会保护传给 Slurm 的百分号，并写入对应的 `JOB_OUTPUT_PREFIX` 或 `JOB_ERROR_PREFIX`，使当前 attempt 的默认日志行成为普通注释。撤下本级声明时同时移除标量、两种载体的整行变量及该日志的前缀，子节点即可再次继承父值。

ecFlow 在没有 requeue 回退的 ORVIX 模板中按 `REQUEUE` 选择公共 include。使用标准 Application 时启用 `use_public_resources` 并将输出的 `ecflow/include` 加入 `ECF_INCLUDE`。原生 Slurm 模板可以使用 `%include <common/requeue.h>`，只有有效 False 产生 `#SBATCH --no-requeue`。takler 用第二轮 Jinja 处理缺失值与布尔值。

示例见 `examples/toyflow` 的 `resources/jobs/` 模板。

## 与 orvix 的契约关系

`#ORVIX` 指令词汇表是 takflow 与 `orvix`（Go 作业提交层）之间的语言无关契约：

- 权威 schema 在 orvix 仓库的 `spec/jobspec/jobspec.schema.json`（19 个键）；
  `takflow.spec.jobspec` 中是 vendor 只读副本（pin 见 `ORVIX_VERSION`）。
- orvix 是契约的唯一 owner；takflow vendor 副本并做消费侧一致性校验（渲染稳定性
  + pin 版本对拍）。
- 契约详情见 [jobspec 契约](../reference/jobspec-schema.md)。
