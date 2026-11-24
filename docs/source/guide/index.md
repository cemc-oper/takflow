# 使用指南

面向应用开发者：如何用 takflow 构建一个业务工作流生成器。本指南围绕一次构建的生命周期组织，而不是按包目录逐一罗列功能。

建议先阅读[设计总览与职责边界](overview.md)，理解“应用声明 → 有效上下文 → 标准构建 → 产物检查 → 运行环境”的主线；完整示例见[第一个应用：toyflow](../quickstart.md)。

## 按任务选择阅读路径

- **构建新应用**：设计总览 → toyflow 快速上手 → Application → 配置与资源层 → 流程与 jobspec → build/CLI → 产物检查。
- **迁移现有应用**：设计总览中的“标准路径与历史入口” → CLI 迁移与旧接口适配 → Application 与标准构建 → 公共 API 兼容策略。
- **维护框架或契约**：公共 API 与后端能力矩阵 → [jobspec 契约](../reference/jobspec-schema.md) → [版本与兼容管理](../develop/versioning.md)。

```{toctree}
:maxdepth: 1
:caption: 1. 认识框架

overview
```

```{toctree}
:maxdepth: 1
:caption: 2. 构建一个应用

application
config
resource-layers
flow-and-hooks
jobspec
backends
```

```{toctree}
:maxdepth: 1
:caption: 3. 生成、检查与交付

build
cli
generation-checks
observability
```

```{toctree}
:maxdepth: 1
:caption: 4. 兼容与迁移

public-api
legacy-adapters
cli-migration
```
