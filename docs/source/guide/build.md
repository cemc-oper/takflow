# 标准管线、分步生成与成功清单

`takflow.build` 消费 [Application.prepare](application.md) 的同一有效上下文，不重新读取配置。
完整构建和分步调用共享阶段实现；不执行 machine、业务程序、引擎 load 或调度提交。
本页是 TC-06 公开契约，公共 CLI 见[命令契约](cli.md)，TYM 生产入口和旧布局迁移仍由 TC-07 负责。

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
prepare 的加载/校验失败继续使用 TC-02 异常；这时尚未开始写出，不虚构本轮阶段产物。

阶段顺序为 `resource → config → credential → job → workflow → check → report`。
分步调用检查相同前置条件；例如 job 要求运行配置及所选脚本已准备。
每次调用只登记自己的写出，已有前置文件不会因为存在就变成本轮产物。
多个步骤成功也不会自动升级为完整成功，需要显式完整 build 才发布清单。

| 结果字段 | 契约 |
|---|---|
| scope / complete / build_id | full或stage、本轮是否完整成功、本轮调用身份 |
| mode / output_root / workflow_output | 有效模式、绝对输出根、definition或runner位置 |
| stages: list[StageResult] | name/status/reason/skipped_outputs；passed、failed、skipped、not_run |
| artifacts: list[BuildArtifact] | 路径、角色、负责阶段、generated/copied/reference、mode、sha256、来源、mutable/sensitive |
| diagnostics | 保留 TC-03 的code/stage/object/reason/status及 TC-02 的code/path/reason/stage，无原始配置或异常正文 |
| generation | 现有低层 GenerationResult，供薄适配读取output_path/suite，不进入JSON报告 |
| manifest_path | 只有完整成功发布后存在，其他调用为None |

`BuildError` 的公开消息及 `result.as_dict()` 为受控展示；`original` 和 `__cause__` 保留捕获到的同一原异常。
默认日志/CLI 不应打印可能含敏感值的异常正文或 traceback。
标准管线作用域中的公共 Hook 错误日志不含异常正文，旧入口的默认日志行为保持。

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

作业复用目录renderer、include_raw、invoke_script、资源指令helper和TC-03检查，统一jobs/、0755。
标准Environment只渲染最终有效模板，禁用组件不读模板正文；inline先准备脚本，external正确引用路径。
旧renderer不传新增keyword-only参数时保持原布局、空白、来源、权限与返回行为。

流程继续调用takflow.generation.generate_workflow。
definition回调仍为builder → before_save → save → after_save，异常保留原异常与已写文件。
标准definition为0644、shell runner为run_workflow.sh/0755，原生JSON不插注释品牌头。
before_save/after_save为已有保存扩展点，不用整套handler替换默认阶段。

## 变量与machine

框架从输出根提供OUTPUT_REPO_BASE，合并BuildContext.variables的同一有效映射，包含MACHINE_NAME/MACHINE_DIR，实际写出export。
shell配置写Shell字面值；ecFlow/takler配置写原生变量引用，保存前将这个显式导出通道的suite值编码为Shell字面值。
空格、引号、美元符号替换后仍为数据；其他领域变量保持原语义。直接在引擎alter导出通道时，也须提供对应Shell字面值。
标准ecFlow保存作用域使用原生规则保留混合单/双引号，不加入改变变量值的额外反斜杠。
旧入口默认写出保持；公共定义检查同时认识两种兼容写法，标准调用退出作用域后仍可复验。

模板helper `include_machine("env/runtime.sh")` 不内嵌正文、不执行片段。
默认只复制所选machine/<name>，ecFlow生成绝对includenopp，shell/takler生成正确引用的点号加载。
普通Shell与需原生预处理的旧片段仍需消费者分类，要求source语义的业务入口保持原作用域。
显式machine_dir不复制、不本地探测、不回退，记录unchecked reference。
本地片段检查存在性并记录构建时摘要；copied/reference均标mutable，最终观察到更新会报告差异而非强制重生成。
缺失/不可读仍在当前可检查范围内失败。ecFlow后续新建job读取更新，已展开job不自动改变；shell在加载时读取。

## 失败和清单

写出入口在任何阶段输出前使旧generation_manifest.json失效；check/report单步不写产物，不发布成功。
首错停止，负责阶段failed、后续not_run，保留已写文件和原异常；不重试、清空输出根或回滚整个目录。
完整阶段和最终内容/权限检查通过后，写同目录临时清单、flush/fsync，以os.replace原子发布0644清单。
发布失败是report failed，不留下新成功标志，尽力清理临时清单。原子性只覆盖成功标志，整个目录为原位写入。

清单schema_version=1包含本轮结果、包/解释器/jobspec与pin版本、实际库模块摘要、资源层和产物来源。
config_fingerprint.scope=public-generation-options只摘要模式、流程名、脚本模式和组件等公开选项，
不摘要整份原始配置、变量值或凭证。它不代表完整科学配置身份，科学变化通过实际产物和消费者对照审查。
凭证及mode0600额外产物只登记角色/路径/mode，不记录正文或sha256。
reference摘要仅为构建时观察，不冻结运行时内容；陈旧文件不进入本轮结果。

此清单不是Sledra definition manifest，也不是引擎job创建、实际提交、HPC或产品合格证明。
serializer、真实原生解析、动态模板/远端unchecked分别报告，不用skip代替必测能力通过。
