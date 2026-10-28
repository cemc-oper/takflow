# 架构设计

takflow 按职责分为七层，上层应用（如 `mcv-workflow`）只与其中几层直接交互：

- **配置层 `config/`**：基于 Pydantic v2 的 `BaseWorkflowConfig`、
  `SlurmWorkload` / `ShellWorkload`、调度配置等，只负责"配置输入 → Python 对象"。
- **资源模型层 `jobspec/`**：面向应用的 `TaskResource`（serial/parallel）向下编译成与
  `orvix` 对齐的扁平 `ResourceSpec`。
- **抽象层 `flow/`**：与后端无关的流程定义 API（`WorkflowEngine`、`Node`、
  `WorkflowBackend`、Hook 注册表），同一套节点树可在公共支持子集上生成 ecFlow `.def` 或
  takler JSON；后端差异见[能力矩阵](../guide/backends.md)。
- **生成编排层 `generation.py`**：统一 definition/shell 模式分发、输出路径解析和保存
  前后回调顺序；应用注入领域 builder/renderer，shell 分支不创建后端或引擎。
- **转换层 `backends/`**：把抽象定义转换为具体运行形式：
  - `backends/ecflow/` → ecFlow `.def`
  - `backends/takler/` → takler flow
  - `backends/runtime/` → `#ORVIX` / `slsubmit6` 运行时提交描述
- **工具层 `toolkit/`**：为上层应用构建 CLI 提供可复用能力（渲染作业模板、复制静态资源、
  渲染凭证文件）。
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
├── generation.py           # 生成编排层（模式分发 / 路径 / 保存回调）
├── backends/               # 转换层
│   ├── ecflow/             # ecFlow .def 后端（含折叠进来的 light-ecflow 序列化器）
│   ├── takler/             # takler 后端
│   └── runtime/            # orvix / slsubmit6 运行时载体
└── toolkit/                # 工具层（job / resource / credential / util）
```

## 与运行时工具的关系

- **orvix**（Go，HPC 作业提交层）：消费 `#ORVIX` 指令与 jobspec schema，
  把作业脚本翻译为 `#SBATCH`（slurm）/ `#DSUB`（donau）等并提交。
  takflow 通过 `backends/runtime/orvix` 生成它的输入。
- **takler**（Python 工作流调度器）：ecFlow 之外的另一个引擎后端，
  由 `backends/takler` 输出其 flow 定义。

## 设计取向

- **Hook 词汇表归应用**：takflow 只提供注册表机制（`BaseHookRegistry`），
  不预定义任何领域 hook 点；各应用定义自己的 `EngineHookPoint` 枚举与上下文。
- **生成职责分层**：`config generate` 与领域 suite/shell 构建仍由应用实现；
  `workflow generate` 的模式分发、输出路径和保存编排由 `takflow.generation` 提供，
  应用 CLI 与历史选项保持独立，详见[生成服务设计](generation-service.md)。
- **凭证渲染是共享注册表**：与 engine hook 不同，credential hook 使用 takflow 全局
  注册表，业务包与业务扩展包按优先级向同一文件贡献片段。
