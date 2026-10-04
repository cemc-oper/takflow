# jobspec 契约

`takflow.spec.jobspec` 是语言无关的作业运行资源契约，是 takflow 存在的核心理由：
Python 侧的应用（takflow 及其上层应用）和 Go 侧的 `orvix` 通过它保持作业资源描述一致。

## 组成

| 文件 | 作用 |
|---|---|
| `spec/jobspec/jobspec.schema.json` | 权威 schema，扁平 19 键，与 orvix `#ORVIX` 指令词汇表一一对应 |
| `spec/jobspec/VERSION` | 契约版本号（语义化版本），takflow 唯一维护 |
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

## 所有权规则

- **takflow 是契约的唯一 owner**：schema、VERSION、对拍向量都在本仓库维护。
- **orvix 只 vendor 只读副本**：orvix 仓库中的 schema 拷贝只用于校验，不得修改；
  修改契约必须从 takflow 发起，并同步 bump VERSION。
- 契约变更后须重新生成 golden 输出并跑通对拍，见 [测试](../develop/testing.md) 与
  [版本管理](../develop/versioning.md)。
