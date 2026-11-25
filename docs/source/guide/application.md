# 应用声明与有效上下文

`takflow.application` 提供应用声明、一次配置加载和有作用域的有效上下文。资源复制、模板写出、作业/流程保存和完整成功清单由[标准构建](build.md)消费同一上下文，公共命令见 [CLI 契约](cli.md)。`prepare` 不写生成文件。

本页聚焦配置、路径、上下文和扩展生命周期。脚本、模板、include、组件和 machine 的声明与选择集中在[资源层、组件与 machine](resource-layers.md)。

## 公开入口

```python
from takflow.application import Application, ApplicationBrand

application = Application(
    config_type=WorkflowConfig,          # 已有领域配置类
    resources=get_resources_path,        # 已有包资源公开函数，也可直接传 Path
    suite_builder=build_suite,           # (config, engine) -> Node
    brand=lambda config: ApplicationBrand(
        "my-workflow", "0.2.0", f"MyModel {config.model_version}"
    ),
)

with application.prepare(
    "config.yaml",
    output_repo_base="build",
    overrides={"workflow_name": "daily"},
) as context:
    print(context.paths.workflow_output)
    # 标准构建阶段在此作用域中消费同一 context。
```

必需声明是 `config_type`、`resources` 和显式 `brand`。默认只声明 ecFlow 支持，
definition 模式要求 `suite_builder`，shell 模式要求 `shell_template`。
可选凭证通过 `credential_enabled=False` 或接收有效 config 的布尔判定函数显式选择，未启用的应用无需空 handler；
凭证文件输入及生成/缺失/skipped 结果由标准构建处理。观测选择沿用有效 config.observability。
`supported_modes` 必须反映实际消费者能力；公共模型接受 takler 不代表应用已支持它。
接口直接引用 Python 对象，允许入口分布在多层包中，不要求统一文件名或动态插件发现。

`Application.prepare(source, *, source_dir=None, overrides=None,
output_repo_base=None, workflow_repo_base=None, output=None)` 返回上下文管理器，
`with` 内得到 `BuildContext[ConfigT]`。`source` 可为 YAML 路径、原始 mapping 或
已验证的领域模型。不能在离开作用域后继续构图、执行 Hook 或依赖作用域中的品牌。

## 加载、覆盖与路径

生命周期依次为：隔离声明的注册表 → 按声明顺序初始化扩展 → 读取一次原始配置 →
canonical 覆盖 → 可选领域 `normalize_config` → 本地路径归一化 → 原领域模型校验一次 →
路径/资源层/能力预检 → 品牌、组件、变量和领域上下文。退出或任何异常均恢复注册表和品牌。

复用 `takflow.config.load_config_data`、`apply_config_overrides`、`validate_config`；
历史 `load_config_from_file` 和 `load_validated_config` 的签名及异常策略保持。
`load_config_data` 返回原始 YAML mapping，`apply_config_overrides` 返回独立副本，
两者使用现有 `ConfigValidationError` 受控诊断。覆盖整字段替换，非深合并，保留显式
None 与省略的区别；复杂 AliasPath/AliasChoices 的覆盖仍明确拒绝。

| 输入 | 相对路径基准与优先级 |
|---|---|
| 配置中的 output/workflow repo | YAML 所在目录；raw mapping 需提供 `source_dir` |
| `overrides` 中的 repo、显式 repo 参数 | 调用 `prepare` 时的 cwd；显式参数覆盖 overrides |
| 声明的包/扩展资源根 | 调用时 cwd；推荐包公开函数返回绝对 Path |
| 资源来源优先级 | 显式参数 > 有效配置 > 包默认；仅替换 base 层，扩展层保留 |
| definition `output` | 绝对值照用；相对值以最终输出根为基准 |
| shell runner | 固定 `<output_root>/run_workflow.sh`；拒绝 definition `output` 参数 |

输出根必需；内部本地路径是绝对 `Path`，不展开环境变量或命令替换。
`project_base_dir`、`run_base_dir` 和外部 machine 等目标端路径不做本机 resolve/exists。
首版使用同一个逻辑/物理输出根，移动产物后引用是否仍有效不在此承诺内。

已验证模型采用深拷贝，不 dump/rebuild，不重新运行可能有副作用的领域 validator；
含相对路径时仍要求 `source_dir`。模型输入拒绝配置/repo 覆盖，需要覆盖时改传原始
mapping 或文件，以保证覆盖先于派生。显式 definition `output` 仍可设置。
`strict_fields=False` 保留领域模型的 extra 策略；对 raw 输入显式启用 True 时，
要求 `takflow[strict-config]` / Pydantic>=2.12。基础路径继续支持 Pydantic>=2.0。
已验证模型无法恢复此前被丢弃的未知字段，严格未知字段验收应使用 raw 输入。

`BuildPaths` 提供 `output_root`、有序 `resource_layers`、`workflow_output`、`config_dir`、
`config_file`、`jobs_dir`、`scripts_dir`、`ecflow_include` 和 `takler_include`。
标准 config 为 `config/config.h`（ecFlow）或 `config/config.sh`，作业统一为 `jobs/`。
现有低层 `takflow.flow.generate` 的显式 output 原样解释规则、Context/Result、保存回调顺序不变；
新标准路径仅在 `Application` 边界解释。

## 数据声明与领域扩展

| 声明 | 责任与限制 |
|---|---|
| `variables(config)` | 返回名称为变量标识符、值为 str 的映射；值由领域计算，编码和实际导出由标准构建负责 |
| `context(context)` | 返回领域模板数据，不接管 renderer；应用贡献先于扩展，键冲突报错；各贡献读取相同基础上下文 |
| `normalize_config(data)` | 在覆盖后处理领域旧输入，返回 raw mapping，不加载第二份配置或执行环境脚本 |
| `required_operations(config)` | 返回已有后端操作名，复用公共能力预检，不建立新 IR |

`BuildContext.template_context()` 返回只读外层 mapping，包含 config、paths、brand、
components、machine、variables、两个 build_info 行以及领域贡献。保留键还包括
`include_raw`、`invoke_script`、`include_machine`、`render_orvix_resource_block`、`render_slurm_resource_block`、stdout/stderr，
领域贡献不可覆写。底层 config 及嵌套领域对象仍是 Python 模型，按只读契约消费。

资源指令 helper 的注册时机、直接 Jinja 入口、参数和模板回退规则统一见[作业资源](jobspec.md)。

`ApplicationExtension(name, initialize=None, registries=(), resource_layers=(),
context=None, outputs=())` 只提供局部初始化、数据和规则，名称必须唯一。资源与输出的选择见[资源层](resource-layers.md)；初始化顺序、注册表隔离和恢复见{ref}`初始化的注册表所有权 <registry-ownership>`。

不接受 resource/config/job/workflow 整套 handler 注册，也不提供阶段接管开关。
业务构图、科学配置、组件判定、变量值、模板、Shell runner 调用序列与领域 Hook 内容由应用维护。
Jinja 环境、复制、写出、凭证组合、作业生成、清单、完整/分步结果及公共命令属于标准构建与公共 CLI。

### 组合 oper 的最终声明

`config_type`、`brand`、`variables` 和 `credential_enabled` 属于最终 Application，
不由扩展隐式合并。应用工厂可用 `dataclasses.replace(base, config_type=OperConfig,
extensions=(*base.extensions, oper_extension), ...)` 明确选择最终类型与规则；品牌、变量
和凭证选择无需变化时沿用 base。配置继承、具体变量和凭证字段由应用维护，不自动建立
多个模型、品牌或变量字典的合并协议。

品牌、变量、可选层及 outputs 选择器读取同一个已验证 config；credential_enabled
在凭证阶段读取该对象。可选层与额外输出的选择和来源规则见[资源层](resource-layers.md)。
Application.context 先执行，再按扩展顺序执行 context；
每项贡献接收相同基础 BuildContext，不读取前一贡献临时合并后的 domain_context。
所有贡献成功后才形成最终模板上下文，config、job、额外模板与凭证模板共用它。

保留键或贡献之间重名使用 APPLICATION_CONTEXT_CONFLICT，诊断不含冲突值。
machine 变量沿用 APPLICATION_VARIABLE_CONFLICT；OUTPUT_REPO_BASE 必须与有效
输出根一致，标准阶段使用 BUILD_VARIABLE_CONFLICT 检查。额外产物不会静默覆盖
其他贡献、运行配置、凭证、definition、清单、静态文件或 job；复用 BUILD_OUTPUT_COLLISION，
诊断在发现冲突的阶段返回部分结果。prepare 贡献失败尚未开始生成；已开始的变更阶段
清除上一份成功清单，部分产物按实际写出记录。

凭证及 mode=0o600 的额外输出保留路径、权限和来源元数据，公开报告与清单不含正文
或内容摘要；这同样适用于写出后因后续碰撞而失败的部分结果。原始配置、canonical
覆盖值、domain_context 和凭证 mapping 不写入这些报告。应用仍负责把敏感模板声明为
0600 并避免把敏感字段放入公开产物或品牌。实际异常对象保留给调用者，公开 CLI 和
错误消息使用受控诊断。

## 品牌

`ApplicationBrand(tool_name, version, target_model=None)` 在上下文中固定本轮头部与构建时间。
应用准备期间，作业渲染读取当前作用域的文件头。独立渲染可用
`takflow.build_info.build_info_scope(lines)` 指定文件头，作用域退出时恢复外层品牌。
作用域外的独立作业渲染使用 `takflow vunknown`。JSON 等原生格式的品牌信息由保存阶段写出。

## 构图消费有效路径

`context_suite_builder(context, engine)` 是 `suite_builder(config, engine)` 的可选替代，二者互斥。新增字段位于声明末尾，不改变既有位置参数；原签名继续工作。需要输出/组件路径的应用可直接从本轮 `BuildContext.paths` 构图，无需把运行上下文塞回配置、使用全局变量或重新推导布局。仅 definition 模式调用，Shell 仍由声明的模板生成。

(registry-ownership)=
## 初始化的注册表所有权

每次 prepare 先隔离公共 credential 注册表、Application.registries 与各 Extension.registries，再按 extensions 顺序初始化，最后加载/校验配置并构造上下文。同一个注册表重复出现在声明中时只进入一次作用域。初始化函数每次显式注册已有函数，导入缓存不会代替注册；非 credential 的领域注册表必须全部列入声明，credential 注册表由框架自动处理。

作用域内从空注册表开始，调用者的外来注册不会参与本轮构建。正常退出或初始化、校验、上下文及构建失败时恢复原表，KeyboardInterrupt/SystemExit 也不遗留本轮注册。Python 调用保留原异常或公共 BuildError.original，CLI 使用既有受控错误和中断退出码；作用域恢复不回滚生成文件。`BaseHookRegistry.isolated()` 同样可单独使用；优先级、同优先级顺序及领域 Hook 调用时点保持。该保证适用于顺序调用，不承诺共享单例的并发隔离。

消费者验证范围与可选能力的实测边界见[开发测试](../develop/testing.md)，不作为阅读本页契约的前置条件。

(mcv-s1-reference)=
## MCV S1 真实应用参考

MCV S1 将同一 GMF 冷启动场景用于 ecFlow 定义和 Shell runner。两份教程均使用
`machine_name: hpc2023`，生成 24 小时预报的配置与作业，并给出标准 CLI、
直接 `Application.prepare` / `build` 和成功清单检查。
在工作区打开 `app/mcv/mcv-workflow` 的下列文件。应用源码与教程由 MCV 维护。
[MCV 工作区仓库](http://e.mc.met.cma/codingcorp/mcv-gfs/mcv-workflow)。

| 查阅内容 | MCV 仓库中的位置 |
|---|---|
| 配套安装、程序与站点准备 | `docs/source/getting_started/installation.rst` |
| ecFlow 和 Shell 的 YAML、构建命令与目录树 | `docs/source/getting_started/s1_ecflow.rst` 和 `s1_shell.rst` |
| 声明、派生上下文与业务组件边界 | `docs/source/develop/design/architecture.rst` |
| 应用工厂与领域源码 | `src/mcv_workflow/application.py`、`src/mcv_workflow/config/`、`src/mcv_workflow/flow/` |
| 模板、业务脚本与 machine 片段 | `src/mcv_workflow/resources/` |

工作区的 `framework/takflow-test-suite/experiments/mcv/base/coldstart/{ecflow,shell}/basic/`
提供对应集成用例。两个教程的生成检查可在本地执行，现场加载、调度、资料和产品的验收条件
在应用教程中给出。公共路径覆盖、分步和诊断语义见[标准构建](build.md)与[命令契约](cli.md)。
