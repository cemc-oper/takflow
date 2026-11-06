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

### ecFlow 业务脚本执行边界

ecFlow 下，`invoke_script()` 对 inline 和 external 都生成独立的 `( ... )`
子 shell。业务 `exit 0` 返回父作业并继续执行 tail；非零退出由父作业的
`set -e` 和退出 trap 上报 abort。head/tail 统一拥有 init/complete/abort，
业务脚本不得重复发送终态通知。括号内开头的 `:` 让仅含注释的占位任务也能执行。

业务中的变量赋值、`cd` 和 shell 选项修改不会传回父作业；后台进程必须在
业务内部等待并检查结果。不要把调用放入 `if`、`&&`、`||` 条件上下文，
否则可能抑制 `set -e`。external 仍按脚本自身解释器和错误处理规则执行，
不自动追加 `bash -e`。shell/takler 后端保持原有调用方式。

模板可以用 `{{ invoke_script('scripts/check.sh', 'literal-argument') }}`
传入字面量位置参数；参数由生成器引用，不进行 shell 表达式展开。
不要在 `{{ invoke_script(...) }}` 后拼接参数。
配置和函数库需要修改当前 shell 时，继续使用 `include_raw()` 或 `source`。

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

## 公共校验与安全诊断

`SchedulingConfig` 校验八位 `YYYYMMDD` 的真实日历日期及 `start_date <= end_date`，同一天和合法闰日均允许。`TaskResource.nodes`、`ntasks_per_node` 显式填写时必须为正整数，`None` 继续表示未指定；原有整数类型转换规则保持。扁平 `ResourceSpec` 的字符串、范围及运行时表达式仍按 orvix 契约保留，不强套高层整数规则。

这些规则在应用模型构造时生效，因此旧 loader 也会在生成资源、作业和定义之前拒绝上述非法值。有效旧配置的业务派生、别名和返回行为保持。日期或资源非法但过去能够加载的输入属于有意收紧，需要修正配置，不能用兼容模式绕过。

新的安全入口适用于需要结构化诊断和有效覆盖的调用：

```python
from takflow.config import ConfigValidationError, load_validated_config

try:
    config = load_validated_config(
        "config.yaml",
        config_class=ToyflowConfig,  # 应用的真实领域类
        overrides={"output_repo_base_dir": "/tmp/toyflow"},
        strict_fields=True,
    )
except ConfigValidationError as error:
    for diagnostic in error.diagnostics:
        print(diagnostic.as_dict())
else:
    # 只有有效配置才进入资源/配置/作业/流程生成。
    print(config.output_repo_base_dir)
```

`validate_config(data, config_class=..., overrides=..., strict_fields=...)` 提供同样的内存映射入口。输入必须是原始 mapping，不接收已构建模型；不通过 `model_dump` 重建模型，以保留省略和显式 `None` 的区别。两个入口均深拷贝输入，先应用覆盖，再调用原配置类的 before/字段/after 验证器，返回原领域类实例。

`overrides` 使用顶层 **canonical 字段名**，整字段替换；嵌套 mapping 作为完整节替换，不做深合并。例如覆盖 scheduling 时须提供该节所需的起止日期。覆盖前移除同一字段的旧 alias，避免原 YAML 的 alias 抢过显式覆盖；因此 GFS 的 machine 等派生能够读取最终输出根。未知覆盖字段始终拒绝。现有应用的简单字符串 alias 可用，AliasPath/AliasChoices 字段的覆盖当前明确报 `CONFIG_OVERRIDE_ALIAS`，不猜测复杂路径。未覆盖的字段和 `None` 不被删除或改写。

### 兼容与严格未知字段路径

原 `load_config_from_file(file_path, config_class)` 的签名、原生异常类型及模型 extra 策略保持，应用历史 CLI 未改为统一展示。新的安全入口默认同样保留配置类的 extra 策略；TYM 原有 `extra="forbid"` 不会被放宽。安全入口的异常为 `ConfigValidationError`，调用者应明确采用这个契约。

`strict_fields=True` 使用 Pydantic 的递归 `extra="forbid"`，在消费者 before 归一化之后拒绝未知字段，包括 workload、TaskResource 等原本会忽略额外键的嵌套模型。它不启用 Pydantic 的严格类型模式，不附带禁用合法历史整数转换。安装此可选能力：

```bash
uv pip install 'takflow[strict-config]'
```

基础依赖仍为 `pydantic>=2.0`；`strict-config` 要求 `pydantic>=2.12`。在没有该官方接口的旧版本上请求 strict 会明确报 `CONFIG_STRICT_UNAVAILABLE`，不会静默按兼容路径执行。标准支撑后续接入时须选择该依赖能力；不通过改写 Pydantic 内部 schema 或替换应用类实现递归校验。

GFS 的路径/default partition alias 与 partition/tasks_per_node 归一化由原应用继续处理。strict 不会忽略归一化后仍剩余的旧键、重复别名或冗余字段。例如旧配置的 `housekeep.workload.workload_type` 不是 `TaskResource` 字段，兼容路径沿用旧忽略行为，严格输入需删除该冗余键。不能承诺每份旧配置未经迁移就能进入严格路径。领域科学校验、目标端文件可用性和业务资格仍归应用/部署检查。

### 稳定诊断格式

每项诊断包含 `code`、`path`（由字段名/索引组成的列表）、受控 `reason` 和负责 `stage`；例子：

```json
{"code":"CONFIG_DATE_INVALID","path":["scheduling","start_date"],"reason":"must be a real calendar date in YYYYMMDD format","stage":"config.validation"}
```

| code | 含义 |
|---|---|
| `CONFIG_DATE_INVALID` / `CONFIG_DATE_ORDER` | 日期不存在/格式错误，或起止倒序 |
| `CONFIG_RESOURCE_POSITIVE` | 高层申请资源非正 |
| `CONFIG_UNKNOWN_FIELD` / `CONFIG_REQUIRED` | 未知字段或必填字段缺失 |
| `CONFIG_TYPE` / `CONFIG_CHOICE` / `CONFIG_RANGE` | 类型/选择/已声明边界错误 |
| `CONFIG_DOMAIN_RULE` / `CONFIG_INVALID` | 领域验证器拒绝对象或其他配置规则不满足 |
| `CONFIG_READ_ERROR` / `CONFIG_YAML_SYNTAX` / `CONFIG_ROOT_TYPE` | UTF-8 文件读取、YAML 语法或顶层结构错误 |
| `CONFIG_OVERRIDES_TYPE` / `CONFIG_OVERRIDE_ALIAS` | 覆盖结构错误或复杂 alias 覆盖不支持 |
| `CONFIG_STRICT_UNAVAILABLE` | 未安装严格字段检查所需的 Pydantic 接口 |

输入读取负责 `config.read`，覆盖负责 `config.overrides`，模型校验负责 `config.validation`。`validation_diagnostics(pydantic_error)` 可用于适配旧入口抛出的 `ValidationError`。诊断不包含 input、ctx、YAML 出错行或任意验证器原始消息；领域验证器消息也可能含敏感值，所以未知/领域错误使用固定原因和对象路径。需要领域细节的应用可基于自己的受控代码补充说明，不应直接打印原始异常。该适配不改变应用验证器的执行和拒绝行为。
