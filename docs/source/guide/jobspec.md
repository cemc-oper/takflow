# 作业资源描述（jobspec）

本页说明节点数、队列、墙钟等**作业资源**如何从应用模型进入提交层。这里的“资源”不是脚本、模板、include 和 machine 组成的[资源层](resource-layers.md)。

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

Jinja2 作业模板在第一条可执行语句之前调用 `render_orvix_resource_block(...)`。ecFlow＋slsubmit6 和 Shell 直接 Slurm 的兼容模板可在同一位置改用 `render_slurm_resource_block(...)`。两者使用同一组取值，标准构建在 Python 中生成资源头。

完整构建与分步构建在 config 和 job 模板中注册这两个 helper。前者支持三种 workflow 模式，后者服务于 ecFlow 和 Shell 的历史 Slurm 入口。低层 `render_jobs_from_directory` 注册相同的 helper，`render_single_job_file` 会在调用方的 Jinja 环境中补上缺失的注册。直接调用 Jinja 的应用可自行向 `env.globals` 注册 `takflow.jobs.headers.RESOURCE_TEMPLATE_HELPERS` 并提供 `config` 上下文，或从 Python 调用渲染函数。Python 函数省略 `workflow_mode` 时输出具体值。

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
from takflow.jobs.submission import set_runtime
from takflow.jobs.submission.variables import set_resource_variables
from takflow.jobspec import TaskResource

set_runtime(suite, config.workload, engine)
set_resource_variables(family, TaskResource(job_type="parallel", queue="batch", nodes=4, ntasks_per_node=32))
set_resource_variables(task, TaskResource(time="00:40:00"))
```

以上 task 只固定墙钟。需要固定与父节点相同的队列或规模时，也在本级显式声明。已有混合队列应用使用的 `set_runtime(node, workload, engine, task_resource)` 保留按 parallel 选择默认并行队列的行为。载体切换由不带 task_resource 的 `set_runtime` 调用声明。

ecFlow 在声明资源的 suite、family 或 task 上写入标量。常用变量有 `QUEUE`、`WCKEY`、`APPLICATION`、`NODES`、`TASKS_PER_NODE`、`WALLTIME`、`MEMORY`、`REQUEUE`、`JOB_NAME`、`JOB_OUTPUT` 和 `JOB_ERROR`。ORVIX 的提交命令另外读取 `ORVIX_SCHEDULER` 来选择实际调度器。

源作业或其 include 包含所选载体的完整指令，例如 ORVIX 的 `#ORVIX memory=%MEMORY%` 或原生 Slurm 的 `#SBATCH --mem=%MEMORY%`。创建作业时，ecFlow 从 task 向上查找标量，再采用模板回退，例如 `%WALLTIME:06:00:00%`。可选字段在两处都无值时，生成的作业中会省略整行。已加载定义可直接用 `family.add_variable("MEMORY", "8G")` 首次声明内存，用 `task.add_variable("MEMORY", "4G")` 覆盖，用 `task.delete_variable("MEMORY")` 恢复继承。再删除 family 上的声明，下一次创建的作业就会恢复模板回退或省略该行。

日志文件名可以同时含有 ecFlow 和 Slurm 的占位符。通过 takflow 的节点 API 传入原始路径即可。在原生 ecFlow Python API 中，可用 `node.add_variable(ecflow_resource_variables({"JOB_OUTPUT": "/log dir/%A_%a.%j.out"}))` 写入所需的百分号转义。该函数由 `takflow.jobs.submission.variables` 导出，只返回传入的标量。删除日志覆盖后，默认路径中的 `%ECF_JOBOUT%` 会随本次尝试重新展开。升级已有产物时，用同一次构建生成的定义和源作业配套加载。

ecFlow 在没有 requeue 回退的 ORVIX 模板中按 `REQUEUE` 选择公共 include。使用标准 Application 时启用 `use_public_resources` 并将输出的 `ecflow/include` 加入 `ECF_INCLUDE`。原生 Slurm 模板可以使用 `%include <common/requeue.h>`，只有有效 False 产生 `#SBATCH --no-requeue`。takler 用第二轮 Jinja 处理缺失值与布尔值。

示例见 `examples/toyflow` 的 `resources/jobs/` 模板。

## 与 orvix 的契约关系

`#ORVIX` 指令词汇表是 takflow 与 `orvix`（Go 作业提交层）之间的语言无关契约：

- 权威 schema 在 orvix 仓库的 `spec/jobspec/jobspec.schema.json`（19 个键）；
  `takflow.spec.jobspec` 中是 vendor 只读副本（pin 见 `ORVIX_VERSION`）。
- orvix 是契约的唯一 owner；takflow vendor 副本并做消费侧一致性校验（渲染稳定性
  + pin 版本对拍）。
- 契约详情见 [jobspec 契约](../reference/jobspec-schema.md)。
