# jobspec 契约

`takflow.spec.jobspec` 是语言无关的作业运行资源契约，是 takflow 存在的核心理由：
Python 侧的应用（takflow 及其上层应用）和 Go 侧的 `orvix` 通过它保持作业资源描述一致。

## 组成

下表为本仓库的 vendor 只读副本（同步自 orvix，见文末所有权规则）：

| 文件 | 作用 |
|---|---|
| `spec/jobspec/jobspec.schema.json` | 契约 schema，扁平 19 键，与 orvix `#ORVIX` 指令词汇表一一对应 |
| `spec/jobspec/VERSION` | 契约版本号（语义化版本），orvix 唯一维护 |
| `spec/jobspec/ORVIX_VERSION` | vendor 来源 pin：本副本同步自的 orvix git ref |
| `spec/jobspec/conformance/vectors/*.sh` | 对拍输入：携带 `#ORVIX` 指令的作业脚本 |
| `spec/jobspec/conformance/golden/<scheduler>/*.submit` | 对拍基线：`orvix generate` 的期望输出 |

## 19 个契约键

```text
scheduler, job_name, output, error, nodes, ntasks, ntasks_per_node,
cpus_per_task, time, queue, account, project, application, exclusive,
nodelist, job_type, memory, dependency, requeue
```

在 Python 侧对应 `takflow.jobspec.ResourceSpec`（`extra="forbid"`）；
在 orvix 侧对应 `#ORVIX key=value` 指令解析器的词汇表（下划线在指令中写成连字符，
如 `ntasks_per_node` → `ntasks-per-node`）。

除 `requeue`（布尔，默认 `true`）与 `exclusive` 外，所有键的值均为字符串：指令层不做
数值转换，避免 Go 侧与 Python 侧各自解析产生漂移；带类型的易用性由上层
`TaskResource`（见 [作业资源描述](../guide/jobspec.md)）提供。

## 所有权规则

- **orvix 是契约的唯一 owner**：schema、VERSION、对拍向量的权威版本在 orvix
  仓库的 `spec/jobspec/`（`github.com/cemc-oper/orvix`）。
- **takflow 只 vendor 只读副本**：本目录内容同步自 orvix @ `ORVIX_VERSION` 记录的
  pin，不得原地修改；修改契约必须从 orvix 发起，由其 bump VERSION。
- 同步用 `python scripts/sync_jobspec.py --orvix-ref <ref>` 执行，CI 检查
  vendor 副本与 pin 一致；契约变更后 orvix 侧重新生成 golden 输出并跑通对拍，
  见 [测试](../develop/testing.md) 与 [版本管理](../develop/versioning.md)。
