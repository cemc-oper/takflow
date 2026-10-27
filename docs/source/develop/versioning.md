# 版本与兼容管理

takflow 包版本、orvix jobspec 契约版本和 orvix 来源 pin 分别管理。公共 Python API、应用 CLI
和生成产物的兼容边界见[公共 API 与兼容策略](../guide/public-api.md)；本页只规定版本关系和
jobspec vendor 同步流程。

## 1. 版本对象

| 对象 | 版本/标识来源 | 维护规则 |
|---|---|---|
| takflow Python 包 | takflow 仓库 git tag，经 `setuptools_scm` 写入包版本；运行时读取 `takflow.__version__` | 按公共 Python API 和消费者影响独立发布，不与 jobspec 机械同步 bump |
| orvix jobspec 契约 | orvix `spec/jobspec/VERSION`；takflow 保存只读 vendor 副本 | 由 orvix 按契约兼容性 bump，takflow 通过 pin 同步 |
| vendor 来源 pin | takflow `src/takflow/spec/jobspec/ORVIX_VERSION` | 记录只读副本对应的 orvix git ref，不是语义化版本 |

当前 jobspec 契约版本和完整 pin 只在
[jobspec 契约页的 vendor 快照](../reference/jobspec-schema.md)展示，权威值始终是上述包内文件。
文档中的快照不能代替 `VERSION`/`ORVIX_VERSION`，也不能通过编辑文档或 vendor 文件伪造升级。

## 2. takflow 包版本

takflow 使用独立包版本表达 Python API、toolkit、后端适配和生成行为的发布节奏。1.x 起，
向后兼容功能、修复和不兼容变化分别进入 MINOR、PATCH 和 MAJOR；0.x 阶段的破坏性变化也必须
显式记录并提供迁移说明。deprecate、兼容 facade、生成产物 golden diff 和应用 CLI 的记录规则
以[公共 API 与兼容策略](../guide/public-api.md)为准。

应用 CLI 由应用仓库独立版本化。takflow 包升级不隐含应用命令或历史选项变化，也不以 jobspec
契约版本作为 takflow 或应用的发布版本。

## 3. jobspec 契约版本规则

- **orvix 是契约的唯一 owner**。任何对 `jobspec.schema.json`、`#ORVIX` 指令词汇表、
  契约键语义的修改都必须在 orvix 仓库发起。
- **takflow 只 vendor 只读副本**。本仓库中的 schema / VERSION / conformance 拷贝
  用于校验与消费侧验收，不得原地修改；同步方向永远是 orvix → takflow，
  由 `scripts/sync_jobspec.py` 执行，CI 检查 vendor 副本与 pin 一致。
- 契约变更时 orvix 侧同步 bump VERSION：
  - **MAJOR**：删除键、改变键的语义或类型（不兼容）。
  - **MINOR**：新增可选键（向后兼容）。
  - **PATCH**：描述性修正，不改变任何行为。

`TaskResource`/`ResourceSpec` 是 Python 侧的契约消费者。只调整应用高层模型但未改变语言无关
契约时，不 bump jobspec VERSION；需要新增或修改契约键时，必须先从 orvix 发起。

## 4. vendor 变更流程

1. 在 orvix 中修改 schema / 解析器 / 后端 / 对拍向量，按规则 bump `spec/jobspec/VERSION`，
   `make regen-golden` 重新生成 golden 基线并跑通 golden 测试（见 orvix 的
   `docs/source/develop/adding-directive.md`）。
2. orvix 合并（并发布/打 tag）后，在本仓库升 pin 同步：
   `python scripts/sync_jobspec.py --orvix-ref <新版 orvix ref>`。
   该命令覆盖 vendor 副本并更新 `ORVIX_VERSION`，人工确认差异后随 PR 评审。
3. 若新键需要从应用层配置生成，在同一 PR 更新 `TaskResource` → `ResourceSpec`
   的编译逻辑与相关文档，并分别评审 Python API 和 jobspec 兼容影响。
4. 核对 [jobspec 契约页](../reference/jobspec-schema.md)的当前快照与 vendor
   `VERSION`/`ORVIX_VERSION` 完全一致，避免文档版本漂移。
5. CI 的 conformance job（vendored==pin 检查 + 对拍测试，见
   [测试](testing.md)）全绿即完成。
