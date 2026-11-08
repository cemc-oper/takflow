# 应用声明与有效上下文

`takflow.application` 提供应用声明、一次配置加载和有作用域的有效上下文。
TC-05 交付准备生命周期；资源复制、模板写出、作业/流程保存、完整成功清单
由 [TC-06 标准管线](build.md)消费同一上下文，公共命令见 [CLI 契约](cli.md)。`prepare` 不写生成文件。

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
    # TC-06 的阶段在此作用域中消费同一 context。
```

必需声明是 `config_type`、`resources` 和显式 `brand`。默认只声明 ecFlow 支持，
definition 模式要求 `suite_builder`，shell 模式要求 `shell_template`。
可选凭证通过 `credential_enabled=False` 显式选择，TYM 等未启用的应用无需空 handler；
凭证文件输入及生成/缺失/skipped 结果由 TC-06 处理。观测选择沿用有效 config.observability。
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
现有低层 `takflow.generation` 的显式 output 原样解释规则、Context/Result、保存回调顺序不变；
新标准路径仅在 `Application` 边界解释。

## 数据声明与领域扩展

| 声明 | 责任与限制 |
|---|---|
| `ResourceLayer(name, root)` | base 后按声明顺序覆盖，扩展层在后；名称唯一；模板搜索应按反向层序，TC-06 实现复制/搜索与来源记录 |
| `ResourceEntry(source, destination, executable=False, required=False)` | 声明静态目录/文件映射，路径相对且不逃逸；默认 scripts、ecflow/include、takler/include、utils；迁移映射由应用给出，不新增应用名 profile |
| `TemplateOutput(template, output, required=True, mode=0o644)` | 声明额外模板产物，mode 仅 0644/0755/0600；TC-06 检查实际模板、目标碰撞、编码、权限及写出 |
| `select_components(config)` | 只计算一次，返回 `ComponentSelection`；enabled 与两个路径分类器供资源/作业共用，不读禁用文件 |
| `variables(config)` | 返回名称为变量标识符、值为 str 的映射；值由领域计算，编码和实际导出由 TC-06 负责 |
| `context(context)` | 返回领域模板数据，不接管 renderer；应用贡献先于扩展，键冲突报错；各贡献读取相同基础上下文 |
| `normalize_config(data)` | 在覆盖后处理领域旧输入，返回 raw mapping，不加载第二份配置或执行环境脚本 |
| `required_operations(config)` | 返回已有后端操作名，复用 TC-03 能力预检，不建立新 IR |

`BuildContext.template_context()` 返回只读外层 mapping，包含 config、paths、brand、
components、machine、variables、两个 build_info 行以及领域贡献。保留键还包括
`include_raw`、`invoke_script`、`include_machine`、`render_orvix_resource_block`、stdout/stderr，
领域贡献不可覆写。底层 config 及嵌套领域对象仍是 Python 模型，按只读契约消费。

`ApplicationExtension(name, initialize=None, registries=(), resource_layers=(),
context=None, outputs=())` 只提供局部初始化、数据和规则。名称唯一；同一个构建各扩展
初始化一次，在配置加载前按声明顺序执行。初始化器应每次显式注册函数，不能依赖仅导入
模块触发 decorator，因为 Python 会缓存 import。列出所有会修改的领域注册表；框架
对每个表只隔离一次，credential registry 自动纳入。退出后原注册恢复；首错保留原异常。
`BaseHookRegistry.isolated()` 同样可单独使用；优先级、同优先级顺序及领域 Hook 调用时点保持。
全局单例注册表不支持并发构建，不在这里承诺完整 oper 扩展组合已经验收。

不接受 resource/config/job/workflow 整套 handler 注册，也不提供阶段接管开关。
业务构图、科学配置、组件判定、变量值、模板、Shell runner 调用序列与领域 Hook 内容由应用维护。
Jinja 环境、复制、写出、凭证组合、作业生成、清单、完整/分步结果及公共命令属于 TC-06/12。

## 品牌和 machine

`ApplicationBrand(tool_name, version, target_model=None)` 在上下文中固定本轮头部与构建时间。
准备作用域使用 `build_info_scope`，现有公共 job renderer 优先消费该作用域的头部；
历史 `set_build_info_provider` 继续服务旧入口，无需 import 应用 job 模块改写全局 provider。
作用域退出后恢复原品牌，顺序应用不会串用；JSON 等原生格式如何记录品牌由保存阶段处理，
这里不向 JSON 注入注释。

公共配置增加可选顶层 `machine_name/machine_dir`。未使用站点能力的应用无需填写；
`require_machine=True` 时必须显式选择。默认目录为最终输出根下的 `machine/<name>`，
原始 config.machine_dir 保持 None，派生结果在 `MachineContext.directory`。
显式 machine_dir 是所选站点目录本身，必须为绝对目标路径，不复制、不回退、不本地探测。

`MachineContext.external` 区分两种来源；`BuildContext.variables` 合入同一份
`MACHINE_NAME/MACHINE_DIR`，拒绝领域覆盖，检查报告注明远端可见性/执行未验。
实际变量写出、所选站点分发和 include_machine 原生引用 helper 由 [TC-06](build.md)提供，
原生消费者、Shell 加载位置及可更新片段语义由 TC-07 验证。

## 构图消费有效路径（TC-07）

`context_suite_builder(context, engine)` 是 `suite_builder(config, engine)` 的可选替代，二者互斥。新增字段位于声明末尾，不改变既有位置参数；原签名继续工作。需要输出/组件路径的应用可直接从本轮 `BuildContext.paths` 构图，无需把运行上下文塞回配置、使用全局变量或重新推导布局。仅 definition 模式调用，Shell 仍由声明的模板生成。

TYM 的 create_suite 接受显式 paths，并把同一 BuildPaths 传给原有 derived 领域函数；完整 config/flow 和 Node 建树组织保留。旧 config/engine 领域入口若未提供 paths，使用 Application.prepare 解析同一上下文，不保留第二套路径公式。

未启用 observability 时，准备报告记录 APPLICATION_OBSERVABILITY_DISABLED，完整清单保留这一可选能力选择；它不授予任何运行资格。
