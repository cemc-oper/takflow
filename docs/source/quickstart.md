# 快速上手

本页用一个最小应用 [toyflow](https://github.com/cemc-oper/takflow/tree/main/examples/toyflow)
走通 takflow 的完整链路：配置子类化 → 节点树 → hook → 4 步 CLI → 生成 ecFlow `.def`。

`toyflow` 是一个玩具天气预报系统的工作流生成器，角色相当于 `mcv-workflow` 的袖珍版：
节点树只有 `obs → main → post` 三个任务，但 takflow 的每一层都真实用到。

## 安装

要求 Python >= 3.10。

```bash
pip install takflow
```

或从源码安装最新开发版本：

```bash
git clone https://github.com/cemc-oper/takflow.git
# 在 CMA 内网可使用 metcode:
# git clone http://e.mc.met.cma/codingcorp/cemc-takler/takflow.git
cd takflow
pip install .
```

## 端到端流程

### 1. 定义配置

子类化 `BaseWorkflowConfig`，只声明领域字段；通用字段（目录、模式、workload、调度）全部继承：

```python
from takflow.config import BaseWorkflowConfig, load_config_from_file
from takflow.jobspec import TaskResource


class ToyflowConfig(BaseWorkflowConfig):
    enable_obs: bool = True
    enable_main: bool = True
    enable_post: bool = True
    # 预报任务的资源需求(serial/parallel 高层模型,生成时编译为 #ORVIX 指令)
    # forecast: ForecastConfig = ...
    post_resource: TaskResource = TaskResource(job_type="serial")


config = load_config_from_file("config/toyflow.yaml", config_class=ToyflowConfig)
```

对应文件：`examples/toyflow/src/toyflow/config.py`。详见 [配置](guide/config.md)。

### 2. 定义运行流程

用 `takflow.flow` 中与后端无关的 API 搭节点树：

```python
from takflow.flow import WorkflowEngine
from takflow.backends.ecflow import EcflowBackend
from takflow.backends.runtime import common_setting, set_runtime

engine = WorkflowEngine(EcflowBackend())
suite = engine.Suite(config.workflow_name)

set_runtime(suite, config.workload, engine=engine)
suite.add_variables(common_setting(engine=engine))

fm_obs = suite.add_family("obs")
fm_obs.add_task("prepare")
# ... main / post ...
```

对应文件：`examples/toyflow/src/toyflow/flow.py`。详见 [流程与钩子](guide/flow-and-hooks.md)。

### 3. 选择后端并输出

按 `workflow_mode` 从映射表取后端类，同一套节点树可输出 ecFlow `.def` 或 takler JSON：

```python
from takflow.backends.ecflow import EcflowBackend
from takflow.backends.takler import TaklerBackend

_BACKEND_MAP = {"ecflow": EcflowBackend, "takler": TaklerBackend}
engine = WorkflowEngine(_BACKEND_MAP[config.workflow_mode]())
engine.save_suite(suite, output_path)
```

对应文件：`examples/toyflow/src/toyflow/generate.py`。详见 [后端与资源载体](guide/backends.md)。

### 4. 构建命令行接口

用 `takflow.toolkit` 的原子能力拼出应用的 4 步生成管线：

```python
from takflow.toolkit import copy_resources_to_output, render_jobs_from_directory

# resource copy / job generate / config generate / workflow generate
```

对应文件：`examples/toyflow/src/toyflow/cli.py`。详见 [构建 CLI](guide/cli.md)。

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

## 下一步

- [examples/toyflow/README.md](https://github.com/cemc-oper/takflow/tree/main/examples/toyflow)
  逐文件讲解每一层在 toyflow 中的落点，是跟着做的最佳材料。
- 真实应用可参考 `mcv-workflow` / `mcv-oper-workflow`（内部仓库）。
