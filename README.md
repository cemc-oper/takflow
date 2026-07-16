# takflow

![Maturity-Sandbox](https://img.shields.io/badge/Maturity-Sandbox-F9D71C)

`takflow`（`tak` 取自 task/takler + `flow`）是面向 CEMC 数值天气预报模式系统的统一工作流生成框架。

它提供了一套通用的配置模型、作业资源描述契约、工作流引擎抽象和渲染工具，让业务工作流生成器（如 `mcv-workflow`、`mcv-oper-workflow`、`cma-gfs-post-workflow`）专注于领域逻辑，而无需重复实现 ecFlow 定义生成、作业脚本渲染、资源载体切换等通用能力。

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

要求 Python >= 3.9。在依赖它的业务包之前先安装 `takflow`：

```bash
git clone https://github.com/cemc-oper/takflow.git
# or in CMA, use metcode
# git clone http://e.mc.met.cma/codingcorp/cemc-takler/takflow.git
cd takflow
pip install -e ".[dev]"
```

## 工作流规范(YAML)

`takflow` 从 YAML 文件加载工作流规范。`BaseWorkflowConfig` 定义了通用字段，业务应用通过子类化添加领域字段。

### 通用 YAML 结构

```yaml
project_base_dir: /path/to/project
run_base_dir: /path/to/run
workflow_repo_base_dir: /path/to/resources   # 可选,默认使用应用包内 resources/
output_repo_base_dir: /path/to/output        # 可选
workflow_name: mcv_gfs
workflow_mode: ecflow                        # shell / ecflow / takler
script_invoke_mode: external                 # external / inline

workload:
  workload_type: slurm
  wckey: myproject
  scheduler: slurm                           # slurm / donau
  submit_carrier: orvix                      # orvix / slsubmit6
  default_serial_queue: serial
  default_parallel_queue: normal
  application: op_grapes_gfs                 # 可选

scheduling:                                  # ecflow 模式有效
  scheduling_type: RepeatDate
  start_date: 20250716
  end_date: 20250720

cycles:                                      # ecflow 模式有效
  "12":
    cycle_label: "12"
    time: "12:00"

housekeep:                                   # ecflow 模式有效
  clear_day: 3
  time: "23:30"
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

### 1. 定义配置

应用子类化 `BaseWorkflowConfig`，添加领域字段，然后使用 `load_config_from_file` 加载 YAML：

```python
from takflow.config import BaseWorkflowConfig, load_config_from_file
from pydantic import Field
from typing import Literal

class MyWorkflowConfig(BaseWorkflowConfig):
    enable_obs: bool = True
    enable_main: bool = True
    enable_post: bool = True

config = load_config_from_file("my_config.yaml", config_class=MyWorkflowConfig)
print(config.workflow_mode)
print(config.workload.submit_carrier)
```

#### 1.1 作业资源描述

配置中的任务资源使用 `TaskResource` 作为面向应用的串行/并行模型，再编译为与 `orvix` 对齐的扁平 `ResourceSpec`：

```python
from takflow.config import SlurmWorkload
from takflow.jobspec import TaskResource, to_orvix_directives

workload = SlurmWorkload(
    wckey="myproject",
    scheduler="slurm",
    submit_carrier="orvix",
    default_serial_queue="serial",
    default_parallel_queue="normal",
)

tr = TaskResource(
    job_type="parallel",
    nodes=4,
    ntasks_per_node=16,
    time="01:30:00",
    queue="normal",
)

spec = tr.compile(workload)
print("\n".join(to_orvix_directives(spec)))
```

输出：

```text
#ORVIX scheduler=slurm
#ORVIX nodes=4
#ORVIX ntasks-per-node=16
#ORVIX time=01:30:00
#ORVIX queue=normal
#ORVIX project=myproject
```

### 2. 定义运行流程

运行流程通过 `takflow.flow` 中的抽象 API 定义，与后端无关：

```python
from takflow.flow import WorkflowEngine
from takflow.backends.ecflow import EcflowBackend

engine = WorkflowEngine(EcflowBackend())

suite = engine.Suite("mcv_gfs")
suite.add_variable("FOO", "bar")

main = suite.add_family("main")
fcst = main.add_task("forecast")
fcst.add_trigger("/mcv_gfs/obs == complete")

fcst.add_event("ready")
fcst.add_meter("progress", 0, 100)
```

同一套节点树可以通过不同的后端输出为 ecFlow `.def` 或 takler JSON。

#### 2.1 扩展流程：钩子

通过 `takflow.flow.hook` 的优先级排序注册表注入业务逻辑：

```python
from takflow.flow.hook import BaseHookRegistry, create_hook_decorator

registry = BaseHookRegistry()
register = create_hook_decorator(lambda: registry)

@register("my.hook.point", priority=10)
def my_hook(ctx):
    # ctx 包含当前 node、component 等上下文
    ctx.node.add_family("extra")
```

### 3. 选择后端

`takflow` 通过 `backends/` 提供具体后端实现。切换后端只需更换 `WorkflowEngine` 构造参数。

#### 3.1 ecFlow 后端

```python
from takflow.flow import WorkflowEngine
from takflow.backends.ecflow import EcflowBackend

engine = WorkflowEngine(EcflowBackend())
suite = engine.Suite("mcv_gfs")
# ... 构建节点树 ...
engine.save_suite(suite, "mcv_gfs.def")
```

#### 3.2 takler 后端

```python
from takflow.flow import WorkflowEngine
from takflow.backends.takler import TaklerBackend

engine = WorkflowEngine(TaklerBackend())
suite = engine.Suite("mcv_gfs")
# ... 构建节点树 ...
engine.save_suite(suite, "mcv_gfs.json")
```

#### 3.3 资源载体

在 slurm workload 下，任务资源通过 `submit_carrier` 决定如何抵达调度器：

```python
from takflow.backends.runtime import set_runtime

set_runtime(
    node=suite,
    workload_config=config.workload,
    engine=engine,
    task_resource=tr,  # slsubmit6 需要;orvix 忽略
)
```

| Carrier | 生成内容 | 适用场景 |
|---------|----------|----------|
| `orvix` | `#ORVIX key=value` 指令 + `orvix submit` | `mcv-workflow` 默认 |
| `slsubmit6` | `%QUEUE%` / `%NODES%` / `%WCKEY%` 变量 + `slsubmit6` | `gfs-post` / `meso-post` 默认 |

两种 carrier 使用相同的 `TaskResource` 输入，切换只需改 YAML 中的 `workload.submit_carrier`。

### 4. 构建命令行接口

`takflow.toolkit` 提供构建 CLI 的原子能力。典型业务应用 CLI 如下：

```python
import click
from takflow.config import load_config_from_file
from takflow.toolkit import (
    copy_resources_to_output,
    render_credential,
    render_jobs_from_directory,
)

@click.group()
def cli():
    pass

@cli.command()
@click.option("--config-file", required=True)
def resource_copy(config_file):
    config = load_config_from_file(config_file, config_class=MyWorkflowConfig)
    copy_resources_to_output(
        output_repo_base=config.output_repo_base_dir,
        src_base=config.workflow_repo_base_dir,
    )

@cli.command()
@click.option("--config-file", required=True)
def job_generate(config_file):
    config = load_config_from_file(config_file, config_class=MyWorkflowConfig)
    render_jobs_from_directory(
        config=config,
        repo_base=config.workflow_repo_base_dir,
        output_repo_base=config.output_repo_base_dir,
    )

@cli.command()
@click.option("--config-file", required=True)
@click.option("--credential-file", required=True)
def credential_generate(config_file, credential_file):
    config = load_config_from_file(config_file, config_class=MyWorkflowConfig)
    render_credential(
        credential_file=credential_file,
        config=config,
        output_repo_base=config.output_repo_base_dir,
        build_info_lines={"warning": "...", "info": "..."},
    )

if __name__ == "__main__":
    cli()
```

#### 4.1 凭证渲染 Hook

`takflow.toolkit.credential` 提供共享的凭证渲染钩子注册表：

```python
from takflow.toolkit.credential import register_credential_hook, CredentialContext

@register_credential_hook("credential.render", priority=10)
def render_db_credential(ctx: CredentialContext) -> str:
    credential = ctx.credential
    return f'export DB_HOST={credential["db"]["host"]}'
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
