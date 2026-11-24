# 资源层、组件与 machine

本页说明静态输入的来源、覆盖、组件筛选、额外输出和 machine 选择。本页所称“资源层”是脚本、模板、include、machine 和其他静态输入的有序来源，不是 `TaskResource` 所描述的节点数、队列和墙钟；后者见[作业资源描述](jobspec.md)。

`Application.prepare()` 根据有效配置选定资源层、组件、额外输出和 machine，并把结果固定在 `BuildContext`。`resource` 阶段只消费这些选择，不重新读取配置或从旧输出猜测来源。应用声明与路径生命周期见[应用上下文](application.md)，实际复制与写出见[标准构建](build.md)。

## 声明静态资源与额外产物

| 声明 | 责任与限制 |
|---|---|
| `ResourceLayer(name, root, config_field=None, required_inputs=())` | base 后按声明顺序覆盖，扩展层在后；名称唯一；配置目录字段的非空值优先于 root，配置相对路径基于 source_dir、canonical overrides 基于调用 cwd；required_inputs 是本层必须提供的相对文件，不能由其他层或旧输出满足；静态与模板共用层序及来源记录 |
| `ResourceEntry(source, destination, executable=False, required=False)` | 声明静态目录/文件映射，路径相对且不逃逸；默认 scripts、ecflow/include、takler/include、utils；迁移映射由应用给出，不新增应用名 profile |
| `use_public_resources` | 默认 False。传 True 或接受有效 config 的布尔函数，可在 base 之前加入随 takflow 安装的公共资源层 |
| `TemplateOutput(template, output, required=True, mode=0o644)` | 声明额外模板产物，mode 仅 0644/0755/0600；标准构建检查实际模板、目标碰撞、编码、权限及写出 |
| `select_components(config)` | 只计算一次，返回 `ComponentSelection`；enabled 与两个路径分类器供资源/作业共用，不读禁用文件 |

## 按有效配置选择可选输入

`Application.resource_layers/outputs` 和 `ApplicationExtension.resource_layers/outputs`
既可以保持固定 tuple，也可以传入 `selector(config) -> tuple`。Application 的
required_machine_fragments 同样接受该形式。每个选择器在一次 prepare 中只调用一次，
读取同一个已验证配置；base 的默认资源 factory 先按需调用一次并解析成有效目录，
因此层选择器能从 config.workflow_repo_base_dir 构造其子目录。现有 config_field
字段仍按表中规则解析，不增加第二次 YAML 加载或领域模型校验。outputs 的选择发生在
context 贡献之前，接收 config；实际渲染时可使用最终合并的领域数据。

资源层按 `base → Application.resource_layers → 各 ApplicationExtension.resource_layers`
的声明顺序选择并解析。每项贡献解析完成后再调用下一项贡献的选择器，因此后续扩展
能从前面 `config_field` 的有效绝对根（包含包默认）派生观测子目录。一个选择器返回的
tuple 内各层随后依次解析；该选择器执行期间不能读取其尚未返回的层的解析结果。
依赖 oper 根的独立观测层应声明在 oper 贡献之后，未启用时返回空 tuple；框架不替应用
推断启用条件。

`config_field` 必须使用规范字段名，历史字符串 alias 由原配置模型校验；Python
canonical overrides 在校验前替换 alias 值。YAML 根相对 YAML 所在目录，mapping/model
根相对 source_dir；相对 canonical override 基于调用 cwd；声明的默认 root 基于调用
cwd。显式 workflow_repo_base 仅替换 base，扩展仍按自己的有效字段或包默认解析。
静态 ResourceEntry、config/job、TemplateOutput 与嵌套 Jinja include 均使用最终层序，
同名项后层覆盖、缺失项向前回落。公共结果中静态文件保留有序 layer/path 来源，渲染
产物的 template 指向选中的源文件；成功清单记录相同的层根，不记录模板正文。

多模式应用可声明 `use_public_resources=lambda config: config.workflow_mode == "ecflow"`。
公共文件包括 `ecflow/include/common/{head,tail}.h`、`takler/include/{head,tail}.sh`
和 `utils/{logger,orvix_functions,run_functions}.sh`。沿用普通
`resource_entries` 和组件筛选选择要复制的文件。允许只映射其中一个文件。
同一相对路径的优先级从低到高依次为 takflow、有效应用基础根、应用后续层、扩展层。
`config.workflow_repo_base_dir` 始终指向有效应用基础根。job 通过工作流输出的 include
目录引用头尾，例如在 `ECF_INCLUDE` 中加入输出的 `ecflow/include` 后使用
`%include <common/head.h>` 和 `%include <common/tail.h>`。

takler 应用启用该资源层后，可将 `TAKLER_INCLUDE` 指向输出的 `takler/include`。
在 job 模板的 Jinja raw 块中写入 `{% include "head.sh" %}` 和 `{% include "tail.sh" %}`，
业务调用放在两个块之间。takler 创建 job 时展开这两处 include。公共 head 在 init 前导出任务名、
本次 attempt UUID 及引擎提供的作业口令，init 的 `--task-id` 使用作业 PID。
应用定制片段仍按同一路径逐文件覆盖。

顺序执行的 Bash runner 从输出目录显式 source 日志、运行及所选的提交辅助。logger 需要 Bash 4+。
`run local` 传递业务脚本退出码。`run orvix` 需要运行机 PATH 上的 `orvix` 和 `python3`，
使用 Python 标准库解析 `orvix status <info.yaml> --format json`。Slurm 和 Donau 确认成功后继续。
local 只报告进程消失时，runner 提示“无法确认业务结果”并以 6 停止。保留直接 Slurm 的应用须先
导入自己的 `submit_and_monitor_slurm_job`。Ksh 头尾和各应用的业务顺序保持独立。

选择结果固定在 BuildPaths.resource_layers、BuildContext.outputs 和
BuildContext.required_machine_fragments；完整与单步构建读取同一结果。
选择器只返回数据，不复制、写出或执行脚本。扩展初始化仍在加载配置前执行，
可选层/产物不构成按配置接管完整阶段或重排业务 Hook 的接口。

选定层的 required_inputs 在 resource 复制前逐项检查来源、类型及可读性。
用它声明必须存在的覆盖文件，可以防止缺少扩展 head 时悄悄落回基础 head；
未选择的层不会被检查。普通稀疏覆盖继续使用不带这些必需项的 ResourceLayer。

## machine 来源与引用

公共配置增加可选顶层 `machine_name/machine_dir`。未使用站点能力的应用无需填写；
`require_machine=True` 时必须显式选择。默认目录为最终输出根下的 `machine/<name>`，
原始 config.machine_dir 保持 None，派生结果在 `MachineContext.directory`。
显式 machine_dir 是所选站点目录本身，必须为绝对目标路径，不复制、不回退、不本地探测。

`MachineContext.external` 区分两种来源；`BuildContext.variables` 合入同一份
`MACHINE_NAME/MACHINE_DIR`，拒绝领域覆盖，检查报告注明远端可见性/执行未验。
实际变量写出、所选站点分发和 include_machine 原生引用 helper 由 [标准构建](build.md)提供，
原生消费者、Shell 加载位置及可更新片段语义见[标准构建](build.md)。

## 业务 Shell 延后加载 machine

`required_machine_fragments=("env/forecast_mpi.sh", ...)` 声明业务脚本将在原位置 source 的片段。资源阶段先检查本轮所选 machine 的有序来源，再复制并登记引用；输出目录中的陈旧文件不能代替缺少的来源。默认目录检查存在性与摘要，显式外部目录仅登记引用，留到目标环境读取。框架不执行或提前 source，不改变业务 cwd/作用域，不自动把片段正文嵌进父作业。片段内容、加载位置和库/MPI 参数继续由消费者维护。

`required_resource_inputs` 为相对文件名元组或接收有效 config 的纯判定函数，用于声明选定业务能力的必需脚本/模板。资源阶段从同一有序来源验证输入，缺失即失败，输出目录里的旧 job 不作替代。未启用相应能力时，判定函数可返回空元组，继续沿用基础资源。

真实消费者的选择、覆盖和初始化验证范围见[开发测试](../develop/testing.md)。
