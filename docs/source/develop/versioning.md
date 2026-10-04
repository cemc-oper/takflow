# 契约版本管理

`spec/jobspec/VERSION` 是 jobspec 契约的版本号，采用语义化版本（当前 `1.0.0`）。

## 规则

- **takflow 是契约的唯一 owner**。任何对 `jobspec.schema.json`、`#ORVIX` 指令词汇表、
  契约键语义的修改都必须在本仓库发起。
- **orvix 只 vendor 只读副本**。orvix 仓库中的 schema 拷贝用于校验，不得原地修改；
  同步方向永远是 takflow → orvix。
- 契约变更时同步 bump VERSION：
  - **MAJOR**：删除键、改变键的语义或类型（不兼容）。
  - **MINOR**：新增可选键（向后兼容）。
  - **PATCH**：描述性修正，不改变任何行为。

## 变更流程

1. 在 takflow 中修改 schema / Python 模型 / 对拍向量。
2. bump `spec/jobspec/VERSION`。
3. 重新生成 golden 基线并跑通对拍（见 [测试](testing.md)）。
4. 将新 schema 与 VERSION 同步到 orvix 的 vendor 副本，在 orvix 侧跑一致性校验。
