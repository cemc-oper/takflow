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
可选凭证通过 `credential_enabled=False` 或接收有效 config 的布尔判定函数显式选择，TYM 等未启用的应用无需空 handler；
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
| `ResourceLayer(name, root, config_field=None, required_inputs=())` | base 后按声明顺序覆盖，扩展层在后；名称唯一；配置目录字段的非空值优先于 root，配置相对路径基于 source_dir、canonical overrides 基于调用 cwd；required_inputs 是本层必须提供的相对文件，不能由其他层或旧输出满足；静态与模板共用层序及来源记录 |
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

`render_orvix_resource_block(...)` 模板 helper 由 takflow 按 `config.workflow_mode`
自动选择资源表达方式。ecFlow 模式下，queue、project、application 分别引用 `%QUEUE%`、
`%WCKEY%`、`%APPLICATION%`，time、nodes、ntasks-per-node 分别引用
`%WALLTIME:默认值%`、`%NODES:默认值%`、`%TASKS_PER_NODE:默认值%`；Shell/takler 模式直接渲染传入值。应用模板只传资源值，
无需自行判断模式或拼接这些引用。调用 `set_runtime` 为 suite 设置全局 workload 默认值，
为任务传入 `task_resource` 设置其队列、time 和并行布局；项目和应用名由上级节点继承。
未配置的 time、nodes、ntasks_per_node 不生成节点变量，继承上级设置或使用模板编译值作为默认值。
串行任务不生成节点数和每节点 task 指令。未传 application 时
省略该指令；如果应用模板提供 application 默认值而 workload 未配置标签，则使用
`%APPLICATION:默认值%`，保留模板默认值并允许 ecFlow 变量覆盖。直接调用 Python 函数
`takflow.toolkit.job.render_orvix_resource_block` 在未传 `workflow_mode` 时仍按原样渲染参数。

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

### 组合 oper 的最终声明（TC-10.4）

`config_type`、`brand`、`variables` 和 `credential_enabled` 属于最终 Application，
不由扩展隐式合并。应用工厂可用 `dataclasses.replace(base, config_type=OperConfig,
extensions=(*base.extensions, oper_extension), ...)` 明确选择最终类型与规则；品牌、变量
和凭证选择无需变化时沿用 base。配置继承、具体变量和凭证字段由应用维护，不自动建立
多个模型、品牌或变量字典的合并协议。MCV/GFS oper 当前均沿用 base 品牌；MCV
凭证选择读取最终 config.enable_credential，base 和 oper 片段按已声明优先级组合，
GFS oper 当前关闭凭证能力。

品牌、变量、可选层及 outputs 选择器读取同一个已验证 config；credential_enabled
在凭证阶段读取该对象。Application.context 先执行，再按扩展顺序执行 context；
每项贡献接收相同基础 BuildContext，不读取前一贡献临时合并后的 domain_context。
所有贡献成功后才形成最终模板上下文，config、job、额外模板与凭证模板共用它。
outputs 的选择发生在 context 贡献之前，接收 config；实际渲染时可使用最终合并的领域数据。

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
错误消息使用受控诊断。MCV shadow 和 GFS base Execution 的实际贡献可使用这些接口；
GFS oper 的观测拒绝边界仍由应用判定。

### 按有效配置选择可选输入（TC-09.6）

`Application.resource_layers/outputs` 和 `ApplicationExtension.resource_layers/outputs`
既可以保持固定 tuple，也可以传入 `selector(config) -> tuple`。Application 的
required_machine_fragments 同样接受该形式。每个选择器在一次 prepare 中只调用一次，
读取同一个已验证配置；base 的默认资源 factory 先按需调用一次并解析成有效目录，
因此层选择器能从 config.workflow_repo_base_dir 构造其子目录。现有 config_field
字段仍按表中规则解析，不增加第二次 YAML 加载或领域模型校验。

资源层按 `base → Application.resource_layers → 各 ApplicationExtension.resource_layers`
的声明顺序选择并解析。每项贡献解析完成后再调用下一项贡献的选择器，因此后续扩展
能从前面 `config_field` 的有效绝对根（包含包默认）派生观测子目录。一个选择器返回的
tuple 内各层随后依次解析；该选择器执行期间不能读取其尚未返回的层的解析结果。
依赖 oper 根的独立观测层应声明在 oper 贡献之后，未启用时返回空 tuple；框架不替应用
推断启用条件。MCV 的 shadow 按 ecFlow 与 observability.enabled 选择资源条目，
GFS base 的 Execution 试点使用 base 后的 execution 层；GFS oper 仍拒绝观测模式。

`config_field` 必须使用规范字段名，历史字符串 alias 由原配置模型校验；Python
canonical overrides 在校验前替换 alias 值。YAML 根相对 YAML 所在目录，mapping/model
根相对 source_dir；相对 canonical override 基于调用 cwd；声明的默认 root 基于调用
cwd。显式 workflow_repo_base 仅替换 base，扩展仍按自己的有效字段或包默认解析。
静态 ResourceEntry、config/job、TemplateOutput 与嵌套 Jinja include 均使用最终层序，
同名项后层覆盖、缺失项向前回落。公共结果中静态文件保留有序 layer/path 来源，渲染
产物的 template 指向选中的源文件；成功清单记录相同的层根，不记录模板正文。

选择结果固定在 BuildPaths.resource_layers、BuildContext.outputs 和
BuildContext.required_machine_fragments；完整与单步构建读取同一结果。
选择器只返回数据，不复制、写出或执行脚本。扩展初始化仍在加载配置前执行，
可选层/产物不构成按配置接管完整阶段或重排业务 Hook 的接口。

选定层的 required_inputs 在 resource 复制前逐项检查来源、类型及可读性。
用它声明必须存在的覆盖文件，可以防止缺少扩展 head 时悄悄落回基础 head；
未选择的层不会被检查。普通稀疏覆盖继续使用不带这些必需项的 ResourceLayer。

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

## 业务 Shell 延后加载 machine（TC-08）

`required_machine_fragments=("env/forecast_mpi.sh", ...)` 声明业务脚本将在原位置 source 的片段。资源阶段先检查本轮所选 machine 的有序来源，再复制并登记引用；输出目录中的陈旧文件不能代替缺少的来源。默认目录检查存在性与摘要，显式外部目录保持 unchecked、不作生成机探测。框架不执行或提前 source，不改变业务 cwd/作用域，不自动把片段正文嵌进父作业。片段内容、加载位置和库/MPI 参数继续由消费者维护。

MCV oper、GFS oper及独立RA2已使用同一资源层、显式初始化和公共构建服务。MCV通过配置声明上传必需输入，GFS oper另按实际任务的ECF引用检查最终模板；目录/领域规则留应用。`ApplicationExtension`不新增整套handler接管口。


`required_resource_inputs` 为相对文件名元组或接收有效 config 的纯判定函数，用于声明选定业务能力的必需脚本/模板。资源阶段从同一有序来源验证输入，缺失即失败，输出目录里的旧 job 不作替代。MCV oper 只在上传启用时声明其上传 job 模板和脚本；稀疏 oper 不启用上传时仍可回落基础资源。

## 初始化的注册表所有权（TC-10.2）

每次 prepare 先隔离公共 credential 注册表、Application.registries 与各 Extension.registries，再按 extensions 顺序初始化，最后加载/校验配置并构造上下文。同一个注册表重复出现在声明中时只进入一次作用域。初始化函数每次显式注册已有函数，导入缓存不会代替注册；非 credential 的领域注册表必须全部列入声明，credential 注册表由框架自动处理。

作用域内从空注册表开始，调用者的外来注册不会参与本轮构建。正常退出或初始化、校验、上下文及构建失败时恢复原表，KeyboardInterrupt/SystemExit 也不遗留本轮注册。Python 调用保留原异常或公共 BuildError.original，CLI 使用既有受控错误和中断退出码；作用域恢复不回滚生成文件。MCV/GFS 的真实消费者回归位于 test-suite/tests/test_oper_initialization.py，框架必测还验证重复声明、部分初始化及基础异常。该保证适用于顺序调用，不承诺共享单例的并发隔离。

## 已验证消费者与可选能力范围

标准声明和Python/CLI共用一套机制，领域能力的支持范围分别声明：

| 能力 | 已验证消费者及边界 |
|---|---|
| 完整组件选择 | TYM的model/data/graph/typhoon；Shell仍按原业务限制排除graph。MCV shadow资源筛选与GFS试点job筛选属于局部消费者 |
| 配置变量通道 | MCV base/oper的有效覆盖、Shell字面值和ecFlow/takler引用；TYM Fortran参数、GFS flags/设置仍保留领域格式 |
| 有序资源、context/outputs与初始化 | MCV/GFS oper及RA2的覆盖/回落、三层来源、完整/分步/CLI、冲突和中断恢复。显式initializer继续使用 |
| 可选凭证 | MCV base→oper组合与RA2 CTS条件；0600和公开报告保护由公共阶段处理，字段/编码留应用，未统一迁移静态历史账户 |
| 可选观测 | MCV base/oper仅ecFlow forecast及五个prepare/bckg wrapper的shadow；GFS base仅ecFlow+inline Execution data试点。GFS oper/RA2明确拒绝，不创建运行身份或统一状态机 |

观测默认关闭，关闭不要求SDK或目标配置；启用只选择已声明输入，不授予运行资格。同目录启停按本轮结果和任务引用判定，旧文件可以保留，但不能替代当前必需源输入。RA2的CTS动作flag关闭仍保留上传任务族，不等同于整体上传关闭。生成、原生预处理、SDK夹具与现场业务证据应分别登记。

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

工作区的 `framework/takflow-test-suite/tests/mcv/base/coldstart/{ecflow,shell}/basic/`
提供对应集成用例。两个教程的生成检查可在本地执行，现场加载、调度、资料和产品的验收条件
在应用教程中给出。公共路径覆盖、分步和诊断语义见[标准构建](build.md)与[命令契约](cli.md)。
