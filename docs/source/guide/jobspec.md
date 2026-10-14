# 作业资源描述（jobspec）

配置中的任务资源使用 `TaskResource` 作为面向应用的串行/并行模型，再编译为与 `orvix` 对齐的
扁平 `ResourceSpec`，最终渲染为 `#ORVIX` 指令或 `%VAR%` 变量（取决于资源载体）。

## TaskResource → ResourceSpec → #ORVIX

```python
from takflow.config import SlurmWorkload
from takflow.jobspec import TaskResource, to_orvix_directives

workload = SlurmWorkload(wckey="toyflow")  # 其余字段取默认值

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
- `project` 取自 `workload.wckey`（→ slurm `--wckey`），`application` 取自
  `workload.application`（→ slurm `--comment`）；
- `requeue=false` 时 slurm 后端发 `--no-requeue`（donau/local 各自映射或忽略）；
- `nodes`/`ntasks_per_node` 等整数字段编译时转成字符串——指令层不做数值转换，与 orvix
  解析器保持一致。

`to_orvix_directives(spec, conditional_for="slurm")` 可生成条件指令
`#ORVIX [scheduler=slurm] key=value`，只在指定调度器下生效。

> **命名冲突（务必注意）：** `TaskResource.job_type`（serial/parallel）是 takflow 的
> **高层选择器**，只用来决定取哪个默认 queue；它**不**对应 orvix 的 `job-type` 指令
> （后者是 donau `cosched` 一类调度属性）。`compile()` 绝不会把高层 `job_type` 当作
> `#ORVIX job-type` 发出。orvix 的 `job-type`/`exclusive`/`dependency`/`nodelist`
> 目前各应用均未使用，作为 `ResourceSpec` 的可选透传字段保留。
>
> 同理，规范名是 **`queue`**；旧名 `partition` 不是契约键，orvix 解析器会**静默丢弃**它。

## 在作业模板中使用

Jinja2 作业模板中通过 `render_resource_block` 把资源块嵌入脚本头部，
模板渲染时传入编译后的 `ResourceSpec`。示例见 `examples/toyflow` 的 `resources/jobs/` 模板。

## 与 orvix 的契约关系

`#ORVIX` 指令词汇表是 takflow 与 `orvix`（Go 作业提交层）之间的语言无关契约：

- 权威 schema 在 orvix 仓库的 `spec/jobspec/jobspec.schema.json`（19 个键）；
  `takflow.spec.jobspec` 中是 vendor 只读副本（pin 见 `ORVIX_VERSION`）。
- orvix 是契约的唯一 owner；takflow vendor 副本并做消费侧一致性校验（渲染稳定性
  + pin 版本对拍）。
- 契约详情见 [jobspec 契约](../reference/jobspec-schema.md)。
