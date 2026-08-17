# takflow

![Maturity-Sandbox](https://img.shields.io/badge/Maturity-Sandbox-F9D71C)
![GitHub Release](https://img.shields.io/github/v/release/cemc-oper/takflow)
![PyPI - Version](https://img.shields.io/pypi/v/takflow)
![GitHub License](https://img.shields.io/github/license/cemc-oper/takflow)
![GitHub Action Workflow Status](https://github.com/cemc-oper/takflow/actions/workflows/ci.yml/badge.svg)

`takflow`（`tak` 取自 takler + `flow`）是面向 CEMC 数值天气预报模式系统的统一工作流生成框架。

它提供了一套通用的配置模型、作业资源描述契约、工作流引擎抽象和渲染工具，让业务工作流生成器专注于领域逻辑，而无需重复实现 ecFlow 定义生成、作业脚本渲染、资源载体切换等通用能力。
目前已应用如下系统流程中（内部访问）：

- mcv-workflow
- cma-gfs-post-workflow

## 设计原则

- **配置层 `config/`**：基于 Pydantic v2 的 `BaseWorkflowConfig`、`SlurmWorkload` / `ShellWorkload`、调度配置等，只负责"配置输入 → Python 对象"。
- **资源模型层 `jobspec/`**：面向应用的 `TaskResource`(serial/parallel) 向下编译成与 `orvix` 对齐的扁平 `ResourceSpec`。
- **抽象层 `flow/`**：与后端无关的流程定义 API（`WorkflowEngine`、`Node`、`WorkflowBackend`、Hook 注册表），同一套节点树可同时生成 ecFlow `.def` 或 takler JSON。
- **转换层 `backends/`**：把抽象定义转换为具体运行形式：
  - `backends/ecflow/` → ecFlow `.def`
  - `backends/takler/` → takler flow
  - `backends/runtime/` → `#ORVIX` / `slsubmit6` 运行时提交描述
- **工具层 `toolkit/`**：为上层应用构建 CLI 提供可复用能力（渲染作业模板、复制静态资源、渲染凭证文件）。
- **契约层 `spec/jobspec/`**：语言无关的作业运行资源契约，`takflow` 为唯一 owner，`orvix` 只读/对拍校验。

## 安装

要求 Python >= 3.10。

使用 pip 安装最新发布版本：

```bash
pip install takflow
```

或者通过源代码安装最新开发版本：

```bash
git clone https://github.com/cemc-oper/takflow.git
# or in CMA, use metcode
# git clone http://e.mc.met.cma/codingcorp/cemc-takler/takflow.git
cd takflow
pip install .
```

## 工作流规范(YAML)

`takflow` 从 YAML 文件加载工作流规范。`BaseWorkflowConfig` 定义了通用字段，业务应用通过子类化添加领域字段。

### 通用 YAML 结构

下面以 toyflow 的配置为例（完整文件见 [`examples/toyflow/config/toyflow.yaml`](examples/toyflow/config/toyflow.yaml)）。
通用字段由 `BaseWorkflowConfig` 定义，分隔线以下是由应用子类添加的领域字段：

```yaml
project_base_dir: /path/to/toyflow/project
run_base_dir: /path/to/toyflow/run
workflow_repo_base_dir: /path/to/resources   # 可选,默认使用应用包内 resources/
output_repo_base_dir: /path/to/toyflow/output # 可选
workflow_name: toyflow
workflow_mode: ecflow                        # shell / ecflow / takler
script_invoke_mode: external                 # external / inline

workload:
  workload_type: slurm
  wckey: toyflow
  scheduler: slurm                           # slurm / donau
  submit_carrier: orvix                      # orvix / slsubmit6
  default_serial_queue: serial
  default_parallel_queue: normal

scheduling:                                  # ecflow 模式有效
  scheduling_type: RepeatDate
  start_date: 20250716
  end_date: 20250720

cycles:                                      # ecflow 模式有效
  "00":
    cycle_label: "00"
    time: "00:00"

# ---- 以下为应用领域字段(以 toyflow 为例) ----

enable_obs: true
enable_main: true
enable_post: true

forecast:
  forecast_length: 24
  resource:
    job_type: parallel
    nodes: 2
    ntasks_per_node: 16
    time: "01:00:00"

post_resource:
  job_type: serial
  time: "00:30:00"
```

### 关键字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `project_base_dir` | str | 模式程序/静态数据根目录 |
| `run_base_dir` | str | 运行时工作目录 |
| `workflow_repo_base_dir` | str \| None | 资源模板目录,None 则使用应用自带 `resources/` |
| `output_repo_base_dir` | str \| None | 生成产物输出目录 |
| `workflow_name` | str | 工作流名称 |
| `workflow_mode` | `shell` / `ecflow` / `takler` | 输出模式 |
| `script_invoke_mode` | `external` / `inline` | 作业脚本是外部引用还是内联 |
| `workload` | `SlurmWorkload` / `ShellWorkload` | 工作负载配置(判别联合) |
| `scheduling` | `SchedulingConfig` \| None | ecFlow 时间调度 |
| `cycles` | `dict[str, CycleConfig]` \| None | 预报启动循环配置 |
| `housekeep` | `HousekeepConfig` \| None | 清理配置 |

### 负载配置

#### `SlurmWorkload`

```yaml
workload:
  workload_type: slurm
  wckey: myproject
  scheduler: slurm
  submit_carrier: orvix
  default_serial_queue: serial
  default_parallel_queue: normal
  application: op_grapes_gfs
```

| 字段 | 默认值 | 说明 |
|---|---|---|
| `wckey` | 必填 | 项目/计费关键字(映射到 slurm `--wckey`) |
| `scheduler` | `slurm` | orvix 目标调度器:`slurm` / `donau` |
| `submit_carrier` | `orvix` | 资源载体:`orvix`(默认) / `slsubmit6` |
| `default_serial_queue` | `serial` | 串行任务默认队列 |
| `default_parallel_queue` | `normal` | 并行任务默认队列 |
| `application` | None | 应用标签(映射到 slurm `--comment`) |

#### `ShellWorkload`

```yaml
workload:
  workload_type: shell
```

无调度器，任务直接以 shell 脚本运行。

## 使用方法

> **完整示例**：想看一个端到端可运行的最小应用（config 子类化 → 节点树 → hook →
> 4 步 CLI → 生成 `.def`），见 [`examples/toyflow/`](examples/toyflow/README.md)。
> 下面的章节按层讲解各个概念。

### 1. 定义配置

应用子类化 `BaseWorkflowConfig`，添加领域字段，然后使用 `load_config_from_file` 加载 YAML（对应 toyflow 的 `src/toyflow/config.py`）：

```python
from pydantic import BaseModel

from takflow.config import BaseWorkflowConfig, load_config_from_file
from takflow.jobspec import TaskResource


class ForecastConfig(BaseModel):
    """预报步骤的领域配置。"""

    forecast_length: int = 24
    # 预报任务的资源需求(serial/parallel 高层模型,生成时编译为 #ORVIX 指令)
    resource: TaskResource = TaskResource(job_type="parallel", nodes=2, ntasks_per_node=16)


class ToyflowConfig(BaseWorkflowConfig):
    """通用字段(目录、模式、workload、调度)全部继承,这里只声明领域字段。"""

    enable_obs: bool = True
    enable_main: bool = True
    enable_post: bool = True

    forecast: ForecastConfig = ForecastConfig()
    post_resource: TaskResource = TaskResource(job_type="serial")


config = load_config_from_file("config/toyflow.yaml", config_class=ToyflowConfig)
print(config.workflow_mode)
print(config.workload.submit_carrier)
```

#### 1.1 作业资源描述

配置中的任务资源使用 `TaskResource` 作为面向应用的串行/并行模型，再编译为与 `orvix` 对齐的扁平 `ResourceSpec`：

```python
from takflow.config import SlurmWorkload
from takflow.jobspec import TaskResource, to_orvix_directives

workload = SlurmWorkload(wckey="toyflow")  # 其余字段取默认值

tr = TaskResource(
    job_type="parallel",
    nodes=2,
    ntasks_per_node=16,
    time="01:00:00",
)

spec = tr.compile(workload)
print("\n".join(to_orvix_directives(spec)))
```

输出：

```text
#ORVIX scheduler=slurm
#ORVIX nodes=2
#ORVIX ntasks-per-node=16
#ORVIX time=01:00:00
#ORVIX queue=normal
#ORVIX project=toyflow
```

### 2. 定义运行流程

运行流程通过 `takflow.flow` 中的抽象 API 定义，与后端无关（对应 toyflow 的 `src/toyflow/flow.py`）：

```python
from takflow.flow import WorkflowEngine
from takflow.backends.ecflow import EcflowBackend
from takflow.backends.runtime import common_setting, set_runtime, set_scheduling

engine = WorkflowEngine(EcflowBackend())

suite = engine.Suite(config.workflow_name)

# 资源载体(提交命令)+ 引擎公共设置
set_runtime(suite, config.workload, engine=engine)
suite.add_variables(common_setting(engine=engine))

# admin/ 运维开关
fm_admin = suite.add_family("admin")
fm_admin.set_defstatus_complete()
fm_admin.add_task("toggles")

# time_triggers/ 时间调度
fm_time = suite.add_family("time_triggers")
set_scheduling(fm_time, config.scheduling, engine=engine)
fm_time.add_task("00").add_time("00:00")

# obs -> main -> post 依赖链
fm_obs = suite.add_family("obs")
fm_obs.add_task("prepare")

fm_main = suite.add_family("main")
fcst = fm_main.add_task("forecast")
fcst.add_trigger(f"/{config.workflow_name}/obs/prepare == complete")

fm_post = suite.add_family("post")
plot = fm_post.add_task("plot")
plot.add_trigger(f"/{config.workflow_name}/main/forecast == complete")
```

同一套节点树可以通过不同的后端输出为 ecFlow `.def` 或 takler JSON。

#### 2.1 扩展流程：钩子

takflow 只提供通用基类（`BaseHookRegistry` + `create_hook_decorator`），hook 点的词汇表由应用自己定义（对应 toyflow 的 `src/toyflow/hooks.py`）：

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from takflow.flow import Node, WorkflowEngine
from takflow.flow.hook import BaseHookRegistry, create_hook_decorator


class EngineHookPoint(str, Enum):
    """应用自己的 hook 点(takflow 不预定义)。"""

    AFTER_FORECAST = "main.after_forecast"


@dataclass
class EngineHookContext:
    """engine hook 的上下文:当前 node、engine 及附加参数。"""

    node: Node
    engine: WorkflowEngine
    kwargs: Dict[str, Any] = field(default_factory=dict)


class EngineHookRegistry(BaseHookRegistry[EngineHookContext, None]):
    """应用自有的 engine hook 注册表(单例)。"""

    _instance: Optional["EngineHookRegistry"] = None

    @classmethod
    def get_instance(cls) -> "EngineHookRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


register_engine_hook = create_hook_decorator(EngineHookRegistry.get_instance)


@register_engine_hook(EngineHookPoint.AFTER_FORECAST, priority=10)
def add_verify_task(context: EngineHookContext) -> None:
    """在预报任务之后注入一个检验任务。"""
    verify = context.node.add_task("verify")
    verify.add_trigger("forecast == complete")
```

hook 在 **import 时** 通过装饰器注册；流程构建代码在相应位置执行：

```python
context = EngineHookContext(node=fm_main, engine=engine, kwargs={})
EngineHookRegistry.get_instance().execute(EngineHookPoint.AFTER_FORECAST, context)
```

### 3. 选择后端

`takflow` 通过 `backends/` 提供具体后端实现。应用通常按 `workflow_mode` 从映射表中取后端类，切换后端只需更换 `WorkflowEngine` 构造参数（对应 toyflow 的 `src/toyflow/generate.py`）：

```python
from pathlib import Path

from takflow.flow import WorkflowEngine
from takflow.backends.ecflow import EcflowBackend
from takflow.backends.takler import TaklerBackend

_BACKEND_MAP = {
    "ecflow": EcflowBackend,
    "takler": TaklerBackend,
}
_DEFAULT_SUFFIX = {
    "ecflow": ".def",
    "takler": ".json",
}

mode = config.workflow_mode
engine = WorkflowEngine(_BACKEND_MAP[mode]())
suite = create_suite(config, engine=engine)  # 见第 2 节的节点树构建

output_path = Path(
    config.output_repo_base_dir,
    f"{config.workflow_name}{_DEFAULT_SUFFIX[mode]}",
)
engine.save_suite(suite, output_path)
```

#### 3.1 资源载体

在 slurm workload 下，任务资源通过 `submit_carrier` 决定如何抵达调度器。suite 构建时调用一次 `set_runtime` 即可（对应 toyflow `flow.py` 的 `setup()`）：

```python
from takflow.backends.runtime import set_runtime

set_runtime(suite, config.workload, engine=engine)
# slsubmit6 carrier 还需要任务级资源:set_runtime(node, workload, engine=engine, task_resource=tr)
```

| Carrier | 生成内容 | 适用场景 |
|---------|----------|----------|
| `orvix` | `#ORVIX key=value` 指令 + `orvix submit` | `mcv-workflow` 默认 |
| `slsubmit6` | `%QUEUE%` / `%NODES%` / `%WCKEY%` 变量 + `slsubmit6` | `gfs-post` / `meso-post` 默认 |

两种 carrier 使用相同的 `TaskResource` 输入，切换只需改 YAML 中的 `workload.submit_carrier`。

### 4. 构建命令行接口

`takflow.toolkit` 提供构建 CLI 的原子能力。典型业务应用 CLI 如下（对应 toyflow 的 `src/toyflow/cli.py`，省略了 click 选项声明）：

```python
from pathlib import Path

import click

from takflow.toolkit import (
    copy_resources_to_output,
    render_credential,
    render_jobs_from_directory,
    set_build_info_provider,
)

from toyflow.config import ToyflowConfig, load_config_from_file
from toyflow.generate import toyflow_build_info_lines

# 让 toolkit 渲染的文件头带上应用品牌(否则是通用 takflow 头)
set_build_info_provider(toyflow_build_info_lines)


def _load_config(config_file: str) -> ToyflowConfig:
    # 先 import hooks,触发 @register_engine_hook / @register_credential_hook
    # 的 import 时注册(与 mcv-oper-workflow 的扩展模式一致)
    import toyflow.hooks  # noqa: F401

    return load_config_from_file(config_file, config_class=ToyflowConfig)


@click.group()
def main():
    pass


@main.group()
def resource():
    pass


@resource.command("copy")
@click.option("--config-file", required=True, type=click.Path(exists=True, dir_okay=False))
def resource_copy(config_file: str):
    """Copy static resources (scripts/, ecflow/include/) to OUTPUT_REPO_BASE."""
    config = _load_config(config_file)
    copy_resources_to_output(
        output_repo_base=Path(config.output_repo_base_dir),
        src_base=Path(config.workflow_repo_base_dir),
    )


@main.group()
def job():
    pass


@job.command("generate")
@click.option("--config-file", required=True, type=click.Path(exists=True, dir_okay=False))
def job_generate(config_file: str):
    """Generate job scripts from Jinja2 templates (jobs/**/*.j2)."""
    config = _load_config(config_file)
    render_jobs_from_directory(
        config=config,
        repo_base=config.workflow_repo_base_dir,
        output_repo_base=config.output_repo_base_dir,
    )


@main.group()
def credential():
    pass


@credential.command("generate")
@click.option("--credential-file", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--config-file", required=True, type=click.Path(exists=True, dir_okay=False))
def credential_generate(credential_file: str, config_file: str):
    """Render config/credential.sh from credential.yaml via credential hooks."""
    config = _load_config(config_file)
    render_credential(
        credential_file=credential_file,
        config=config,
        output_repo_base=config.output_repo_base_dir,
        build_info_lines=toyflow_build_info_lines(),
    )


if __name__ == "__main__":
    main()
```

资源/输出目录的解析优先级（CLI 参数 > 配置字段 > 包内 `resources/` 或报错）由应用侧的小工具函数实现，见 toyflow 的 `src/toyflow/util.py`。`config generate` 与 `workflow generate` 两步由应用自己实现（takflow 刻意留给应用），见 toyflow 的 `src/toyflow/generate.py`。

#### 4.1 凭证渲染 Hook

`takflow.toolkit.credential` 提供共享的凭证渲染钩子注册表（对应 toyflow `hooks.py` 的 credential 部分）：

```python
from takflow.toolkit.credential import (
    CredentialContext,
    CredentialHookPoint,
    register_credential_hook,
)


@register_credential_hook(CredentialHookPoint.RENDER, priority=10)
def render_toyflow_credential(context: CredentialContext) -> str:
    """把 credential.yaml 中的应用段渲染为 credential.sh 片段。"""
    toyflow = context.credential.get("toyflow", {})
    return "\n".join(
        [
            "# toyflow API 凭证",
            f'export TOYFLOW_API_HOST="{toyflow.get("api_host", "")}"',
            f'export TOYFLOW_API_KEY="{toyflow.get("api_key", "")}"',
        ]
    )
```

## 包结构速查

```
src/takflow/
├── spec/jobspec/           # 语言无关契约（被 orvix 使用）
├── config/                 # 配置层
├── jobspec/                # 任务资源 Python 模型
├── flow/                   # 抽象层（WorkflowEngine / Node / Hook）
├── backends/               # 转换层
│   ├── ecflow/             # ecFlow .def 后端
│   ├── takler/             # takler 后端
│   └── runtime/            # orvix / slsubmit6 运行时载体
└── toolkit/                # 工具层（job / resource / credential / util）
```

## 测试

```bash
pytest
```

针对 `orvix` 的一致性测试需要 `orvix` 二进制文件：

```bash
ORVIX_BIN=/path/to/orvix pytest tests/test_conformance.py
```

如果未找到 `orvix`，一致性测试会被跳过。修改契约后可重新生成 golden 输出：

```bash
python -m takflow.spec.jobspec.conformance.regen
```

## 许可

`takflow` 采用 Apache-2.0 许可证。
