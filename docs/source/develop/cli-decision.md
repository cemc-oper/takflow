# 公共 CLI 决策记录（TF-09）

状态：**历史决定，公共 CLI 限制已由 [TC-12 新决策](standard-cli-decision.md)替代** · 原决定日期：2026-11-02

以下原文保留为历史依据；当前标准入口见[命令契约](../guide/cli.md)。

## 1. 决策

takflow **不实现 `takflow.cli`，不增加公共 console script，也不建立 CLI 插件注册表**。
各应用继续拥有自己的 entry point、命令组、历史选项、提示文本和异常展示；框架共享边界保持为：

- `takflow.generation`：definition/shell 分发、输出路径与保存编排；
- `takflow.toolkit`：resource/job/credential 等原子生成能力；
- `takflow.config` / `takflow.flow` / `takflow.backends`：配置、建树与后端公共 API。

本结论关闭 TF-09，不派生公共 CLI 实现任务，也不要求统一历史选项、删除应用命令或迁移全部应用。

## 2. 评审证据

TF-07 已验证 toyflow，TF-08 已验证 TYM 真实消费者，因此本评审不缺少生成服务的实际接入证据。
TYM 的三形态 ecFlow/shell golden 与 7 个集成用例证明：应用可以保留 CLI 和领域行为，同时共享生成编排。

本次另只读对照 GFS-POST、MCV base/oper 的当前实现；它们是比较对象，不代表已在 TF-09 接入生成服务。

### 2.1 命令与历史选项对照

| 应用入口 | 当前命令 | 配置参数与主要特异行为 |
|---|---|---|
| `toyflow` | resource、config、job、workflow、credential | 全部使用 `--config-file`；workflow 只有 output repo 覆盖；shell definition 不支持；hooks 在 config 加载前导入 |
| `cma-tym-v4-workflow` | resource、config、job、workflow | 全部使用 `--config-file`；resource/config/job 支持 output/workflow repo；workflow 另有 `--output`；无 credential 命令 |
| `cma-gfs-post` | resource、config、job、workflow | 全部使用 `--config-file`；workflow 支持 `--output` 和 output repo，但无 workflow repo 选项；默认 definition 是当前目录 `<suite_name>.def`；缺少 config 模板时警告并跳过 |
| `cma-gfs-post-oper` | resource、config、job、workflow | base 选项之外，resource/job 增加 `--oper-workflow-repo-base`；base/oper 资源两次合并；workflow 建树前显式导入 oper hooks |
| `mcv-workflow` | resource、config、job、workflow、credential | resource 有 include 开关和观测资源策略；base workflow CLI 不暴露独立 `--output`，Python API 则支持；shell 返回 `None` |
| `mcv-oper-workflow` | resource、config、job、workflow、credential | workflow 暴露 `--output/-o`，但不接受 base 的 output/workflow repo 选项；shell 显式拒绝；resource/job 有 oper repo 与合并策略；hooks 在 CLI 模块导入时注册 |

上述命令虽然名字相似，但选项集合并不是可直接合并的公共契约。提供全量选项超集会让某些应用出现无意义参数；按应用裁剪则仍需要应用自己的命令 schema。

## 3. 注入成本评估

| 命令/阶段 | 可共享部分 | 必须由应用保留或注入的部分 | 公共 CLI 收益 |
|---|---|---|---|
| config 加载与初始化 | YAML 读取和 `BaseWorkflowConfig` 基类 | 具体 config class、字段别名、legacy 归一化、领域 validator、base/oper config 类型、hooks 导入顺序 | 低；公共 loader 已存在，剩余主要是应用初始化 |
| resource copy | 通用目录复制与可执行位 helper | TYM 的组件过滤和 include/machine/utils 映射；GFS 的额外目录与 Execution 资源；MCV include 开关、观测资源及 base/oper 两次覆盖 | 低；需要完整资源策略回调和选项 schema |
| config generate | Jinja2 与通用路径工具 | 应用模板、派生上下文、ecFlow `%VAR%` 或 shell 字面值、缺模板策略、build-info 和权限 | 很低；领域 renderer 就是命令主体 |
| job generate | `render_jobs_from_directory()` | TYM `ecffiles` 与 enable-aware filter；GFS Execution 模板子集；base/oper 多 repo 覆盖和品牌 provider | 低；通用 toolkit 已收敛真实重复逻辑 |
| workflow generate | 模式分发、输出路径、保存顺序 | builder、dict/Path/None 返回适配、保存前后产物、shell 限制、verbose/CLI 提示 | **编排收益已由生成服务取得**；剩余主要是参数解析和打印 |
| credential generate | 共享 registry 与渲染函数 | 命令是否存在、credential 文件参数、应用/扩展 hooks、build-info、输出提示 | 低；并非所有应用都有该命令 |

若要保留现有行为，公共 CLI 至少需要注入 config loader、初始化回调、资源处理器、config renderer、job renderer、workflow builder/renderer 和 credential 配置，还要允许每个应用声明不同选项及提示。这样会形成第二套应用插件架构，而不是消除现有 facade。

## 4. base/oper 与兼容 facade 判断

base/oper 的差异不是简单增加一个资源目录：

- GFS-POST oper 在 workflow 建树前导入 hooks，并在 resource/job 阶段合并两套资源；
- MCV oper 在 CLI 模块导入时注册 hooks，workflow 选项集合和 shell 支持与 base 不同；
- toyflow 同样在 config 加载前导入 hooks，说明导入顺序属于行为契约；
- credential 使用共享全局 registry，公共 CLI 若按命令动态导入不同扩展，还需要额外防止重复注册和跨应用污染。

公共 CLI 若通过应用名动态 import 来隐藏这些差异，会把启动顺序、注册表隔离和异常展示变成新的框架承诺。保留应用 entry point 可以让每个仓库明确控制这些行为，不需要新增兼容层。

## 5. 方案结论

### 5.1 完整公共命令组

**不采用。** 需要重建几乎所有应用适配和选项 schema，复杂度高，且容易产生统一历史选项的隐含目标。

### 5.2 仅公共 `workflow generate`

**不采用。** 真正重复的后端选择、路径解析和保存编排已经由 `takflow.generation` 共享；再增加 CLI 层只统一 click 声明，仍需注入 config loader、builder/renderer 和提示策略，收益不足以抵消新的兼容面。

### 5.3 保留应用 CLI + 生成服务/toolkit

**采用。** 这是当前最小且经过真实消费者验证的边界：框架减少生成逻辑重复，应用保留用户接口和领域策略，不增加公共 CLI 兼容负担。

## 6. 后续约束

- 不把 `takflow.cli`、公共 console script 或 CLI 插件 entry point 作为待实现功能保留；
- 新应用应优先复用生成服务与 toolkit，而不是复制后端分发、路径解析和保存逻辑；
- 既有应用 CLI 的新增、弃用和删除继续由所属仓库独立评审；
- 只有出现当前证据未覆盖的具体需求时才重新立项评审，不在 TF-09 下保留空泛待办。
