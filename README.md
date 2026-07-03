# takflow

`takflow`（`tak` 取自 task/takler + `flow`）是 MCV 数值天气预报模式及相关 CMA 后处理系统的统一工作流生成框架。

它将原先在 `mcv-workflow`、`cma-gfs-post-workflow` 和 `cma-meso-1km-post-workflow` 中重复出现的通用层抽象出来，并吸收独立项目 `light-ecflow` 作为序列化后端，同时为 Go 工具 `orvix` 定义了**作业运行资源描述契约**（jobspec）。

完整设计、迁移计划与阶段历史请见 `../TAKFLOW_DESIGN.md`。

## 状态

**Phase 0–2 已实现。** 当前 `takflow` 已被以下项目使用：

- `mcv-workflow`
- `mcv-oper-workflow`

Phase 3（将 `gfs-post` 和 `meso-post` 迁移到 `takflow`）已规划，但尚未启动。

## 包概览

```
src/takflow/
├── __init__.py              # 版本 / 构建信息辅助
├── build_info.py            # 通用构建信息生成
├── config/                  # Pydantic v2 工作流配置
│   ├── __init__.py
│   ├── workflow.py          # BaseWorkflowConfig, load_config_from_file
│   ├── workload.py          # BaseWorkload, SlurmWorkload, ShellWorkload
│   └── scheduling.py        # CycleConfig, SchedulingConfig 等
├── jobspec/                 # 作业运行资源契约
│   ├── __init__.py
│   ├── model.py             # ResourceSpec（19 键扁平模型）
│   ├── highlevel.py         # TaskResource（面向应用的串行/并行模型）
│   └── render.py            # #ORVIX 指令渲染器
├── spec/jobspec/            # jobspec 权威契约文件
│   ├── jobspec.schema.json  # 权威 JSON Schema（orvix 会引入只读副本）
│   ├── VERSION              # 契约版本，当前为 1.0.0
│   └── conformance/         # 一致性向量与期望输出
├── engine/                  # 后端无关的工作流引擎
│   ├── __init__.py
│   ├── backend.py           # WorkflowBackend, Node, NodeType, WorkflowEngine
│   ├── ecflow.py            # EcflowBackend → takflow.serialize.ecflow
│   └── takler.py            # TaklerBackend（实验/规划中）
├── serialize/ecflow/        # 并入的纯 Python ecFlow .def 序列化器
│   ├── __init__.py
│   ├── defs.py              # Defs / Suite / Family / Task
│   ├── node.py              # 节点层级 + RepeatDate/RepeatDay/Clock
│   └── attributes.py        # Edit / Trigger / Complete / Late 等
├── hooks/                   # 通用钩子注册核心
│   ├── __init__.py
│   └── base.py              # BaseHookRegistry, create_hook_decorator
├── credential/              # 共享凭据渲染
│   ├── __init__.py
│   ├── hooks.py             # CredentialHookPoint + register_credential_hook
│   └── render.py            # render_credential() + render_credential_template()
├── job/                     # Jinja2 作业渲染辅助
│   └── __init__.py
├── resource/                # 静态资源复制辅助
│   ├── __init__.py
│   └── copy.py
└── util/                    # 运行时辅助
    ├── __init__.py
    └── runtime.py           # set_runtime, script_cmd_*, orvix_job
```

## 核心概念

### jobspec 契约

`takflow.spec.jobspec.jobspec.schema.json` 是权威、语言无关的作业运行资源描述。它定义了 19 个扁平键：

| 键 | 说明 |
|-----|-------------|
| `scheduler` | 目标调度器（`slurm`、`donau`、`local`） |
| `job-name` | 作业名称 |
| `output` / `error` | 标准输出 / 标准错误路径 |
| `nodes` | 节点数 |
| `ntasks` | 总 MPI 任务数 |
| `ntasks-per-node` | 每节点任务数 |
| `cpus-per-task` | 每任务 CPU 数 |
| `time` |  wall-clock 时限 |
| `queue` | 调度器队列/分区 |
| `account` / `project` / `application` | 计费/项目标签 |
| `exclusive` | 独占节点 |
| `nodelist` | 请求节点列表 |
| `job-type` | 串行/并行提示 |
| `memory` | 内存请求 |
| `dependency` | 作业依赖表达式 |
| `requeue` | takflow 新增键（`false` 对应 Slurm 的 `--no-requeue`） |

前 18 个键的指令解析器由 `orvix` 实现；`requeue` 是 takflow 契约新增的一个中性键。`orvix` 以只读副本方式引入该 schema。

### 从应用模型到指令

```python
from takflow.jobspec import TaskResource

# 面向应用的串行/并行模型
tr = TaskResource(
    name="forecast",
    parallel=True,
    nodes=4,
    ntasks=64,
    ntasks_per_node=16,
    cpus_per_task=2,
    time="01:30:00",
    queue="normal",
)

# 编译为扁平 ResourceSpec
spec = tr.to_resource_spec()

# 渲染 #ORVIX 指令
print("\n".join(spec.to_orvix_directives()))
```

### 工作负载配置

```python
from takflow.config import SlurmWorkload, ShellWorkload

# 选择 carrier 的 Slurm 工作负载
slurm = SlurmWorkload(
    scheduler="slurm",
    submit_carrier="orvix",        # 或 "slsubmit6"
    default_serial_queue="serial",
    default_parallel_queue="normal",
)
```

### 资源载体（resource carriers）

`submit_carrier` 字段决定任务资源如何抵达调度器：

- **`orvix`** — 在生成的作业脚本中输出 `#ORVIX key=value` 指令，并设置
  `ECF_JOB_CMD=orvix submit --scheduler %ORVIX_SCHEDULER% %ECF_JOB%`。
  这是 `mcv-workflow` 的默认 carrier。
- **`slsubmit6`** — 输出 ecFlow 变量（`%CLASS%`、`%NODES%`、`%WCKEY%`），并设置
  `ECF_JOB_CMD=slsubmit6 ...`。这是 `gfs-post` / `meso-post` 的规划默认 carrier。

两种 carrier 接收相同的 `TaskResource` 输入；分支逻辑位于
`takflow.util.runtime.set_runtime`。

### 引擎抽象

```python
from takflow.engine import WorkflowEngine, EcflowBackend

engine = WorkflowEngine(EcflowBackend())
suite = engine.create_suite("mcv_gfs")
engine.add_variable(suite, "FOO", "bar")

fam = engine.create_family(suite, "main")
task = engine.create_task(fam, "forecast")

engine.save_suite(suite, "mcv_gfs.def")
```

ecFlow 后端使用 `takflow.serialize.ecflow`，即从 `light-ecflow` 并入的纯 Python 序列化器。

### 钩子

`takflow.hooks.base` 提供了通用的按优先级排序的钩子注册表：

```python
from takflow.hooks.base import BaseHookRegistry, create_hook_decorator

registry = BaseHookRegistry()
register = create_hook_decorator(lambda: registry)

@register("my.hook.point", priority=10)
def my_hook(ctx):
    ...
```

`takflow.credential.hooks` 暴露了一个共享的凭据渲染器注册表。
`mcv-workflow` 和 `mcv-oper-workflow` 都在导入时向同一个全局注册表注册渲染器。

## 安装（开发模式）

`takflow` 必须在依赖它的包之前安装（例如 `mcv-workflow`）：

```bash
cd framework/takflow
pip install -e ".[dev]"
```

## 测试

运行单元测试：

```bash
pytest
```

### 针对 orvix 的一致性测试

一致性测试将示例 `ResourceSpec` 渲染为 `#ORVIX` 脚本，通过
`orvix generate --scheduler <scheduler>` 转换，再与期望 `.submit` 文件做对比。
测试需要 `orvix` 二进制文件；可通过 `ORVIX_BIN` 指定，或将其放入 `PATH`：

```bash
ORVIX_BIN=/path/to/orvix pytest tests/test_conformance.py
```

如果未找到 `orvix` 二进制文件，一致性测试会被跳过（不会失败）。

当有意修改契约后，可重新生成 golden 输出：

```bash
python -m takflow.spec.jobspec.conformance.regen
```

## 使用方

- `app/mcv/mcv-workflow` — MCV 基础工作流生成器。
- `app/mcv/mcv-oper-workflow` — 业务扩展；通过 `mcv_workflow.hooks.engine` 注入上传/归档任务，并通过 `takflow.credential.hooks` 注册额外的凭据渲染器。
