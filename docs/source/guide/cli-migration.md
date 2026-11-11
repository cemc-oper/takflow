# 标准 CLI 迁移与当前配套

面向应用维护者和部署者。标准CLI在TC-12引入，TYM、MCV base/oper、GFS base/oper及RA2的默认入口现均委托公共管线。当前R2使用已验源码修订和明确未发布的配套候选；实际发布由维护者办理，不能把local candidate或SCM安装metadata当作正式tag或当前源码身份。

## 调用迁移与有意变化

| 当前 TYM 调用 | TC-12 的临时别名调用 | 当前默认入口 |
| --- | --- | --- |
| 四条命令依次 resource copy/config generate/job generate/workflow generate | cma-tym-v4-workflow standard build | cma-tym-v4-workflow build |
| resource copy | standard resource copy | 同名薄适配至公共 resource |
| config generate | standard config generate | 同名薄适配至公共 config |
| job generate | standard job generate | 同名薄适配至公共 job |
| workflow generate | standard workflow generate | 同名薄适配至公共 workflow |
| 无凭证命令 | standard credential generate（TYM 未启用，skipped） | 同一公共命令 |

所有新调用也可用 `takflow --application cma_tym.application:make_application ...`。根参数 `--format json` 放在 build/阶段组前，通用入口的 --application 同样置于根；`--config-file` 和覆盖参数放在叶命令后。原 --config-file、--output-repo-base、--workflow-repo-base 映射到同名公共参数；原 --output 仅适用于 workflow generate，新增 build 也接受。shell runner 固定为 run_workflow.sh，传 --output 受控失败。旧 workflow handler 忽略 --workflow-repo-base 的缺陷在标准入口中消除。machine 选择使用 --machine-name 和 --machine-dir，post.machine_name 仅限期归一化且冲突报错；model 配置必须显式选择站点。新增 --credential-file 只接受文件路径，不接受凭证内容。

标准输出从旧 ecffiles 迁到 jobs，Shell workflow/run_job.sh 迁到根 run_workflow.sh，config 与 include 的来源、配置 0644/作业 0755/machine 0644 以及 generation_manifest.json 均由公共管线规定。CLI 统一退出码 0/1/2/130 和结构化结果；旧 Path/dict/None 返回与随意打印不属于标准结果。新的 workflow repo 覆盖必须包含相应完整资源；不合并全部旧 oper/include/观测选项为永久公共 schema。

TYM 标准入口直接使用 cma_tym.application 的配置、组件、构图及模板上下文；不调用 resource_copy/config_generate/job_generate/workflow_generate 或它们调用的旧 renderer。当前默认根命令已由公共 create_cli 实现；旧 handler 已削减为共享阶段的 Python 返回适配。util/job/derived/shell runner/run_functions 已使用标准路径，machine 引用经真实原生与 Shell 局部验证；实际部署仍须完成目标站点检查。Shell 原有调度与 graph 能力限制保持，CLI 只显示警告数量，具体限制见应用 Shell 文档和 YAML 配置说明。

## 最低版本与弃用/移除窗口

标准CLI在R1以takflow 0.2.0为发布目标引入，公共库最低Python3.10。当前test-suite自身要求Python>=3.11；它的版本0.3.0.dev0不代表框架或各应用已正式发布。当前R2取消了尚未发布的依赖下限，实际元数据如下；宽松范围不证明任意旧版兼容，部署仍须使用同次验收的修订/wheel/lock配套，不用--no-deps掩盖冲突或手改_version.py。

| 包 | 当前源码依赖声明 |
|---|---|
| MCV base | takflow不限制版本 |
| MCV oper | takflow<0.4；mcv-workflow不限制版本 |
| TYM / GFS base | takflow<0.4 |
| GFS oper / RA2 | takflow<0.4；cma-gfs-post-workflow<0.3 |

旧验收中出现的>=0.2.0或>=0.3.0属于当时候选配套，不应恢复为当前安装门槛。现行依赖放宽不改变以下首弃用和移除目标：

| 仓库 | 首次弃用旧外围/命令的目标版本 | 保留/移除目标 | 标准框架配套 |
| --- | --- | --- | --- |
| takflow | 0.2.0（R1） | 0.3.0 保留公告桥接；0.4.0 移除 | 框架自身 |
| TYM | 0.2.0（R1） | 0.3.0 保留桥接；0.4.0 移除 | 当前R2按上表及已验修订配套 |
| MCV base/oper | 2026.4.0（R2） | 2026.5.0 移除 | 当前R2按上表及已验base/oper配套 |
| GFS POST base/oper | 0.2.0（R2） | 0.3.0 移除 | 当前R2按上表及已验base/oper配套 |
| RA2 oper | 0.2.0（R2） | 0.3.0 移除 | 当前R2按上表及已验GFS base配套 |
| takflow-test-suite | 0.2.0（R1）/0.3.0（R2） | 0.4.0 退出旧调用测试，保留历史报告 | 发布 lock 与上述仓库 SHA 配套 |

这些是具体发布目标，不是已经发生的软件发布或已在所有消费者生效的弃用。MCV/GFS/RA2 的命令迁移随各自 R2 接入验收，TC-12 不创建不可用的替代命令；各仓库必须在实际发布说明中重复窗口并给出本应用有效选项，不得只引用 R1/R3 名称。TC-12 公布共用接口和逐仓库期限；各仓库维护者负责实际弃用告警、锁定依赖与后续移除。变更期限须同步阶段计划和调整记录。

## 回退

当前旧根命令名已委托标准实现；需要旧布局时必须回到冻结的旧配套，并使用独立输出目录。正式发布后保留已验收的旧 wheel/lock 和配置快照；用独立环境重新安装该配套（`uv venv /path/to/rollback-env`，`uv pip install --python /path/to/rollback-env/bin/python /path/to/saved/takflow.whl /path/to/saved/cma_tym_v4_workflow.whl`，实际文件名取发布档案），然后依旧 resource→config→job→workflow 顺序在新的输出目录重建。不要回滚运行中目录或拿旧成功清单证明新构建完成。当前历史基线来源为 takflow dd58e41274322beacc410440dc19e64f97c9da2b 与 TYM 7ef1b263943a71f4fb6b4a761bd384dfff0d8068；版本/依赖与回退档案随发布重新核对。

标准构建只生成和检查文件，不加载引擎、不提交任务、不执行 machine Shell；HPC 部署验证由对应消费者任务完成。

## R1迁移记录（TC-07，2026-11-08）

TYM 默认根入口现已切换为 create_cli；standard 仅作为 0.4.0 前的临时转发别名，旧五套外围实现已由共享管线替代。当前使用顶层 machine_name，post.machine_name 的限期归一化、Python Path/None 返回桥接和版本窗口见 TYM docs/standard-cli.md。此前“默认入口尚待 TC-07”的说明属于 TC-12 交付时点；当前入口和候选配套以此节和 TYM 公告为准。

当时TYM与suite按R1的takflow>=0.2.0,<0.3和0.2.0.dev0验收，并使用0.2.0+tc07.g<实际HEAD>候选验证。该记录只用于冻结R1复查；当前源码依赖及安装方式以上面的现行配套为准。原始SCM describe/HEAD/diff、旧wheel/lock与历史结果继续保留。


## 当前R2源码与安装方式

各应用的有效选项、限期旧Python返回适配和冻结回退见所属项目docs/standard-cli.md及installation说明。工作区用test-suite的scripts/r2_candidates.py在独立环境执行locked sync；候选目标为takflow/TYM 0.3.0、MCV base/oper 2026.4.0、GFS base/oper/RA2 0.2.0，并记录实际HEAD/dirty摘要。

分发验收从每个当前sdist在新目录构建wheel，正常解析全部配套依赖后，在源码树外使用安装解释器的-I模式运行test-suite/scripts/check_oper_installation.py，核对七包site-packages来源、六应用默认资源/完整/分步/console/module/通用CLI与旧适配告警，并执行pip check。wheel检查不能只安装框架或用源码PYTHONPATH替代安装。MCV特殊字符凭证编码、可选观测范围和关闭/失败语义以现行应用公告及Application/build指南为准；现场运行与正式发布另行验收。
