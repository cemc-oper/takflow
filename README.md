# takflow

![Maturity-Sandbox|112](https://img.shields.io/badge/Maturity-Sandbox-F9D71C)


`takflow`（`tak` 取自 task/takler + `flow`）是面向 CEMC 数值天气预报模式系统的统一工作流生成框架。

它提供了一套通用的配置模型、作业资源描述契约、工作流引擎抽象和渲染工具，让业务工作流生成器（如 `mcv-workflow`、`mcv-oper-workflow`）专注于领域逻辑，而无需重复实现 ecFlow 定义生成、作业脚本渲染、资源载体切换等通用能力。

- **统一配置**：基于 Pydantic v2 的 `BaseWorkflowConfig`、`SlurmWorkload` / `ShellWorkload`、调度配置等。
- **作业资源契约**：语言无关的 jobspec，生成 `#ORVIX` 指令，由 `orvix` 在提交时翻译为 Slurm / Donau / Local 调度器脚本。
- **引擎抽象**：同一套节点树可同时生成 ecFlow `.def` 或 takler JSON 定义。
- **可扩展钩子**：通过优先级排序的钩子注册表注入业务逻辑（如上传、归档任务）。

## 安装

要求 Python >= 3.9。在依赖它的业务包之前先安装 `takflow`：

```bash
git clone https://github.com/cemc-oper/takflow.git
# or in CMA, use metcode
# git clone http://e.mc.met.cma/codingcorp/cemc-takler/takflow.git
cd takflow
pip install -e ".[dev]"
```

## 快速开始

### 1. 加载配置

```python
from takflow.config import load_config_from_file

config = load_config_from_file("my_config.yaml")
print(config.workflow_mode)        # "shell" 或 "ecflow"
print(config.workload.workload_type)  # "slurm" 或 "shell"
```

### 2. 描述作业资源

`takflow` 使用 `TaskResource` 作为面向应用的串行/并行模型，再编译为与 `orvix` 对齐的扁平 `ResourceSpec`：

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

### 3. 构建工作流

```python
from takflow.engine import WorkflowEngine
from takflow.engine.ecflow import EcflowBackend

engine = WorkflowEngine(EcflowBackend())
suite = engine.Suite("mcv_gfs")
suite.add_variable("FOO", "bar")

main = suite.add_family("main")
fcst = main.add_task("forecast")
fcst.add_trigger("/mcv_gfs/obs == complete")

engine.save_suite(suite, "mcv_gfs.def")
```

切换到 takler 后端只需更换 backend：

```python
from takflow.engine.takler import TaklerBackend

engine = WorkflowEngine(TaklerBackend())
```

### 4. 渲染作业脚本

```python
from takflow.job import render_jobs_from_directory

render_jobs_from_directory(
    config=config,
    repo_base="/path/to/workflow/resources",
    output_repo_base="/path/to/output",
)
```

支持传入有序的目录列表实现分层覆盖（常用于基础包 + 业务扩展包）：

```python
render_jobs_from_directory(
    config=config,
    repo_base=[
        "/path/to/mcv-workflow/resources",
        "/path/to/mcv-oper-workflow/resources",  # 同名模板覆盖上层
    ],
    output_repo_base="/path/to/output",
)
```

### 5. 复制静态资源

```python
from takflow.resource import copy_resources_to_output

copy_resources_to_output(
    output_repo_base="/path/to/output",
    src_base="/path/to/workflow/resources",
)
```

## 资源载体

`SlurmWorkload.submit_carrier` 决定任务资源如何抵达调度器：

| Carrier | 生成内容 | 适用场景 |
|---------|----------|----------|
| `orvix` | `#ORVIX key=value` 指令 + `orvix submit` | `mcv-workflow` 默认 |
| `slsubmit6` | `%QUEUE%` / `%NODES%` / `%WCKEY%` 变量 + `slsubmit6` | `gfs-post` / `meso-post` 规划默认 |

两种 carrier 使用相同的 `TaskResource` 输入，切换只需改配置。

## 扩展：钩子

```python
from takflow.hooks.base import BaseHookRegistry, create_hook_decorator

registry = BaseHookRegistry()
register = create_hook_decorator(lambda: registry)

@register("my.hook.point", priority=10)
def my_hook(ctx):
    # ctx 包含当前 node、component 等上下文
    ctx.node.add_family("extra")
```

`takflow.credential.hooks` 也提供了共享的凭据渲染钩子注册表。

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
