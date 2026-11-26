# 快速上手：toyflow

本页用最小应用 [toyflow](https://github.com/cemc-oper/takflow/tree/main/examples/toyflow) 走通配置、领域构图、hook、低层生成服务和应用自有四步 CLI，最终生成 ecFlow `.def`。业务主线只有 `obs → main → post`，便于对照源码理解各领域内容如何进入生成物。

toyflow 使用 TakFlow 0.3.0 接口演示独立生成命令。标准应用使用 `Application.prepare()` 和 `build(context)` 生成全套产物和成功清单。[设计总览](guide/overview.md) · [0.3.0 发布说明](guide/release-0.3.0.md)

完整业务包的标准应用示例见 {ref}`MCV S1 真实应用参考 <mcv-s1-reference>`。

## 安装

要求 Python >= 3.10。只使用框架库时可安装发布包：

```bash
pip install takflow
```

本页的端到端命令使用仓库内独立的 toyflow 包。从源码安装框架和该示例：

```bash
git clone https://github.com/cemc-oper/takflow.git
# 在 CMA 内网可使用 metcode:
# git clone http://e.mc.met.cma/codingcorp/cemc-takler/takflow.git
cd takflow
pip install .
pip install -e examples/toyflow
```

以下命令均在仓库根目录执行。不安装两个源码包的等价运行方式见 [toyflow README](https://github.com/cemc-oper/takflow/tree/main/examples/toyflow)。

## 端到端流程

### 1. 加载领域配置

`toyflow.config.ToyflowConfig` 子类化 `BaseWorkflowConfig`，只增加功能开关、预报配置和任务资源等领域字段；目录、模式、workload 和调度等通用字段由框架提供。

```python
from toyflow.config import ToyflowConfig, load_config_from_file

config = load_config_from_file(
    "examples/toyflow/config/toyflow.yaml",
    config_class=ToyflowConfig,
)
print(config.forecast.resource)
```

toyflow 通过公共配置加载器读取 YAML。标准应用把配置类型交给 `Application`，由 `prepare()` 统一加载、覆盖和校验。[配置](guide/config.md)

### 2. 定义运行流程

toyflow 的 suite builder 接收有效配置和后端无关的 `WorkflowEngine`，返回根 `Node`。其核心入口可概括为：

```python
from toyflow.flow import ToyflowSystem


def create_suite(config, engine):
    return ToyflowSystem(config, engine).build_suite()
```

`ToyflowSystem` 负责节点、依赖、调度和领域 hook；`set_runtime()` 负责提交载体，`render_orvix_resource_block()` 负责作业资源指令。完整构图和 hook 示例见[流程与钩子](guide/flow-and-hooks.md)，后端可移植范围见[后端能力矩阵](guide/backends.md)。

### 3. 通过低层生成服务保存定义

toyflow 自己的 `generate_workflow()` 是薄适配入口：通用模式分发、输出路径和保存编排委托 `takflow.flow.generate`，应用保留 suite builder 与可选观测清单的保存回调。

```python
from toyflow.generate import generate_workflow

output_path = generate_workflow(
    config,
    output_repo_base="/tmp/toyflow_output",
)
```

toyflow 支持 ecFlow `.def` 和 takler JSON，不支持 Shell runner。低层接口见[生成服务 API](reference/generation.rst)；标准应用的 workflow 阶段也复用这套编排，但由同一 `BuildContext` 提供输入，不需要应用再次加载配置。

### 4. 运行 toyflow 的四步 CLI

```bash
toyflow resource copy --config-file examples/toyflow/config/toyflow.yaml --output-repo-base /tmp/toyflow_output
toyflow config generate --config-file examples/toyflow/config/toyflow.yaml --output-repo-base /tmp/toyflow_output
toyflow job generate --config-file examples/toyflow/config/toyflow.yaml --output-repo-base /tmp/toyflow_output
toyflow workflow generate --config-file examples/toyflow/config/toyflow.yaml --output-repo-base /tmp/toyflow_output
```

toyflow 的独立命令使用 `takflow.build.assets`、`takflow.jobs.render`、`takflow.flow.generate` 和 `takflow.config.credentials`。按上面的顺序调用资源、配置、作业和流程命令。标准应用的完整构建、分步命令、结果和退出码参见标准命令契约。[标准命令契约](guide/cli.md)

## 生成的流程结构

toyflow 在 ecFlow 模式下生成的节点树：

```text
toyflow/
├── admin/toggles            # 运维开关（defstatus complete）
├── time_triggers/00         # RepeatDate 调度 + 00:00 时间触发
├── obs/prepare              # 观测预处理（serial 作业）
├── main/forecast            # 预报（parallel 作业，trigger: obs/prepare）
│   └── verify               # 由 engine hook 注入的扩展任务
└── post/plot                # 后处理绘图（serial 作业，trigger: main/forecast）
```

打开 `/tmp/toyflow_output/toyflow.def` 和 `/tmp/toyflow_output/jobs/main/forecast.ecf`，可以对照源码检查节点、变量和资源指令的来源。完整产物树见 [toyflow README](https://github.com/cemc-oper/takflow/tree/main/examples/toyflow)。

## 下一步

- **构建新应用**。依次阅读[设计总览](guide/overview.md)、[应用声明](guide/application.md)、[资源层](guide/resource-layers.md)和[标准构建](guide/build.md)。
- **逐文件研究本示例**：阅读 [toyflow README](https://github.com/cemc-oper/takflow/tree/main/examples/toyflow)，查看文件职责、产物树和可选凭证/观测能力。
- **参考真实标准应用**：进入 {ref}`MCV S1 真实应用参考 <mcv-s1-reference>`。
