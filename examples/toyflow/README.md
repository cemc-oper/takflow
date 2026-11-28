# toyflow 的低层 API 与独立命令示例

`toyflow` 是一个玩具天气预报系统的工作流生成器，用最小业务主线 `obs → main → post` 演示配置、构图、资源、模板、hook、低层生成服务和可选观测。它是 `mcv-workflow` 的袖珍学习示例，不是科学业务实现。

toyflow 用独立命令演示 TakFlow 0.3.0 的资源、配置、作业、流程和凭证入口。每条命令写出本步产物。标准应用通过 `Application.prepare()` 和 `build(context)` 执行完整生命周期并生成 `generation_manifest.json`。[设计总览](../../docs/source/guide/overview.md) · [0.3.0 迁移说明](../../docs/source/guide/release-0.3.0.md)

## 示例文件与职责

| toyflow 文件 | 应用职责 | 复用的 takflow 能力 |
|---|---|---|
| `config/toyflow.yaml` | 声明通用输入和 toyflow 领域字段 | `BaseWorkflowConfig`、`TaskResource` |
| `src/toyflow/config.py` | 定义 `ForecastConfig` 和 `ToyflowConfig` | `takflow.config` 的模型和配置加载 |
| `src/toyflow/flow.py` | 用 `create_suite(config, engine)` 构建节点、trigger、变量和调度 | `takflow.flow.backend`、`takflow.flow.scheduling`、`takflow.jobs.submission` |
| `src/toyflow/hooks.py` | 定义应用 hook 点并注入 `main/verify`，渲染凭证片段 | `takflow.flow.hook`、`takflow.config.credentials` |
| `src/toyflow/generate.py` | 复制资源、渲染应用配置并保存定义 | `takflow.build.assets`、`takflow.flow.generate`、`takflow.observability` |
| `src/toyflow/cli.py` | 组合独立命令，限定作业渲染的文件头作用域 | `takflow.jobs.render`、`takflow.build_info.build_info_scope`、`takflow.config.credentials` |
| `src/toyflow/resources/` | 提供配置、作业模板、include 和业务脚本 | Jinja 渲染与资源复制 |

toyflow 支持 ecFlow `.def` 和 takler JSON；公共配置模型虽然接受 `shell`，本示例没有 Shell runner，选择该模式会抛出 `ValueError: Unsupported workflow_mode: shell`。

生成的流程结构（ecFlow 模式）：

```text
toyflow/
├── admin/toggles            # 运维开关（defstatus complete）
├── time_triggers/00         # RepeatDate 调度 + 00:00 时间触发
├── obs/prepare              # 观测预处理（serial 作业）
├── main/
│   ├── forecast             # 预报（parallel 作业，trigger: obs/prepare）
│   └── verify               # engine hook 注入的同级任务（trigger: ./forecast）
└── post/plot                # 后处理绘图（serial 作业，trigger: main/forecast）
```

## 运行

要求 Python >= 3.10、TakFlow >= 0.3.0。在 TakFlow 仓库根目录安装框架和示例。

```bash
pip install -e . -e examples/toyflow
```

在 TakFlow 仓库根目录运行下面的命令，输出会写到新目录。

```bash
toyflow_out=$(mktemp -d -t toyflow-XXXXXX)

# 1. 复制静态资源（scripts/、ecflow/include/）
toyflow resource copy --config-file examples/toyflow/config/toyflow.yaml --output-repo-base "$toyflow_out"

# 2. 生成配置文件（ecFlow 模式生成 config/config.h）
toyflow config generate --config-file examples/toyflow/config/toyflow.yaml --output-repo-base "$toyflow_out"

# 3. 从 Jinja2 模板生成作业脚本（jobs/**/*.sh.j2 → *.ecf）
toyflow job generate --config-file examples/toyflow/config/toyflow.yaml --output-repo-base "$toyflow_out"

# 4. 生成工作流定义（toyflow.def）
toyflow workflow generate --config-file examples/toyflow/config/toyflow.yaml --output-repo-base "$toyflow_out"

# 可选：生成凭证文件 config/credential.sh
toyflow credential generate --config-file examples/toyflow/config/toyflow.yaml --credential-file examples/toyflow/config/credential.yaml --output-repo-base "$toyflow_out"
```

如果第三方依赖已经安装，也可以不安装 takflow 和 toyflow。仍在仓库根目录设置两份源码路径，再把上述命令中的 `toyflow` 换成 `python -m toyflow.cli`，参数保持不变：

```bash
export PYTHONPATH="$PWD/examples/toyflow/src:$PWD/src"
```

按上述顺序生成资源、配置、作业和定义。可选凭证命令使用 `takflow.config.credentials.render_credential`，以 `0600` 权限写出 `config/credential.sh`。生成可在本地完成，加载定义、提交作业和运行流程使用各自的运行环境。[标准构建](../../docs/source/guide/build.md)

## 生成的产物

```text
$toyflow_out/
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

可以打开 `toyflow.def` 和 `jobs/main/forecast.ecf`，对照 `flow.py`、YAML 和作业模板检查每一行来自哪里。作业中的 `# JOB` 和 `# BUILD OUTPUT` 分别定位源模板与本步输出，`# INCLUDE [ecflow]` 标记留给 ecFlow 预处理的 include；配置和 include 文件用成对的 `BEGIN include`／`END include` 注释包裹来源片段。这些注释用于人工追踪，不是额外的运行命令。标准构建还在 `generation_manifest.json` 中保存机器可读的产物来源，toyflow 的独立命令不发布该清单。

默认 `external` 模式的作业片段可直接核对：

```text
# JOB toyflow:jobs/main/forecast.sh.j2
# BUILD OUTPUT jobs/main/forecast.ecf
...
# INCLUDE [ecflow] <common/head.h>
%include <common/head.h>
...
"${OUTPUT_REPO_BASE}"/scripts/main/run_forecast.sh
```

切换为 inline 后，实际嵌入的非空业务正文才会出现 `BEGIN script`／`END script` 来源块。

## 可选观测

需要静态定义清单时，安装 `takflow[observability]`，在配置中设置 `observability.enabled: true`、已发布 Sledra 契约的 `spec_dir`、`application_revision` 和 `config_revision`。`workflow generate` 随后生成 `definition_manifest.json`；默认关闭时不生成此文件。完整配置和边界见[可选 Sledra 接入](../../docs/source/guide/observability.md)。

本地真实进程验收示例位于工作区的 `observability/sledra-devel/repo/sledra/examples/generated/`。它复用上述清单导出接口，生成 prepare → forecast → verify 定义与作业，再由独立 launcher 登记 Run、Attempt。toyflow 本身只演示静态生成，不充当运行入口。

## 修改示例与继续阅读

修改 toyflow 时，可按以下顺序定位：

1. 在 `config.py` 和 YAML 中修改领域字段、功能开关与任务资源。
2. 在 `flow.py` 中修改节点树。toyflow 的扩展可在导入时注册 hook。
3. 在 `resources/` 中替换配置、作业模板、include 和业务脚本。
4. 在 `generate.py` 中调整应用保存回调或观测映射，在 `cli.py` 中维护命令入口。

标准 `Application` 的扩展通过 initializer 在每次构建时注册。新应用可参考 MCV S1 的标准声明、资源层及完整构建。[MCV S1 参考](../../docs/source/guide/application.md) · [流程与钩子](../../docs/source/guide/flow-and-hooks.md) · [标准命令契约](../../docs/source/guide/cli.md)
