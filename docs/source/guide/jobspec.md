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

## 在作业模板中使用

Jinja2 作业模板中通过 `render_resource_block` 把资源块嵌入脚本头部，
模板渲染时传入编译后的 `ResourceSpec`。示例见 `examples/toyflow` 的 `resources/jobs/` 模板。

## 与 orvix 的契约关系

`#ORVIX` 指令词汇表是 takflow 与 `orvix`（Go 作业提交层）之间的语言无关契约：

- 权威 schema：`takflow.spec.jobspec` 中的 `jobspec.schema.json`（19 个键）。
- takflow 是契约的唯一 owner；orvix 只 vendor 只读副本并做一致性校验。
- 契约详情见 [jobspec 契约](../reference/jobspec-schema.md)。
