# 架构设计

takflow 按职责分为六层，上层应用（如 `mcv-workflow`）只与其中几层直接交互：

- **配置层 `config/`**：基于 Pydantic v2 的 `BaseWorkflowConfig`、
  `SlurmWorkload` / `ShellWorkload`、调度配置等，只负责"配置输入 → Python 对象"。
- **资源模型层 `jobspec/`**：面向应用的 `TaskResource`（serial/parallel）向下编译成与
  `orvix` 对齐的扁平 `ResourceSpec`。
- **抽象层 `flow/`**：与后端无关的流程定义 API（`WorkflowEngine`、`Node`、
  `WorkflowBackend`、Hook 注册表），同一套节点树可同时生成 ecFlow `.def` 或 takler JSON。
- **转换层 `backends/`**：把抽象定义转换为具体运行形式：
  - `backends/ecflow/` → ecFlow `.def`
  - `backends/takler/` → takler flow
  - `backends/runtime/` → `#ORVIX` / `slsubmit6` 运行时提交描述
- **工具层 `toolkit/`**：为上层应用构建 CLI 提供可复用能力（渲染作业模板、复制静态资源、
  渲染凭证文件）。
- **契约层 `spec/jobspec/`**：语言无关的作业运行资源契约，`takflow` 为唯一 owner，
  `orvix` 只读/对拍校验。详见 [jobspec 契约](../reference/jobspec-schema.md)。

## 包结构速查

```text
src/takflow/
├── spec/jobspec/           # 语言无关契约（被 orvix 使用）
├── config/                 # 配置层
├── jobspec/                # 任务资源 Python 模型
├── flow/                   # 抽象层（WorkflowEngine / Node / Hook）
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
- **生成步骤刻意留白**：`config generate` 与 `workflow generate` 两步由应用自己实现，
  toolkit 只提供原子能力，不规定 CLI 形态。
- **凭证渲染是共享注册表**：与 engine hook 不同，credential hook 使用 takflow 全局
  注册表，业务包与业务扩展包按优先级向同一文件贡献片段。
