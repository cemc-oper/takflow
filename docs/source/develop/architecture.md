# 架构设计

takflow 按职责分为七层，上层应用（如 `mcv-workflow`）只与其中几层直接交互：

- **配置层 `config/`**：基于 Pydantic v2 的 `BaseWorkflowConfig`、
  `SlurmWorkload` / `ShellWorkload`、调度配置等，只负责"配置输入 → Python 对象"。
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
  - `jobs/submission/` → direct、orvix、slsubmit6 提交和取消命令及节点资源声明
- **应用声明和构建** 在 `application/` 准备有效配置和资源层，在 `build/` 生成整套产物。凭证钩子与渲染位于 `config/credentials.py`。
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
│   ├── scheduling.py       # 将调度规则应用到节点
│   ├── generate.py         # 模式分发、路径和保存回调
│   └── backends/           # ecFlow .def 及 takler flow 后端
├── jobs/                   # 作业渲染、脚本、资源头和提交适配
├── application/            # 应用声明和准备流程
└── build/                  # 资源复制、配置与阶段执行
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
- **生成职责分层**：`config generate` 与领域 suite/shell 构建仍由应用实现；
  `workflow generate` 的模式分发、输出路径和保存编排由 `takflow.flow.generate` 提供，
  应用 CLI 与历史选项保持独立，详见[生成服务设计](generation-service.md)。
- **凭证渲染是共享注册表**：与 engine hook 不同，credential hook 使用 takflow 全局
  注册表，业务包与业务扩展包按优先级向同一文件贡献片段。
