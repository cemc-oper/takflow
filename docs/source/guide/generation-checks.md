# 生成检查与能力预检

`takflow.checks` 为资源、作业、定义和 runner 提供生成端检查。它使用现有配置、模板、公共 Node 树和后端格式，不引入应用注册表或流程 IR。检查完成只说明所列生成条件成立，不代表原生 job 创建、提交或业务程序通过。

## 报告与错误

```python
from takflow.checks import GenerationCheckError, GenerationCheckReport
from takflow.generation import generate_workflow

report = GenerationCheckReport()
try:
    result = generate_workflow(
        config,
        suite_builder=create_suite,
        check_report=report,
    )
except GenerationCheckError as error:
    print(error.diagnostic.code, error.diagnostic.stage, error.diagnostic.object)
    print(error.report.as_dict())
else:
    print(result.output_path)
    print(report.as_dict())
```

每项检查含 `code/stage/object/reason/status`，status 为 `passed`、`unchecked` 或 `failed`。`GenerationCheckError` 继承 ValueError；缺必需输入的 `GenerationInputError` 同时继承 FileNotFoundError。诊断使用受控原因，不复制整份配置、模板正文、Shell stderr 或原生解析异常消息。

`artifacts` 仅登记本次显式写出或显式交给后检的文件，含 path/role/mode/SHA-256。后层覆盖同一路径会更新该记录。坏产物也可能已写出并登记，必须结合 failed 检查和抛出的异常判断；报告不是完整构建成功清单，不扫描旧目录认领陈旧文件，也不写 `generation_manifest.json`。

`render_jobs_from_directory`、`render_single_job_file`、`copy_resources_to_output` 新增可选 keyword-only `check_report` 收集器，原返回 None 不变。`generate_workflow` 的 GenerationResult/GenerationContext 字段保持，额外接受 `required_operations` 和收集器。未提供收集器也执行检查，检查失败的异常携带报告；builder/save/保存回调的原异常继续原样传播，可由显式收集器查看失败阶段。

## 分阶段责任

| 阶段 | 检查时可用信息和动作 | 结果的限度 |
|---|---|---|
| `generation.preflight` | 模式、脚本模式、workload/carrier/scheduler、消费者声明支持模式及所需后端操作 | 不按应用名推测业务能力，不探测远端程序/调度器 |
| `resource.preflight` | 显式源根、4个选中可选子树、源/目标类型、读写权限、路径/链接、实际复制集合和递归/物理碰撞 | 缺可选子树记录未选择/不存在，动态正文引用不解释 |
| `resource.copy` / `resource.check` | 记录实际完成的 copy2 文件，核对本轮内容与原权限合同 | 保留 copytree 行为；既有陈旧 `.sh` 可被原 helper 补执行位，但不因此计为本轮产物 |
| 配置 | TC-02 负责加载/覆盖/模型诊断；现有应用 renderer 拥有配置模板、领域上下文和必需/可选语义 | 本任务不伪造公共 config 阶段；需要检查显式文件时复用 check_input_file/check_output_path |
| `job.preflight` | 先应用组件/pilot过滤，收集输出名，检查 Jinja 模板及无条件静态依赖、本地 literal helper 引用、执行位、逃逸、输出冲突及输入覆盖 | 不把禁用组件资源变必需，不符号执行 Jinja 条件/宏 |
| `job.render` / `job.output` | 实际执行到的内建脚本 helper 再检查解析出的本地引用；写出/chmod后做适用的语法检查和本轮登记 | 动态引用可能晚失败，已写文件保留；runtime模板须待原生 job 创建 |
| `definition.preflight` | 输出路径、builder返回的公共树、名称、父子、engine、兄弟重名；保存前回调后重新核对树 | 检查树形容器，不把 trigger/complete/repeat 等调度表达式强套普通 DAG |
| `definition.output` | ecFlow 现有 serializer 对照、可用时原生 Defs 解析；takler 实际 parse/build并与权威导出语义对照 | serializer 与 native 分别记录；不创建 task job 或提交 |
| `workflow.preflight` / `workflow.output` | 已知 runner模板/目标检查，实际 runner 的权限/语法/登记 | 通用 shell callback 返回 None 时只能报告输出路径未知，不猜目录中哪个文件属于本轮 |

## 支持声明与后端矩阵

`preflight_generation(config, supported_modes=(...), required_operations=(...), check_report=...)` 接受消费者掌握的事实。例如固定 ecFlow 的入口应声明 `supported_modes=("ecflow",)`；不能因 BaseWorkflowConfig 的 Literal 含 takler/shell 就宣称应用已实现这些分发。

`required_operations` 使用现有 WorkflowBackend 方法名，如 `add_label`。`WorkflowBackend.unsupported_operations` 与 TaklerBackend 的同名集合反映[后端矩阵](backends.md)中的明确限制；takler 的 add_label/add_late/add_repeat_day 会在声明时提前拒绝，原方法仍按原契约抛 NotImplementedError。没有领域声明的其他复杂需求仍由原构图/引擎检查，不为了预检重写领域图。

共享组合检查区分 shell 顺序模式与 ecFlow/takler 后端，校验 workload 的实际 carrier；slsubmit6/sbatch 仅用于 slurm，不能与 donau scheduler 混用。takler 的 slsubmit6 分支仍是原有 sbatch/scancel，保留与 ecFlow slsubmit6/slcancel4 的语义差异；预检不将二者判为运行等价。应用自己的开关规则和 warning 保留，例如 TYM shell 忽略 graph/scheduling 而仍借 cycles 形成时长表。

## 引用、模板和路径

`check_relative_path` 拒绝空相对路径、绝对路径、`..`、控制字符和输出 symlink 逃逸。显式 definition output 仍可指向输出根之外，保持原公共 API 的显式路径语义；缺省名称和 job/resource 的相对输出需保持在各自根内。`check_input_file` 检查本地普通文件可读性，只对直接调用脚本要求执行位；include/source 片段无需执行位。`check_output_path` 不创建目录，检查已有目标/父目录类型及可判定权限。

作业模板先按 template_filter 选择。每层使用原有 loader 优先级，合法同名后层覆盖保留；不同模板如 foo.j2 和 foo.sh.j2 映射同一产物则失败。稀疏层没有 jobs 时仍可作为更前层模板来源，索引不会因跳过 jobs 目录而错位。

Jinja 的无条件静态 include/extends/import、候选 include 和 ignore missing 按原语义处理。条件、循环、宏及可覆盖 block 中的引用不被强制变成必需资源，记录为 unchecked，在实际被选择执行时检查；不运行一套新的条件解释器。raw 块和引擎第二遍模板不二次解释。动态模板名、自定义同名 helper、含运行变量/远端标记的路径有独立 unchecked 项，不能把“没有查”表述为“引用有效”。

目录渲染器持有自己的 FileSystemLoader，实际选择条件或动态模板时会在读取前再次核对本地边界和权限。单文件入口可接受调用者自己的 Environment/loader；它保留该 loader 的查找语义，不能宣称已经分析自定义 loader 的所有引用或实施相同的目录边界约束。

内建 include_raw/invoke_script 的本地 literal 输入来自已准备输出树，inline 在 job 生成时读取；external 直接调用需可执行。执行到 helper 时仍做实际引用检查。已知模板/读取脚本与计划输出不能是同一路径、symlink/hardlink别名或发生破坏性覆盖。未读到的远端文件和业务 Shell 内任意 source/module/程序命令没有被全面解析。

## 后检与未检查项

ecFlow 后检比较当前 serializer 的定义正文，允许外层完整注释行及边界空行作为品牌装饰；这是 serializer 对照，不是第二套原生解析器。原生 ecflow Python 包可用时才调用真实 Defs 解析，缺少时记录 GEN_NATIVE_ECFLOW_UNAVAILABLE。trigger、include、变量替换和原生 job 创建仍需对应工具/环境验收。

takler 使用实际 parse_definition/build_definition 校验保存内容，并对照原 suite 的 export_definition，防止只保留根名却丢失任务的文件被认可；运行期 Jinja 和任务提交仍是后续阶段。

具体 Shell 脚本有可用的已声明解释器时执行 `-n`，使用不含 BASH_ENV/ENV/导出函数的受控环境，不运行业务命令。`.ecf` 和含运行期 Jinja 的脚本记录 GEN_RUNTIME_TEMPLATE_UNCHECKED。解释器缺失、当前 ksh 实际指向不能验证目标 Ksh93 的 mksh/lksh、以及未支持的 shebang 选项分别记录 unchecked；不把 mksh当Ksh93，也不丢掉 `-O extglob` 等选项后误判，更不转发可执行启动代码的任意选项。相应原生语法责任仍保留。

所有输出原位写入，动态渲染、copy、语法或保存后检查仍可能在部分文件写出后失败。报告保留已知文件，不自动回滚、重试或清空输出。保存/回调原异常不能被失败证据收集覆盖。已有成功 manifest 的失效和完整成功标志发布属于 TC-06 生命周期；本检查不更新它，也不凭它表示本轮通过。

MCV/GFS 的薄适配仍沿用原 save/write 路径，未保证把每种底层 I/O 异常都补成共享 generation 服务那样的 failed/partial 记录。原异常及已写文件仍是判断本轮结果的一部分；collector 不完整或没有 failed 项不能单独作为成功证明。
