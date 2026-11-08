# 标准 CLI 迁移公告（TC-12，2026-11-08）

面向应用维护者和部署者。本公告先于 R1 发布；所列版本是待验收后的发布目标，未创建 tag。当前 TC-12 候选 SCM 版本和实际安装结果记录在阶段 1 的 tc12/REPORT.md。TYM 显式标准入口已可用于生成验收；TC-07 完成领域路径闭合、默认入口切换及七用例脚本迁移后才具备 R1 发布条件。

## 调用迁移与有意变化

| 当前 TYM 调用 | 显式新调用（候选窗口） | 默认入口切换后 |
| --- | --- | --- |
| 四条命令依次 resource copy/config generate/job generate/workflow generate | cma-tym-v4-workflow standard build | cma-tym-v4-workflow build |
| resource copy | standard resource copy | 同名薄适配至公共 resource |
| config generate | standard config generate | 同名薄适配至公共 config |
| job generate | standard job generate | 同名薄适配至公共 job |
| workflow generate | standard workflow generate | 同名薄适配至公共 workflow |
| 无凭证命令 | standard credential generate（TYM 未启用，skipped） | 同一公共命令 |

所有新调用也可用 `takflow --application cma_tym.application:make_application ...`。根参数 `--format json` 放在 build/阶段组前，通用入口的 --application 同样置于根；`--config-file` 和覆盖参数放在叶命令后。原 --config-file、--output-repo-base、--workflow-repo-base 映射到同名公共参数；原 --output 仅适用于 workflow generate，新增 build 也接受。shell runner 固定为 run_workflow.sh，传 --output 受控失败。旧 workflow handler 忽略 --workflow-repo-base 的缺陷在标准入口中消除。machine 选择使用 --machine-name 和 --machine-dir，post.machine_name 仅限期归一化且冲突报错；model 配置必须显式选择站点。新增 --credential-file 只接受文件路径，不接受凭证内容。

标准输出从旧 ecffiles 迁到 jobs，Shell workflow/run_job.sh 迁到根 run_workflow.sh，config 与 include 的来源、配置 0644/作业 0755/machine 0644 以及 generation_manifest.json 均由公共管线规定。CLI 统一退出码 0/1/2/130 和结构化结果；旧 Path/dict/None 返回与随意打印不属于标准结果。新的 workflow repo 覆盖必须包含相应完整资源；不合并全部旧 oper/include/观测选项为永久公共 schema。

TYM 标准入口直接使用 cma_tym.application 的配置、组件、构图及模板上下文；不调用 resource_copy/config_generate/job_generate/workflow_generate 或它们调用的旧 renderer。当前四个旧根 handler 仍供冻结兼容入口使用；它们的删除、旧 Python 返回桥接、util/job/derived/shell runner/run_functions 中的 ecffiles 引用消除由 TC-07 实施并登记。候选生成成功不能说明这些旧引用已经闭合，不能将生成产物直接用于生产提交。Shell 原有调度与 graph 能力限制保持，CLI 只显示警告数量，具体限制见应用 Shell 文档和 YAML 配置说明。

## 最低版本与弃用/移除窗口

标准 CLI 最低正式框架版本为 **takflow 0.2.0，Python 3.10**。正式版本发布前使用同次验收的 takflow/TYM wheel 候选（来源 SHA 与 wheel 摘要配对），不要单独升级一个包。当前 TYM 声明仍保留 takflow>=0.1.1 以支持冻结旧入口，不能据此假定具备标准 CLI；不带 TC-12 的框架只能使用旧入口。TC-07 发布配套时更新依赖与 lock 至下表窗口，不手改 _version.py 或写入尚不可安装的版本。

| 仓库 | 首次弃用旧外围/命令的目标版本 | 保留/移除目标 | 标准框架配套 |
| --- | --- | --- | --- |
| takflow | 0.2.0（R1） | 0.3.0 保留公告桥接；0.4.0 移除 | 框架自身 |
| TYM | 0.2.0（R1，TC-07 完成后） | 0.3.0 保留桥接；0.4.0 移除 | R1 >=0.2.0,<0.3；R2 >=0.3.0,<0.4；R3 >=0.4.0,<0.5 |
| MCV base/oper | 2026.4.0（R2） | 2026.5.0 移除 | R2 >=0.3.0,<0.4；R3 >=0.4.0,<0.5；oper 配同版本 base |
| GFS POST base/oper | 0.2.0（R2） | 0.3.0 移除 | 同上框架窗口；oper 配同版本 base |
| RA2 oper | 0.2.0（R2，先补实际证据） | 0.3.0 移除 | 同上框架窗口；配同版本 GFS base |
| takflow-test-suite | 0.2.0（R1）/0.3.0（R2） | 0.4.0 退出旧调用测试，保留历史报告 | 发布 lock 与上述仓库 SHA 配套 |

这些是具体发布目标，不是已经发生的软件发布或已在所有消费者生效的弃用。MCV/GFS/RA2 的命令迁移随各自 R2 接入验收，TC-12 不创建不可用的替代命令；各仓库必须在实际发布说明中重复窗口并给出本应用有效选项，不得只引用 R1/R3 名称。TC-12 公布共用接口和逐仓库期限；各仓库维护者负责实际弃用告警、锁定依赖与后续移除。变更期限须同步阶段计划和调整记录。

## 回退

候选期可继续使用未切换的旧根命令，但使用独立输出目录，禁止将新旧布局混用。正式发布后保留已验收的旧 wheel/lock 和配置快照；用独立环境重新安装该配套（`uv venv /path/to/rollback-env`，`uv pip install --python /path/to/rollback-env/bin/python /path/to/saved/takflow.whl /path/to/saved/cma_tym_v4_workflow.whl`，实际文件名取发布档案），然后依旧 resource→config→job→workflow 顺序在新的输出目录重建。不要回滚运行中目录或拿旧成功清单证明新构建完成。当前历史基线来源为 takflow dd58e41274322beacc410440dc19e64f97c9da2b 与 TYM 7ef1b263943a71f4fb6b4a761bd384dfff0d8068；版本/依赖与回退档案随发布重新核对。

标准构建只生成和检查文件，不加载引擎、不提交任务、不执行 machine Shell；HPC 部署验证由对应消费者任务完成。
