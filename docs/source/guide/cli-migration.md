# 标准 CLI 迁移与当前配套

标准 CLI 在 TC-12 引入。与 TakFlow 0.3.0 配套的 TYM、MCV base/oper、GFS base/oper 和 RA2 的默认入口均使用公共管线。旧 Python 导入路径的替代位置见 [0.3.0 发布说明](release-0.3.0.md)。

## 调用迁移与有意变化

| 旧 TYM 调用 | TC-12 的临时别名调用 | 当前默认入口 |
| --- | --- | --- |
| 四条命令依次 resource copy/config generate/job generate/workflow generate | cma-tym-v4-workflow standard build | cma-tym-v4-workflow build |
| resource copy | standard resource copy | 同名薄适配至公共 resource |
| config generate | standard config generate | 同名薄适配至公共 config |
| job generate | standard job generate | 同名薄适配至公共 job |
| workflow generate | standard workflow generate | 同名薄适配至公共 workflow |
| 无凭证命令 | standard credential generate（TYM 未启用，skipped） | 同一公共命令 |

所有新调用也可用 `takflow --application cma_tym.application:make_application ...`。根参数 `--format json` 放在 build/阶段组前，通用入口的 --application 同样置于根；`--config-file` 和覆盖参数放在叶命令后。原 --config-file、--output-repo-base、--workflow-repo-base 映射到同名公共参数；原 --output 仅适用于 workflow generate，新增 build 也接受。shell runner 固定为 run_workflow.sh，传 --output 受控失败。旧 workflow handler 忽略 --workflow-repo-base 的缺陷在标准入口中消除。machine 选择使用 --machine-name 和 --machine-dir，post.machine_name 仅限期归一化且冲突报错；model 配置必须显式选择站点。新增 --credential-file 只接受文件路径，不接受凭证内容。

标准输出从旧 ecffiles 迁到 jobs，Shell workflow/run_job.sh 迁到根 run_workflow.sh，config 与 include 的来源、配置 0644/作业 0755/machine 0644 以及 generation_manifest.json 均由公共管线规定。CLI 统一退出码 0/1/2/130 和结构化结果；旧 Path/dict/None 返回与随意打印不属于标准结果。新的 workflow repo 覆盖必须包含相应完整资源；不合并全部旧 oper/include/观测选项为永久公共 schema。

TYM 标准入口直接使用 cma_tym.application 的配置、组件、构图及模板上下文；不调用 resource_copy/config_generate/job_generate/workflow_generate 或它们调用的旧 renderer。当前默认根命令已由公共 create_cli 实现；旧 handler 已削减为共享阶段的 Python 返回适配。util/job/derived/shell runner/run_functions 已使用标准路径，machine 引用经真实原生与 Shell 局部验证；实际部署仍须完成目标站点检查。Shell 的调度与 graph 能力限制见应用 Shell 文档和 YAML 配置说明。此类应用警告在 CLI 中只显示数量。

资源输入另有迁移提示。Slurm workload 的 `wckey` 改为 `project`。ORVIX helper 的 `partition`、`walltime`、`wckey` 分别改为 `queue`、`time`、`project`。标准 CLI 在实际使用旧名的命令上显示 `RESOURCE_ALIAS_DEPRECATED`。这四个输入的移除版本和日期待定。[输入示例和字段映射](jobspec.md)

## 配套依赖

公共库验收的最低环境为 Python 3.10、Pydantic 2.0、Click 8.0。test-suite `0.4.0.dev0` 要求 Python >=3.11。工作区由套件的本地路径和锁选择框架及应用源码，应用使用各仓的 Git 版本。部署使用同批已验收 wheel 和环境锁。

| 包 | 工作区内部依赖 |
|---|---|
| MCV base、TYM、GFS base | `takflow>=0.3.0` |
| MCV oper | `takflow>=0.3.0` 与同批 `mcv-workflow` |
| GFS oper、RA2 | `takflow>=0.3.0` 与同批 `cma-gfs-post-workflow` |

在工作区的 test-suite 目录按套件说明同步本地源码。验证 wheel 时在源码树外运行已安装解释器的 `-I` 模式，调用 `scripts/check_oper_installation.py`。检查覆盖七包安装位置、六应用资源、完整与分步 Python 构建、console/module/通用 CLI 以及 `pip check`。

## 回退

按站点的上一批环境锁恢复配套的 TakFlow、基础应用、oper、配置和资源层。在独立环境与新输出目录使用上一批命令重新生成，然后用同批 `takflow check --integrity` 核对本次清单。现场接入与切换按各应用的部署流程执行。

标准构建只生成和检查文件，不加载引擎、不提交任务、不执行 machine Shell；HPC 部署验证由对应消费者任务完成。

## R1迁移记录（TC-07，2026-11-08）

TC-07 将 TYM 默认根命令切换到 `create_cli`。当时的 `standard` 临时转发、历史参数及返回桥接记录保留在 TYM 的迁移公告中。

当时TYM与suite按R1的takflow>=0.2.0,<0.3和0.2.0.dev0验收，并使用0.2.0+tc07.g<实际HEAD>候选验证。该记录只用于冻结R1复查；当前源码依赖及安装方式以上面的现行配套为准。原始SCM describe/HEAD/diff、旧wheel/lock与历史结果继续保留。


## 冻结的 R2 验收记录

2026-11-11 的 R2 联合验收使用 TC-11.8 的 takflow、TYM、GFS base/oper 和 RA2 wheel，配上 TC-13.6 含后处理模板校验的 MCV base/oper wheel。各 wheel 由对应 sdist 构建。版本、SHA-256、源码修订与候选来源的对应关系见工作区 `framework/doc/R2_PAIRING.json`。

## 用标准入口验证应用

接入时可按 [MCV S1 参考](application.md) 准备 YAML、machine 和输出根，先在新目录执行完整 `build`。Python 路径通过 `Application.prepare` 合并覆盖并校验，再调用 `build` 或显式按序调用 `run_stage`。缺少输入时按阶段诊断检查生效的配置、资源层来源和路径；例如 MCV 开启 `post_data` 后需要对应后处理模板。修复后重跑完整构建并核对 `generation_manifest.json`。返回码 0 表示该次命令成功，1 表示构建失败，2 表示用法错误，130 表示中断。单步成功和残留作业均不足以证明本次完整构建成功。

源机报告里的 unchecked 项随清单交给目标站点。外部 machine 片段可在运行前由站点更新，已创建的原生作业需按引擎语义重新创建才能纳入变动。MPI、真实资料、预报产品、调度器和持续运行恢复按现场方案验收。
