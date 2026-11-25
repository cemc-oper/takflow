# 标准构建、分步生成与成功清单

`takflow.build` 消费 [Application.prepare](application.md) 的同一有效上下文，不重新读取配置。完整构建和分步调用共享阶段实现。
本页说明完整构建、分步调用、写出、失败恢复与成功清单；不执行 machine、业务程序、引擎 load 或调度提交。
公共 CLI 见[标准命令契约](cli.md)。资源层选择见[资源层、组件与 machine](resource-layers.md)；旧复制和配置接口见[旧接口适配](legacy-adapters.md)，生产入口和布局迁移见[CLI 迁移](cli-migration.md)。

## 调用和结果

```python
from takflow.build import build, run_stage, BuildError

with application.prepare("config.yaml", output_repo_base="build") as context:
    try:
        result = build(context)
    except BuildError as error:
        safe_report = error.result.as_dict()
        original_exception = error.original
        raise
```

`build(context, *, credential_file=None, before_save=None, after_save=None)` 返回 `BuildResult`。
`run_stage(context, stage, *, credential_file=None, before_save=None, after_save=None)` 返回相同类型，
只运行所选阶段，不隐式补跑前置阶段，不发布完整成功清单。必须在 prepare 的作用域内使用。
prepare 的加载/校验失败继续使用配置校验异常；这时尚未开始写出，不虚构本轮阶段产物。

阶段顺序为 `resource → config → credential → job → workflow → report`。
分步调用检查相同前置条件；例如 job 要求运行配置及所选脚本已准备。
每次调用只登记自己的写出，已有前置文件不会因为存在就变成本轮产物。
多个步骤成功也不会自动升级为完整成功，需要显式完整 build 才发布清单。

| 结果字段 | 契约 |
|---|---|
| scope / complete / build_id | full或stage、本轮是否完整成功、本轮调用身份 |
| mode / output_root / workflow_output | 有效模式、绝对输出根、definition或runner位置 |
| stages: list[StageResult] | name/status/reason/skipped_outputs；passed、failed、skipped、not_run |
| artifacts: list[BuildArtifact] | 路径、角色、负责阶段、generated/copied/reference、mode、sha256、来源、mutable/sensitive |
| diagnostics | 保留生成检查的 code/stage/object/reason/status 及配置校验的 code/path/reason/stage，无原始配置或异常正文 |
| generation | 现有低层 GenerationResult，供薄适配读取output_path/suite，不进入JSON报告 |
| manifest_path | 只有完整成功发布后存在，其他调用为None |

`BuildError` 的公开消息及 `result.as_dict()` 为受控展示；`original` 和 `__cause__` 保留捕获到的同一原异常。
默认日志/CLI 不应打印可能含敏感值的异常正文或 traceback。
标准构建作用域中的公共 Hook 错误日志不含异常正文，旧入口的默认日志行为保持。

## 默认阶段

资源阶段复用 toolkit 复制计划和检查，按声明层序覆盖；记录实际来源与覆盖层。
ResourceEntry 支持目录和单文件，组件分类在读取内容前筛选，保留选中的空目录。
显式 executable=True 的文件0755，普通文件0644，目录0755；覆盖已有文件同样设置精确权限，不受umask影响。
machine 由公共选择管理，拒绝手工ResourceEntry复制整个machine树。

所有模板使用相同资源层，最高优先层先搜索，UTF-8/LF、StrictUndefined、lstrip_blocks、trim_blocks、keep_trailing_newline。
配置输出config/config.h或config/config.sh，0644；额外TemplateOutput使用同一环境、上下文和权限规则。
可选缺模板记录skipped_outputs，模板内部渲染错误仍失败。物理别名、角色碰撞和覆盖已知输入会拒绝。

凭证由credential_enabled选择，关闭时skipped，不要求空handler；启用时未给文件、输入缺失及无注册贡献分别诊断。
复用credential toolkit组合局部贡献，标准路径使用严格环境和0600，写入前/期间即受保护。
单独凭证步骤不放宽已有父目录权限。旧render_credential默认0700和None返回保持。

作业复用目录 renderer、include_raw、invoke_script 和资源指令 helper，统一写入 jobs/，权限为 0755。
标准Environment只渲染最终有效模板，禁用组件不读模板正文；inline先准备脚本，external正确引用路径。
已启用的 ecFlow task 指向本地 jobs 目录时，完整 build 要求本轮已渲染相应 job。分步 workflow 可以消费已准备的输出。

流程继续调用takflow.flow.generate.generate_workflow。
definition回调仍为builder → before_save → save → after_save，异常保留原异常与已写文件。
标准definition为0644、shell runner为run_workflow.sh/0755，原生JSON不插注释品牌头。
before_save/after_save为已有保存扩展点，不用整套handler替换默认阶段。

## 变量与machine

框架从输出根提供OUTPUT_REPO_BASE，合并BuildContext.variables的同一有效映射，包含MACHINE_NAME/MACHINE_DIR，实际写出export。
shell/takler配置写Shell字面值；ecFlow配置写原生变量引用，保存前将这个显式导出通道的suite值编码为Shell字面值。
空格、引号、美元符号替换后仍为数据；其他领域变量保持原语义。直接在引擎alter导出通道时，也须提供对应Shell字面值。
标准ecFlow保存作用域使用原生规则保留混合单/双引号，不加入改变变量值的额外反斜杠。
旧入口默认写出保持；公共定义检查同时认识两种兼容写法，标准调用退出作用域后仍可复验。

模板helper `include_machine("env/runtime.sh")` 不内嵌正文、不执行片段。
默认只复制所选machine/<name>，ecFlow生成绝对includenopp，shell/takler生成正确引用的点号加载。
普通Shell与需原生预处理的旧片段仍需消费者分类，要求source语义的业务入口保持原作用域。
显式 machine_dir 的片段登记为外部引用，留到目标环境读取。
本地片段检查存在性并记录构建时摘要。copied/reference 均标 mutable，允许构建后更新。
缺失/不可读仍在当前可检查范围内失败。ecFlow后续新建job读取更新，已展开job不自动改变；shell在加载时读取。

## 失败和清单

配置在 `prepare` 期间失败时，此前的输出和成功清单仍代表上次构建。完整或分步生成在进入第一个改写阶段前撤下旧清单。若撤下失败，`BUILD_MANIFEST_INVALIDATE` 指出清单路径，生成随即停止。

资源复制、模板渲染或写出失败时，本阶段为 `failed`，后续阶段为 `not_run`。Python 调用者可从 `BuildError.original` 取得原异常，从 `BuildError.result` 取得受控原因与已确认的部分产物。目录保留失败时的文件。修正输入后可在同一目录重新构建。

完整构建写完产物后，report 阶段将清单写到同目录临时文件，经 flush 和 fsync 后用 `os.replace` 原子发布为 0644。发布失败时，`BUILD_MANIFEST_PUBLISH` 指出目标和可用的系统错误原因，CLI 退出 1，`complete` 为 false。独立产物检查单独返回自己的结果。

清单schema_version=1包含本轮结果、包/解释器/jobspec与pin版本、实际库模块摘要、资源层和产物来源。
config_fingerprint.scope=public-generation-options只摘要模式、流程名、脚本模式和组件等公开选项，
不摘要整份原始配置、变量值或凭证。它不代表完整科学配置身份，科学变化通过实际产物和消费者对照审查。
凭证及mode0600额外产物只登记角色/路径/mode，不记录正文或sha256。
reference摘要仅为构建时观察，不冻结运行时内容；陈旧文件不进入本轮结果。

此清单不是Sledra definition manifest，也不是引擎job创建、实际提交、HPC或产品合格证明。
要核对已交付文件、解析定义或隔离展开原生 job，可另行运行[独立产物检查](generation-checks.md)。

## ecFlow machine 引用的路径边界

普通路径仍使用绝对 `%includenopp <...>`。ecFlow 5.12 在替换变量前按空白切分直接 include 路径；有效 machine 目录含空格时，helper 使用 `%includenopp <%TAKFLOW_MACHINE_INCLUDE_DIR%/fragment>`，保存阶段为此添加原始路径的专用原生变量。该名字保留给框架，不作为 Shell 环境导出；MACHINE_DIR 继续采用同一有效目录的 Shell 字面值通道，避免路径中的引号和美元符号被执行。完整与 workflow 分步均建立相同通道。

片段相对名称在 ecFlow 模式不能含空白，否则受控失败；Shell 模式仍按 Shell 规则引用名称。外部 machine 目录仍不在生成主机探测，实际读取由目标预处理/运行端决定。默认片段更新在新建原生 job 时可见，已经创建的 job 不自动更新；Shell 点号加载在原位置保留当前作用域并读取届时内容。

共享 ECF_SCRIPT_CMD 的 cat 文件参数采用 Shell 引用，普通路径的原字节保持，带空格/引号的有效路径经过真实原生预处理验证。

## takler 配置编码

takler 与 Shell 的运行配置不会再经过运行期 Jinja，因此标准 config 阶段将二者编码为 Shell 字面值；需要运行时加载配置的应用（如 MCV）由生成的作业通过 Shell source 读取。ecFlow 仍保留 suite 可 alter 的变量引用。该编码不增加应用名分支，真实消费者的配置通道验证见[开发测试](../develop/testing.md)。

## 额外配置产物与后续阶段

额外模板输出和必需来源由 Application.prepare 固定，声明与选择规则见[资源层、组件与 machine](resource-layers.md)。resource 阶段在复制前验证选定层的 required_inputs；该要求不能由其他层或磁盘旧产物满足。

job/workflow 除主配置外，还要求本轮声明中 required=True 的额外配置产物已经存在且可读。
因此删除必需设置文件后，单步会在 job.input/workflow.input 报错并使旧成功清单失效，
不会仅因主配置还在就继续。optional 输出仍按自身声明处理，单步不发布完整成功清单。

## 同目录启停与失败结果

选用公共资源的应用可在同一输出根重复完整构建。应用只覆盖 head 时，tail 取公共文件。
撤下 head 的源覆盖后，下一次 resource 阶段会把公共 head 写到同一目标，job 阶段将读取
本次输出。若组件使用独立 include 目录，应将公共文件和组件覆盖映射到同一目标，或让
生成的 include 明确引用本次选中的文件。旧目录中其他文件可能仍在，单看清单无法判断
引擎按搜索顺序实际读到的文件。单独运行 job 阶段仍可使用已准备的输出。

完整`build`按本次有效配置登记产物，不将输出目录残留自动纳入成功清单，也不承诺自动清扫关闭项。关闭某个领域功能不一定移除资源层或过滤所有模板；组件分类与任务图仍由应用提供。重新启用时验证当前源输入，旧job/include不能填补缺源。

prepare阶段尚未开始写出，校验、选择器或初始化中断会恢复作用域并保留此前清单。进入修改阶段后，失败清除旧成功清单，BuildError.result只包含本轮已确认部分结果；磁盘仍存在的旧definition不代表本轮成功。修复来源后可复用声明重试，正常完成才原子发布清单。Python保留原异常/BuildError.original，CLI使用受控诊断和既有0/1/2/130退出码；registry恢复不会撤销已写文件。
