# 公共 API 与兼容策略

本文面向 takflow 应用维护者，约定可以依赖的 Python 入口，以及 Python API、应用 CLI、
生成产物和 jobspec 契约各自的兼容边界。后端操作的支持状态另见
[后端能力矩阵](backends.md)，jobspec 的所有权和同步流程见
[版本与兼容管理](../develop/versioning.md)。

## 1. 三套版本信息不得混用

| 信息 | 读取方式 | 含义 |
|---|---|---|
| takflow 包版本 | `takflow.__version__` | Python 包的发布版本，由 takflow 仓库 git tag 经 `setuptools_scm` 生成 |
| jobspec 契约版本 | `takflow.spec.jobspec.contract_version()`，权威来源为 vendor `VERSION` | orvix 拥有的语言无关资源契约语义化版本；当前快照见 [jobspec 契约](../reference/jobspec-schema.md) |
| orvix 来源 pin | vendor `ORVIX_VERSION` | 当前只读副本对应的 orvix git ref；与契约版本在同一快照页展示 |

`ORVIX_VERSION` 是来源标识，不是 takflow 包版本或 jobspec 语义化版本。takflow 发布、
jobspec 契约升级和 orvix pin 更新可以分别发生，不做机械同步 bump。takler definition 的
`schema_version` 也是另一种格式版本，不属于 jobspec 版本体系。

## 2. 公共 Python API

### 2.1 推荐入口

下表中的包根部 re-export、`__all__` 符号，以及 API 参考页明确列出的模块和公开类/函数，
构成当前公共 Python API。新代码优先使用表中的包根部入口；需要 hook、低层 serializer 或
可选能力时，使用相应已列出的模块入口。

| 公共命名空间 | 主要入口与用途 |
|---|---|
| `takflow` | `__version__`；只暴露包版本，不承载应用生成入口 |
| `takflow.config` | `BaseWorkflowConfig`、`load_config_from_file`、workload/scheduling 配置、`FortranBool` 和变量组装 helpers |
| `takflow.config.workload/scheduling/workflow/types` | API 参考页列出的配置模型与字段 helpers；需要明确模块路径时可继续使用 |
| `takflow.jobspec` | `TaskResource`、`ResourceSpec`、`to_orvix_directives`、`render_resource_block` |
| `takflow.jobspec.highlevel/model/render` | API 参考页列出的高层模型、扁平契约模型和指令渲染器 |
| `takflow.spec.jobspec` | `contract_version`、`load_schema`、`schema_keys`、`schema_path`；只读访问 vendor 资源 |
| `takflow.flow` | `WorkflowEngine`、`Node`、`NodeType`、`WorkflowBackend`、通用 hook 基类和工厂 |
| `takflow.flow.node/backend/hook` | 公共节点、后端抽象和 hook 实现；现有应用直接使用 `flow.hook` 的方式继续受支持 |
| `takflow.backends.ecflow` / `takflow.backends.takler` | `EcflowBackend` / `TaklerBackend`；能力差异以矩阵为准，takler 是可选运行时依赖 |
| `takflow.backends.ecflow.serializer` | 已文档化的纯 Python ecFlow 低层 serializer；新应用优先使用 `EcflowBackend` |
| `takflow.backends.runtime` | `set_runtime`、`set_scheduling`、`common_setting`、脚本变量和 shell job helpers |
| `takflow.toolkit` | resource/job/credential 的可复用生成入口及已导出的 observability helpers |
| `takflow.toolkit.job/resource/credential/observability` | 已文档化的模板渲染、资源复制、credential hook 和静态 definition manifest 入口 |
| `takflow.build_info` | `BuildInfo`、`get_build_info`、`get_build_info_lines` |

可选依赖不改变默认导入契约：没有 takler 包时可以导入 `takflow` 和
`takflow.backends.takler`，但实例化 `TaklerBackend` 会明确抛出 `ImportError`。可选
observability 校验能力的依赖和启用条件见[可观测性](observability.md)。

### 2.2 兼容 facade 与历史入口

- `takflow.toolkit.util` 是 `takflow.backends.runtime` helpers 的兼容 re-export facade；
  `takflow.toolkit` 根部的相关 re-export 同样保留。facade 必须委托同一实现并保持行为一致。
- `takflow.flow.register_hook` 是 `create_hook_decorator` 的现有兼容别名，不因推荐名称存在而
  直接删除。
- 包根部和已列出模块之间的 re-export 都是公共入口。调整其实现位置时，应保留导入路径或按
  下文弃用流程提供 facade，不要求应用跟随内部文件移动。
- 已被应用或测试使用的非下划线历史入口，即使尚未列入 `__all__`，也不能仅凭这一点视为可
  立即删除的内部实现。先登记消费者并评审是否转为推荐 API 或兼容 facade；新代码不要据此
  扩大未文档化 API 的使用范围。

### 2.3 非公共实现

以下不属于稳定 API：以下划线开头的模块、类、函数和变量，未列出的内部实现模块，
`takflow._version` 生成文件，测试/conformance harness 内部，以及后端原始引擎对象的私有
属性。`Node.raw` 可用于明确需要的引擎特异操作，但原始对象的私有状态不在 takflow 兼容承诺内。

## 3. 应用 CLI 的兼容边界

takflow 当前没有 `takflow.cli` 或公共 console script。`mcv-workflow`、`mcv-oper-workflow`、
TYM、toyflow 等命令及其 `resource/config/job/workflow/credential` 命令组、历史选项、默认值和
输出路径覆盖优先级由**各应用仓库**拥有和发布。

因此：

- takflow 包版本不替代应用 CLI 的版本和变更记录；toolkit 的 Python API 变更也不等于 CLI
  选项变更。
- 不在框架升级中静默统一 `--config`/`--config-file`、删除历史选项或改变既有路径优先级。
- 应用 CLI 的弃用提示、兼容别名和移除版本由所属应用记录；未来是否提供公共 CLI 仍由独立
  决策任务评审，本文不预先作出承诺。

## 4. 生成产物的兼容边界

生成产物包括 ecFlow `.def`、takler definition JSON、shell runner、作业脚本、配置文件和
credential 文件。其兼容面是文件布局、节点路径、变量/指令、触发和提交命令语义，而不是承诺
不同 takflow 版本之间永远逐字节相同。

- 有意的生成变化必须附 golden diff，并声明全部差异；不能用更新 golden 掩盖未解释变化。
- 修复、格式化或新增内容是否兼容，按现有消费者能否继续加载和运行判断，并在发布记录中说明。
- 节点路径、变量语义、definition 结构或提交命令的不兼容变化需要迁移说明和相应消费者验证。
- Python API 保持不变不代表生成产物必然不变；反过来，生成产物变化也不要求 jobspec 契约
  bump，除非语言无关 jobspec 本身发生变化。

## 5. jobspec 契约的兼容边界

jobspec 的 schema、19 个指令键、语义化版本和 conformance golden 由 orvix 唯一拥有，takflow
只保存 pin 对应的只读 vendor 副本。契约 MAJOR/MINOR/PATCH 规则和同步流程见
[版本与兼容管理](../develop/versioning.md)。

`TaskResource`/`ResourceSpec` 同时处于 Python API 和 jobspec 消费边界：修改字段、类型或编译
语义时必须分别评审两类影响。需要新增或修改契约键时先从 orvix 发起，不能在 takflow 本地
通过修改 vendor 文件完成升级。

## 6. deprecate、facade 与破坏性变更

### 6.1 变更规则

- **takflow 1.x 起**：向后兼容的功能进入 MINOR，修复进入 PATCH；删除公共入口或其他不兼容
  变化进入 MAJOR。0.x 阶段如必须发生破坏性变化，也必须在发布记录中醒目标注并提供迁移说明，
  不能因为版本号小于 1 而静默删除。
- **deprecate**：在变更记录中写明旧入口、替代入口、弃用版本和计划移除版本。Python API 在
  可行时发出 `DeprecationWarning`；仅文档弃用必须说明原因。默认先弃用再移除，不在同一变更中
  无记录地删除。
- **兼容 facade**：旧入口委托新实现，保持参数、返回值和副作用语义；增加覆盖旧入口和新入口
  的测试。facade 需要移除时同样走弃用流程。
- **破坏性变更**：说明消费者影响、迁移步骤、计划发布版本和需要的 golden/消费者验证。无法
  预先弃用的正确性或安全修复，必须明确说明例外原因。

弃用周期以变更记录中公布的移除版本为准，不隐式承诺固定时长；维护者应根据实际消费者和
发布节奏评审，而不是让兼容入口无记录地消失。

### 6.2 必须同步的记录

每次公共 API 弃用、facade 调整或破坏性变更必须同时更新：

1. 本文的公共入口或兼容说明，并在变更记录中列出旧入口、替代入口和版本；
2. 发布说明/迁移说明及相应测试；
3. 涉及生成产物时的 golden diff，涉及 jobspec 时的 orvix 契约版本和 pin 同步记录。

当前没有已宣布的 takflow 公共入口弃用项。首项弃用发生时，在本节增加“版本、类型、旧入口、
替代入口、计划移除/迁移说明”的记录表。
