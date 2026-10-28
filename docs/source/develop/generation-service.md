# 工作流生成服务设计（TF-06）

状态：**设计草案** · 日期：2026-10-28

本文是 TF-06 的四应用对照与最小 API 草案。`takflow.generation` 及下述类型在 TF-07
实现前**不构成公共 API 承诺**；首版只接入 toyflow，不要求 TYM、GFS-POST、MCV 同步修改，
也不据此实现公共 CLI。

## 1. 目标与非目标

生成服务只收敛各应用重复的工作流生成编排：

- 根据 `workflow_mode` 分发 definition 或 shell 生成；
- 选择 ecFlow/takler 后端及 definition 默认后缀；
- 解析输出仓库与 definition 输出路径；
- 固定构建、保存前后回调、保存和结果返回的顺序。

应用继续拥有：

- CLI entry point、历史选项、提示文本和异常展示；
- 领域 config、`config generate` renderer 和路径特异策略；
- suite builder、领域 hooks、enable-aware 规则及组件知识；
- shell runner 模板与渲染、build-info 品牌和可执行位策略；
- resource/job/credential 生成步骤。

shell 是应用生成模式，不是 `WorkflowBackend`。orvix 与 slsubmit6 是资源载体，也不属于
本服务新增的后端类型。

## 2. 当前实现对照

### 2.1 模式、路径与返回值

| 应用 | 当前模式 | 默认 definition 输出 | 输出覆盖 | shell 输出 | 当前返回 |
|---|---|---|---|---|---|
| toyflow | ecFlow、takler；`workflow generate` 不支持 shell | `<output_repo>/<workflow_name>.def` 或 `.json` | Python 可覆盖 output repo；无独立 definition `output` 参数 | 不适用 | `Path` |
| TYM | ecFlow、takler、shell | 同 toyflow | CLI/Python 的 `output` 原样使用；CLI 先解析 output repo | `<output_repo>/workflow/run_job.sh`，`--output` 不适用 | 两种模式均为 `Path` |
| GFS-POST | 仅 ecFlow | **当前工作目录** `<suite_name>.def`，不是 output repo 下 | CLI/Python 可覆盖 `output` 和 output repo；output repo 在建树前回写 config | 不支持 | `{"suite_name", "suite", "output_path"}` |
| MCV | ecFlow、takler、shell | 同 toyflow | definition 的 Python API 支持 `output`；base CLI 不暴露该参数 | 同 TYM 路径 | definition 为 `Path`，shell 为 `None` |

MCV oper 继续是独立入口：其 CLI 暴露 `--output/-o`，但不接受 base 的全部路径选项，
且显式拒绝 shell。统一服务不得借 facade 合并这些选项或改变 oper 的 shell 行为。

### 2.2 build-info、权限和保存顺序

| 应用 | definition build-info / 权限 | 保存顺序及失败语义要点 |
|---|---|---|
| toyflow | 不自动加 definition 头，不额外 chmod；manifest 记录 generator 版本 | 解析并回写 output repo → 建树 → 在内存导出可选 manifest → 保存 definition → 有 manifest 时落盘。manifest 构造失败发生在 definition 保存前 |
| TYM | 保存后前置带 `model_version` 的应用头，并置 ugo+x | 建树 → 保存 definition → 读取文件并注入头部 → chmod |
| GFS-POST | 无 definition 头或额外 chmod | 解析并回写 output repo → 建树 → 确定输出路径并创建父目录 → 保存 → 返回字典 |
| MCV | 无 definition 头或额外 chmod；shell runner 有应用头并置 ugo+x | definition 建树后保存；shell 独立渲染并写文件，不构建节点树 |

后端 `save_suite()` 已负责创建 definition 父目录。服务不引入新的原子替换、权限扩大或
统一头部；否则会在没有业务收益的情况下改变产物和失败后的文件状态。

### 2.3 源码依据

- toyflow：`framework/takflow/examples/toyflow/src/toyflow/generate.py`、`flow.py`、`cli.py`。
- TYM：`app/tym/cma-tym-v4-workflow/src/cma_tym/workflow/generator.py`、`workflow/flow.py`、
  `shell/generator.py`、`cli.py`。
- GFS-POST：`app/gfs-post/cma-gfs-post-workflow/src/cma_gfs_post/workflow/generator.py`、
  `workflow/flow.py`、`cli.py`、`util.py`。
- MCV：`app/mcv/mcv-workflow/src/mcv_workflow/workflow/{generator,definition,shell}.py`，以及
  `app/mcv/mcv-oper-workflow/src/mcv_oper_workflow/cli.py`。

TYM 的入口与建树函数已经分模块，但建树当前仍在 `workflow/flow.py`，不是独立顶层
`flow/` 包。TF-08 的目录级前置是否已完成由 TYM 侧另行评审；本设计不提前将其标为就绪。

## 3. 最小 API 草案

建议新增 `takflow.generation`，只暴露一个编排入口和两个小数据类型：

```python
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from takflow.config import BaseWorkflowConfig
from takflow.flow import Node, WorkflowEngine


@dataclass(frozen=True)
class GenerationContext:
    config: BaseWorkflowConfig
    engine: WorkflowEngine
    suite: Node
    output_repo_base: Path
    output_path: Path


@dataclass(frozen=True)
class GenerationResult:
    mode: str
    output_repo_base: Path
    output_path: Path | None
    suite: Node | None


def generate_workflow(
    config: BaseWorkflowConfig,
    *,
    output_repo_base: str | Path | None = None,
    output: str | Path | None = None,
    workflow_repo_base: str | Path | None = None,
    suite_builder: Callable[[BaseWorkflowConfig, WorkflowEngine], Node] | None = None,
    shell_renderer: Callable[
        [BaseWorkflowConfig, Path, str | Path | None], Path | None
    ] | None = None,
    before_save: Callable[[GenerationContext], None] | None = None,
    after_save: Callable[[GenerationContext], None] | None = None,
) -> GenerationResult:
    ...
```

签名表达的是职责，不要求首版引入新的 config 基类字段或领域泛型。应用 facade 可用
lambda 从自己的 `create_suite()` 返回值中提取 `Node`，并保持原有公开返回类型。

### 3.1 参数约定

- `output_repo_base`：遵循 **显式参数 > `config.output_repo_base_dir` > `ValueError`**。
  转成 `Path`，并在调用 builder/renderer 前把字符串值回写 config，保持现有派生变量行为。
- `output`：仅 definition 使用，原样转换为 `Path`，不强制位于 output repo 内，也不改写
  用户提供的后缀。缺省时为 `<output_repo>/<workflow_name><mode_suffix>`。
- `workflow_repo_base`：只作为原始覆盖值传给 shell renderer。包内 resources 默认值和
  `workflow_repo_base_dir` 的完整优先级由应用解析，服务不知道应用包名。
- `suite_builder`：definition 必需，接收 config 与已选后端的 `WorkflowEngine`，返回根
  `Node`。领域 builder 的 dict 返回值由应用适配，不进入服务契约。
- `shell_renderer`：shell 必需，接收 config、已解析 output repo 和原始 resources 覆盖值；
  返回生成路径或应用既有 `None`。
- `before_save` / `after_save`：仅 definition 使用，接收完整只读上下文。用于应用产物、
  保存前校验和保存后收尾，不建立第二套全局 hook 注册表。

服务不接收 `verbose`，不打印应用提示。日志、进度文本、加载/runner 用法提示留在应用 CLI。

## 4. 分发与保存语义

### 4.1 definition

固定顺序为：

1. 校验模式并选择 `ecflow → .def/EcflowBackend`、`takler → .json/TaklerBackend`；
2. 解析并回写 output repo，确定默认或显式 `output`；
3. 创建 `WorkflowEngine`，调用 `suite_builder`；
4. 构造 `GenerationContext`，调用可选 `before_save`；
5. 调用 `engine.save_suite(suite, output_path)`；
6. 调用可选 `after_save`；
7. 返回包含 mode、两个输出路径和 suite 的 `GenerationResult`。

具体约束：

- 不支持的模式和缺失 builder 使用 `ValueError`；后端缺少可选依赖的 `ImportError` 不转换。
- builder、回调和后端异常原样传播，不包装成应用领域异常。
- `before_save` 失败时不调用 `save_suite()`，已有 definition 不被本轮写入。
- `after_save` 失败时 definition 已经保存；异常仍向上抛出，不返回成功结果，也不删除文件。
- 不额外引入临时文件、自动重试或事务化多文件写入。多产物一致性仍由应用回调顺序表达。

### 4.2 shell

shell 分支只解析 output repo 并调用 `shell_renderer`：

- **不得实例化 `WorkflowBackend` 或 `WorkflowEngine`，也不得要求 `suite_builder`**；
- 不创建节点树，不选择 definition 后缀，不执行 definition 保存前后回调；
- `output` 在 shell 下不参与路径解析，保持 TYM/MCV 当前“独立 output 不适用于 shell”的
  行为；应用可在自己的 facade 增加更严格校验；
- renderer 决定实际路径和返回值。结果中的 `output_path` 因而允许为 `None`，`suite`
  始终为 `None`。

shell renderer 的模板、build-info、cycles 校验、enable-aware 和可执行位完全归应用。

## 5. build-info、可执行位与错误边界

首版**不向所有 definition 自动注入 build-info，也不统一 chmod**。当前只有 TYM 需要
“保存后头部注入 + ugo+x”，应由其 `after_save` 完成；toyflow 的 manifest 构造/落盘则分别
放在 `before_save` / `after_save`。这样可同时保持：

- toyflow 在 manifest 无效时不先写 definition；
- TYM 的头部品牌和 `model_version` 不进入 takflow；
- GFS-POST/MCV 的 definition 内容和权限不被无意改变；
- shell 与 definition 的应用头部继续各自演进。

`takflow.build_info` 和 job 的 build-info provider 保持现有职责，不新增另一个全局
provider。通用服务只统一**调用时机**，不拥有应用品牌内容。

## 6. 应用 facade 对照

### 6.1 TF-07：仅接入 toyflow

toyflow facade 保留现有 `generate_workflow(config, output_repo_base=None) -> Path`：

- `suite_builder` 直接使用现有 `create_suite(config, engine)`；
- `before_save` 调用现有 `_task_mappings()` 和 `export_definition_manifest()`，把结果暂存于
  本次调用的局部闭包；
- `after_save` 仅在 manifest 非空时调用 `write_definition_manifest()`；
- 返回 `result.output_path`，CLI、observability 开关和 manifest 文件名不变。

不得新增 definition 头、chmod、shell 支持或 CLI 选项。新旧生成行为以零差异为目标，尤其
覆盖 observability 禁用、配置无效、manifest 校验失败和重复生成。

### 6.2 后续消费者，仅记录映射，不在 TF-07 切换

| 应用 | 未来 facade 需要保留的适配 |
|---|---|
| TYM | builder 提取 `result["suite"]`；`after_save` 调现有头部注入；shell 包装现有 renderer 并返回 `Path`；CLI 提示不变 |
| GFS-POST | builder 提取 `result["suite"]`；facade 将默认 `output` 显式设为当前目录 `<suite_name>.def`；把统一结果重新组成原字典 |
| MCV | builder 提取 `result["suite"]`；shell 包装现有 renderer 并保留 `None`；base/oper 各自维护 CLI 选项和 shell 限制 |

真实应用推广仍按 **TYM → GFS-POST → MCV**，每次单独做消费者 golden diff。TF-08 未启动不妨碍
toyflow 验证服务，但也不得把 toyflow 成功写成真实应用已经验证。

## 7. toolkit 与兼容策略

以下 API 原样保留，不因新服务移动或改名：

- resource：`copy_resources_to_output`、`make_scripts_executable`；
- job：`render_jobs_from_directory`、`render_single_job_file`、
  `generate_output_log_data`、`set_build_info_provider`；
- credential：现有渲染与共享注册表入口；
- observability：`export_definition_manifest`、`write_definition_manifest` 等；
- runtime：`takflow.backends.runtime` 及 `takflow.toolkit.util` 的既有兼容 facade。

新服务不吞并 `resource/config/job/credential` 命令。可逐步转为兼容 facade 的是**各应用**
`generate_workflow()` 的重复编排，而不是上述 takflow toolkit 原子能力。私有
`_BACKEND_MAP`、`_DEFAULT_SUFFIX` 可在消费者接入时删除，公共入口按各应用兼容策略保留。

TF-09 仍独立评审公共 CLI；本设计不预设需要 `takflow.cli`。

## 8. TF-07 实施验收清单

- 默认输出、显式 output、缺失 output repo、不支持模式和缺失回调均有测试；
- shell 用测试 renderer 验证不创建后端/引擎，definition hooks 不被误调用；
- builder → before_save → save → after_save 顺序及两类失败后的文件状态有测试；
- toyflow 新旧 definition、manifest 和配置驱动产物只有已声明差异，目标为零行为差异；
- toyflow CLI 不改，未接入的 TYM/GFS-POST/MCV 不改；
- 现有源码测试、jobspec conformance、CI 和安装后 wheel 冒烟继续通过；
- 文档将草案状态更新为实际公共 API 后，才能按兼容策略承诺新入口。
