# 架构设计

TakFlow 将应用准备、流程生成、作业渲染和产物检查放在各自的模块。业务应用通过 `takflow.application` 声明能力，由 `takflow.build` 执行标准构建。

- **配置层 `config/`** 基于 Pydantic v2 组织 `BaseWorkflowConfig`、`SlurmWorkload`、
  `ShellWorkload` 和调度配置。凭证钩子与渲染由 `config/credentials.py` 提供。
- **资源模型层 `jobspec/`**：面向应用的 `TaskResource`（serial/parallel）向下编译成与
  `orvix` 对齐的扁平 `ResourceSpec`。
- **抽象层 `flow/`**：与后端无关的流程定义 API（`WorkflowEngine`、`Node`、
  `WorkflowBackend`、Hook 注册表），同一套节点树可在公共支持子集上生成 ecFlow `.def` 或
  takler JSON；后端差异见[能力矩阵](../guide/backends.md)。
- **生成编排层 `flow/generate.py`**：统一 definition/shell 模式分发、输出路径解析和保存
  前后回调顺序；应用注入领域 builder/renderer，shell 分支不创建后端或引擎。
- **引擎后端与作业生成** 根据流程定义和资源生成引擎定义、作业与运行设置。
  - `flow/backends/ecflow/` → ecFlow `.def`
  - `flow/backends/takler/` → takler flow
  - `flow/scheduling.py` 和 `flow/backend.py` → 调度、通用设置和任务脚本命令
  - `jobs/render.py`、`jobs/scripts.py`、`jobs/headers.py` → 模板渲染、脚本调用和资源头
  - `jobs/provenance.py` → 作业、嵌入脚本和 include 的来源标签与注释块
  - `jobs/submission/` → direct、orvix、slsubmit6 提交和取消命令及节点资源声明
- **应用声明和构建** 由 `application/prepare.py` 准备有效配置、扩展和资源层。
  `build/pipeline.py` 编排完整与分步构建，`build/assets.py` 复制静态资源，
  `build/runtime_config.py` 写出运行配置，`build/result.py` 定义结果，`build/manifest.py` 发布成功清单。
- **产物检查 `checks/`** 提供生成诊断、能力预检和独立检查。`checks/_native.py` 在单独的进程中执行原生任务展开。
- **文件头和观测** 由 `build_info.py` 提供本轮生成器信息，`observability.py` 提供 Sledra 运行环境和定义清单导出。
- **包内资源 `resources/`** 由应用声明选择，随构建复制运行脚本和 include。
- **契约层 `spec/jobspec/`**：语言无关的作业运行资源契约的 vendor 只读副本
  （唯一 owner 是 `orvix`，本仓库 pin + 消费侧对拍校验），外加 Python 渲染器
  harness。详见 [jobspec 契约](../reference/jobspec-schema.md)。

## 包结构速查

```text
src/takflow/
├── spec/jobspec/           # 语言无关契约的 vendor 副本（owner 是 orvix）+ 渲染器 harness
├── config/                 # 配置层
├── jobspec/                # 任务资源 Python 模型
├── flow/                   # 抽象层（WorkflowEngine / Node / Hook）
│   ├── backend.py           # 后端抽象、通用设置和脚本命令
│   ├── scheduling.py       # 将调度规则应用到节点
│   ├── generate.py         # 模式分发、路径和保存回调
│   └── backends/           # ecFlow .def 及 takler flow 后端
├── jobs/                   # 作业渲染、来源追踪、脚本、资源头和提交适配
├── application/            # 应用声明和准备流程
├── build/                  # 阶段、资源、运行配置、结果及成功清单
├── checks/                 # 生成诊断、预检及独立产物检查
├── build_info.py           # 生成器信息与文件头作用域
├── observability.py        # 可选 Sledra 接入
└── resources/              # 随包安装的公共脚本和 include
```

## 与运行时工具的关系

- **orvix**（Go，HPC 作业提交层）：消费 `#ORVIX` 指令与 jobspec schema，
  把作业脚本翻译为 `#SBATCH`（slurm）/ `#DSUB`（donau）等并提交。
  takflow 的 `jobspec` 提供指令渲染，`jobs/submission/orvix.py` 提供提交和取消命令。
- **takler**（Python 工作流调度器）：ecFlow 之外的另一个引擎后端，
  由 `flow/backends/takler` 输出其 flow 定义。

## 设计取向

- **Hook 词汇表归应用**：takflow 只提供注册表机制（`BaseHookRegistry`），
  不预定义任何领域 hook 点；各应用定义自己的 `EngineHookPoint` 枚举与上下文。
- **生成职责分层**。应用提供配置模型、资源模板、领域 suite builder 和 Shell 模板。
  `takflow.build.runtime_config` 渲染并写出运行配置。`takflow.flow.generate` 负责模式分发、输出路径和定义保存。
  [生成服务设计](generation-service.md)
- **凭证片段共享注册表**。业务包与扩展包按优先级向同一文件贡献片段。
  标准应用在 `prepare()` 作用域内组装注册项，退出时恢复先前的注册状态。
