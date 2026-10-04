# 配置

`takflow` 从 YAML 文件加载工作流规范。`BaseWorkflowConfig` 定义了通用字段，业务应用通过子类化添加领域字段。

## 通用 YAML 结构

下面以 toyflow 的配置为例（完整文件见 `examples/toyflow/config/toyflow.yaml`）。
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

## 关键字段说明

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

## 负载配置

### `SlurmWorkload`

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

### `ShellWorkload`

```yaml
workload:
  workload_type: shell
```

无调度器，任务直接以 shell 脚本运行。

## 在应用中定义配置

应用子类化 `BaseWorkflowConfig`，添加领域字段，然后使用 `load_config_from_file` 加载 YAML
（对应 toyflow 的 `src/toyflow/config.py`）：

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

配置中的任务资源使用 `TaskResource` 作为面向应用的串行/并行模型，编译方式见 [jobspec](jobspec.md)。
