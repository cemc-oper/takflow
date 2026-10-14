# 契约版本管理

jobspec 契约的版本号采用语义化版本（当前 `1.0.0`）。契约的权威版本号文件是
orvix 仓库的 `spec/jobspec/VERSION`；本仓库存放 vendor 只读副本
（`src/takflow/spec/jobspec/VERSION`）与 orvix 侧的 pin
（`src/takflow/spec/jobspec/ORVIX_VERSION`）。

## 规则

- **orvix 是契约的唯一 owner**。任何对 `jobspec.schema.json`、`#ORVIX` 指令词汇表、
  契约键语义的修改都必须在 orvix 仓库发起。
- **takflow 只 vendor 只读副本**。本仓库中的 schema / VERSION / conformance 拷贝
  用于校验与消费侧验收，不得原地修改；同步方向永远是 orvix → takflow，
  由 `scripts/sync_jobspec.py` 执行，CI 检查 vendor 副本与 pin 一致。
- 契约变更时 orvix 侧同步 bump VERSION：
  - **MAJOR**：删除键、改变键的语义或类型（不兼容）。
  - **MINOR**：新增可选键（向后兼容）。
  - **PATCH**：描述性修正，不改变任何行为。

## 变更流程

1. 在 orvix 中修改 schema / 解析器 / 后端 / 对拍向量，bump `spec/jobspec/VERSION`，
   `make regen-golden` 重新生成 golden 基线并跑通 golden 测试（见 orvix 的
   `docs/source/develop/adding-directive.md`）。
2. orvix 合并（并发布/打 tag）后，在本仓库升 pin 同步：
   `python scripts/sync_jobspec.py --orvix-ref <新版 orvix ref>`。
   该命令覆盖 vendor 副本并更新 `ORVIX_VERSION`，人工确认差异后随 PR 评审。
3. 若新键需要从应用层配置生成，在同一 PR 更新 `TaskResource` → `ResourceSpec`
   的编译逻辑与相关文档。
4. CI 的 conformance job（vendored==pin 检查 + 对拍测试，见
   [测试](testing.md)）全绿即完成。
