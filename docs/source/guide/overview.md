# 设计总览与职责边界

本页从**一次构建**解释 takflow 的整体设计，帮助读者先建立使用模型，再进入各专题页面。包目录和七层技术架构见[架构设计](../develop/architecture.md)；底层 API 与旧 CLI 示例见[toyflow 快速上手](../quickstart.md)，真实标准应用见 {ref}`MCV S1 参考 <mcv-s1-reference>`。

takflow 面向工作流生成器应用，不直接替代业务应用、调度器或作业提交工具。新应用的主路径是：

```text
Application 声明 → Application.prepare() → build(context) → 检查生成物
```

## 一次构建的生命周期

一次标准构建以应用声明、YAML、资源层和扩展为输入，在同一个有效上下文中完成：

```text
Application 声明 + YAML + 资源层 + 扩展
                    │
                    ▼
          Application.prepare()
          本轮不写生成文件
                    │
     ┌──────────────┼──────────────┐
     │ 注册表隔离与扩展初始化          │
     │ 配置加载、覆盖与领域校验         │
     │ 路径、资源层与能力预检           │
     └──────────────┼──────────────┘
                    ▼
               BuildContext
          本轮唯一有效上下文
                    │
                    ▼
              build(context)
                    │
     resource → config → credential → job → workflow → report
                    │
                    ▼
       配置、作业、脚本、definition/runner、成功清单
                    │
                    ▼
       takflow check（按需独立检查已有产物）
                    │
                    ▼
       Shell / ecFlow / takler / orvix / 调度器
       和业务程序组成的运行环境（不属于生成阶段）
```

### 1. 声明应用

`Application` 描述“这个生成器是什么”：领域配置类型、资源入口、品牌、支持的模式，以及按需提供的 suite builder、Shell 模板和扩展。声明不包含某次运行的输出目录或临时配置值。

详见[应用声明与有效上下文](application.md)。

### 2. 准备本轮有效上下文

`Application.prepare()` 把应用声明与本轮输入组合成一个 `BuildContext`：加载和校验配置，应用显式覆盖，解析路径和资源层，初始化扩展，并固定本轮品牌、组件、变量和模板上下文。

`prepare` 不写生成文件。完整构建和分步生成必须在这个作用域内消费**同一个**上下文，不能各自重新读取配置、推导路径或注册 hook。静态资源与站点的选择规则见[资源层、组件与 machine](resource-layers.md)。

### 3. 生成产物

`takflow.build` 按以下顺序消费上下文：

| 阶段 | 主要职责 |
|---|---|
| `resource` | 按资源层顺序复制静态文件，记录实际来源 |
| `config` | 生成运行配置和声明的额外模板产物 |
| `credential` | 按开关组合凭证片段；敏感文件使用受控权限和报告 |
| `job` | 渲染任务包装、业务调用和作业资源指令 |
| `workflow` | 生成 ecFlow/takler definition 或 Shell runner |
| `report` | 仅在完整构建成功后原子发布 `generation_manifest.json` |

完整 `build` 与 `run_stage` 共用阶段实现，但分步调用不补跑前置阶段，也不发布完整成功清单。详见[标准构建](build.md)和[标准命令契约](cli.md)。

### 4. 检查与运行

`takflow check` 可对已有产物执行定义解析、原生 job 隔离展开、Shell 语法和清单完整性检查。它不要求重新加载应用或原配置，也不把检查结果改写成新的构建清单。

生成和检查均不执行 machine 片段、业务程序、引擎 load、调度提交或科学产品验收。进入运行环境后，由 Shell/ecFlow/takler、orvix、调度器和业务程序分别承担相应职责。详见[产物检查](generation-checks.md)。

## 两条贯穿构建的能力链

生命周期说明“何时发生”，下面两条链说明应用的领域内容如何进入生成物。

### 领域配置如何变成流程定义

```text
领域 WorkflowConfig
        │
        ▼
应用 suite_builder / context_suite_builder
        │  使用 takflow.flow 的 Node、trigger、变量和领域 hook
        ▼
后端无关节点树
        │
        ├── EcflowBackend → ecFlow .def
        └── TaklerBackend → takler JSON
```

takflow 提供构图抽象和后端能力，应用决定节点、依赖、业务时次及 hook 词汇表。后端支持能力并不完全相同，必须在[后端能力矩阵](backends.md)中核对，详见[流程与钩子](flow-and-hooks.md)。

### 作业资源如何进入提交层

```text
应用 TaskResource（serial / parallel）
        │
        ▼
扁平 ResourceSpec（与 jobspec 契约键对应）
        │
        ▼
#ORVIX 指令或其他资源载体
        │
        ▼
orvix / 站点提交工具 → 目标调度器
```

orvix 拥有语言无关的 jobspec 契约；takflow 保存只读 vendor 副本并提供 Python 模型和渲染器。详见[作业资源描述](jobspec.md)和[jobspec 契约](../reference/jobspec-schema.md)。

这里的“作业资源”是节点数、队列、墙钟等申请参数，不要与脚本、模板、include 和 machine 组成的“资源层”混为一谈。

## 职责边界

| 参与方 | 负责 | 不负责 |
|---|---|---|
| takflow | 配置与有效上下文、资源层、标准阶段、公共 CLI、后端抽象、结果与检查 | 领域科学规则、业务节点树、业务程序执行、实际调度与运行验收 |
| 应用 | 领域配置、suite builder、业务脚本与模板、组件选择、变量、领域 hook 点和运行方式声明 | 重复实现标准阶段、成功清单、公共诊断和资源载体基础设施 |
| 应用扩展 | 有序资源层、显式初始化、领域 hook、额外模板输出和局部上下文 | 接管或重排标准阶段，隐式合并品牌、最终配置类型或全局规则 |
| 运行环境 | Shell/ecFlow/takler 控制、orvix 转换与提交、调度器分配资源、业务程序执行 | 证明某次生成配置在科学和业务上正确 |

## 术语与事实归属

下表统一本指南的核心术语，并指定契约细节的归属页。其他页面只保留与自身主题相关的摘要和链接，不再平行维护同一套规则。

| 术语或事实 | 本指南中的含义 | 归属页 |
|---|---|---|
| 标准应用路径 | 以 `Application` 声明、`prepare()` 的有效上下文、标准构建和公共 CLI 组织应用 | [应用声明](application.md) |
| 标准构建 | `build` / `run_stage` 的六阶段、结果、失败恢复和成功清单 | [标准构建](build.md) |
| 有效上下文 | 一次 `prepare()` 固定的配置、路径、资源选择、品牌和领域上下文 | [应用声明](application.md) |
| 资源层 | 脚本、模板、include、machine 等静态输入的有序来源 | [资源层](resource-layers.md) |
| 作业资源 | 节点数、队列、墙钟等 `TaskResource` / `ResourceSpec` 申请参数 | [作业资源](jobspec.md) |
| 工作流后端 | ecFlow / takler 的节点树实现及其能力差异 | [后端能力矩阵](backends.md) |
| 资源载体 | orvix / slsubmit6 等提交与取消命令通道，不是工作流后端 | [资源载体](backends.md) |
| 低层生成服务 | `takflow.generation` 的模式分发、输出路径和保存编排 | [生成服务 API](../reference/generation.rst) |
| 独立产物检查 | 对已有 definition、job、Shell 和清单执行所选检查 | [产物检查](generation-checks.md) |
| 旧 Python 适配 | 旧复制、配置渲染等入口的历史返回和副作用 | [旧接口适配](legacy-adapters.md) |

真实消费者的实测边界统一见[开发测试](../develop/testing.md)；版本窗口和迁移历史见[CLI 迁移](cli-migration.md)及开发记录，不混入当前契约的定义。

## 标准路径与历史入口

新应用优先使用 `Application.prepare()`、`takflow.build` 和公共 CLI。`takflow.flow` 与 `takflow.jobspec` 是这条主路径中的领域能力；`takflow.generation` 是标准 workflow 阶段复用的低层生成编排入口。

旧 toolkit 适配器、应用自有 CLI 和历史 handler 仍用于兼容既有消费者，但不应与标准路径拼接成另一套并行的构建生命周期。旧复制与配置接口见[旧接口适配](legacy-adapters.md)；迁移时先阅读[CLI 迁移](cli-migration.md)，公共入口及兼容边界见[公共 API 与兼容策略](public-api.md)。

## 阅读下一步

- 第一次构建应用：阅读[应用声明](application.md)和[标准构建](build.md)，再用[toyflow 快速上手](../quickstart.md)对照底层 API；toyflow 的旧 CLI 不是标准入口。
- 已了解示例、需要补齐领域能力：依次阅读[配置](config.md)、[资源层](resource-layers.md)、[流程与钩子](flow-and-hooks.md)和[作业资源](jobspec.md)。
- 需要生成和验收产物：阅读[标准构建](build.md)、[标准命令契约](cli.md)和[产物检查](generation-checks.md)。
