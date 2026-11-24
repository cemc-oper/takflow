# toyflow —— takflow 底层 API 与旧 CLI 示例

`toyflow` 是一个玩具天气预报系统的工作流生成器，用最小业务主线 `obs → main → post` 演示配置、构图、资源、模板、hook、低层生成服务和可选观测。它是 `mcv-workflow` 的袖珍学习示例，不是科学业务实现。

**toyflow 使用应用自有四步 CLI 和旧 toolkit 适配入口，没有声明标准 `Application`，也不发布 `generation_manifest.json`。** 新应用应以 `Application.prepare()` 和 `build(context)` 组织构建，见[设计总览](../../docs/source/guide/overview.md)、[应用声明](../../docs/source/guide/application.md)和[标准构建](../../docs/source/guide/build.md)。本 README 负责说明 toyflow 的文件、命令和产物；各 API 的完整契约以对应专题页为准。

## 示例文件与职责

| toyflow 文件 | 应用职责 | 复用的 takflow 能力 |
|---|---|---|
| `config/toyflow.yaml` | 声明通用输入和 toyflow 领域字段 | `BaseWorkflowConfig`、`TaskResource` |
| `src/toyflow/config.py` | 定义 `ForecastConfig` 和 `ToyflowConfig` | 配置模型与旧 loader |
| `src/toyflow/flow.py` | 用 `create_suite(config, engine)` 构建节点、trigger、变量和调度 | `takflow.flow`、后端 runtime helpers |
| `src/toyflow/hooks.py` | 定义应用 hook 点并注入 `main/verify`；渲染 toyflow 凭证片段 | 通用 registry 与 credential hook |
| `src/toyflow/generate.py` | 适配配置渲染、definition 保存和可选观测清单 | `takflow.generation`、observability toolkit |
| `src/toyflow/cli.py` | 组合应用自有的 resource/config/job/workflow/credential 命令 | 旧 toolkit 生成入口 |
| `src/toyflow/resources/` | 提供配置、作业模板、include 和业务脚本 | Jinja 渲染与资源复制 |

toyflow 支持 ecFlow `.def` 和 takler JSON；公共配置模型虽然接受 `shell`，本示例没有 Shell runner，选择该模式会抛出 `ValueError: Unsupported workflow_mode: shell`。

生成的流程结构（ecFlow 模式）：

```text
toyflow/
├── admin/toggles            # 运维开关（defstatus complete）
├── time_triggers/00         # RepeatDate 调度 + 00:00 时间触发
├── obs/prepare              # 观测预处理（serial 作业）
├── main/forecast            # 预报（parallel 作业，trigger: obs/prepare）
│   └── verify               # 由 engine hook 注入的扩展任务
└── post/plot                # 后处理绘图（serial 作业，trigger: main/forecast）
```

## 运行

要求 Python >= 3.10。先安装 takflow 和本示例：

```bash
cd framework/takflow
pip install -e .
pip install -e examples/toyflow
```

在 takflow 仓库根目录依次执行：

```bash
# 1. 复制静态资源（scripts/、ecflow/include/）
toyflow resource copy --config-file examples/toyflow/config/toyflow.yaml --output-repo-base /tmp/toyflow_output

# 2. 生成配置文件（ecFlow 模式生成 config/config.h）
toyflow config generate --config-file examples/toyflow/config/toyflow.yaml --output-repo-base /tmp/toyflow_output

# 3. 从 Jinja2 模板生成作业脚本（jobs/**/*.sh.j2 → *.ecf）
toyflow job generate --config-file examples/toyflow/config/toyflow.yaml --output-repo-base /tmp/toyflow_output

# 4. 生成工作流定义（toyflow.def）
toyflow workflow generate --config-file examples/toyflow/config/toyflow.yaml --output-repo-base /tmp/toyflow_output

# 可选：生成凭证文件 config/credential.sh
toyflow credential generate --config-file examples/toyflow/config/toyflow.yaml --credential-file examples/toyflow/config/credential.yaml --output-repo-base /tmp/toyflow_output
```

如果第三方依赖已经安装，也可以不安装 takflow 和 toyflow。仍在仓库根目录设置两份源码路径，再把上述命令中的 `toyflow` 换成 `python -m toyflow.cli`，参数保持不变：

```bash
export PYTHONPATH="$PWD/examples/toyflow/src:$PWD/src"
```

这些命令是 toyflow 的旧应用入口：不会自动补跑前置步骤，也不发布标准成功清单。可选 credential 命令沿用旧 `render_credential` 的权限和返回行为；标准构建的凭证阶段使用 `0600`，见[标准构建](../../docs/source/guide/build.md)。整个生成过程是纯本地渲染，不需要 ecFlow、Slurm 或 HPC；只有加载、提交和运行生成物才需要相应环境。

## 生成的产物

```text
/tmp/toyflow_output/
├── toyflow.def              # ecFlow 定义文件（含提交方式变量）
├── config/
│   ├── config.h             # 作业运行时加载的配置
│   └── credential.sh        # 可选：credential hook 渲染
├── jobs/
│   ├── obs/prepare.ecf      # 作业脚本（含 #ORVIX 资源指令）
│   ├── main/forecast.ecf
│   ├── main/verify.ecf
│   └── post/plot.ecf
├── scripts/                 # 静态业务脚本
└── ecflow/include/common/   # head.h / configure.h / tail.h
```

可以打开 `toyflow.def` 和 `jobs/main/forecast.ecf`，对照 `flow.py`、YAML 和作业模板检查每一行来自哪里。

## 可选观测

需要静态定义清单时，安装 `takflow[observability]`，在配置中设置 `observability.enabled: true`、已发布 Sledra 契约的 `spec_dir`、`application_revision` 和 `config_revision`。`workflow generate` 随后生成 `definition_manifest.json`；默认关闭时不生成此文件。完整配置和边界见[可选 Sledra 接入](../../docs/source/guide/observability.md)。

本地真实进程验收示例位于工作区的 `observability/sledra-devel/repo/sledra/examples/generated/`。它复用上述清单导出接口，生成 prepare → forecast → verify 定义与作业，再由独立 launcher 登记 Run、Attempt。toyflow 本身只演示静态生成，不充当运行入口。

## 修改示例与继续阅读

修改 toyflow 时，可按以下顺序定位：

1. 在 `config.py` 和 YAML 中修改领域字段、功能开关与任务资源。
2. 在 `flow.py` 中修改节点树；toyflow 旧 CLI 的扩展包可在 import 时注册 hook。
3. 在 `resources/` 中替换配置、作业模板、include 和业务脚本。
4. 在 `generate.py` 中调整应用保存回调或观测映射；只有维护旧入口时才修改 `cli.py`。

标准 `Application` 不依赖 import-only 注册，扩展必须在 initializer 中逐轮注册，见[流程与钩子](../../docs/source/guide/flow-and-hooks.md)。新应用不要复制这套旧 CLI 来建立第二套构建生命周期；标准声明、资源层、阶段结果和公共命令分别见[应用声明](../../docs/source/guide/application.md)、[资源层](../../docs/source/guide/resource-layers.md)、[标准构建](../../docs/source/guide/build.md)和[标准命令契约](../../docs/source/guide/cli.md)。真实业务包的标准应用示例见[应用声明中的 MCV S1 参考](../../docs/source/guide/application.md)。
