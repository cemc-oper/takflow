# takflow

![Maturity-Sandbox](https://img.shields.io/badge/Maturity-Sandbox-F9D71C)
![GitHub Release](https://img.shields.io/github/v/release/cemc-oper/takflow)
![PyPI - Version](https://img.shields.io/pypi/v/takflow)
![GitHub License](https://img.shields.io/github/license/cemc-oper/takflow)
![GitHub Action Workflow Status](https://github.com/cemc-oper/takflow/actions/workflows/ci.yml/badge.svg)
[![Documentation Status](https://readthedocs.org/projects/takflow/badge/?version=latest)](https://takflow.readthedocs.io/)

`takflow`（`tak` 取自 takler + `flow`）是面向 CEMC 数值天气预报模式系统的统一工作流生成框架。

它提供了一套通用的配置模型、作业资源描述契约、工作流引擎抽象和渲染工具，让业务工作流生成器专注于领域逻辑，而无需重复实现 ecFlow 定义生成、作业脚本渲染、资源载体切换等通用能力。
目前已应用如下系统流程中（内部访问）：

- mcv-workflow
- cma-gfs-post-workflow

## 安装

要求 Python >= 3.10。

使用 pip 安装最新发布版本：

```bash
pip install takflow
```

或者通过源代码安装最新开发版本：

```bash
git clone https://github.com/cemc-oper/takflow.git
# or in CMA, use metcode
# git clone http://e.mc.met.cma/codingcorp/cemc-takler/takflow.git
cd takflow
pip install .
```

## 快速上手

```python
from takflow.config import BaseWorkflowConfig, load_config_from_file
from takflow.flow import WorkflowEngine
from takflow.backends.ecflow import EcflowBackend


class MyConfig(BaseWorkflowConfig):
    """通用字段(目录、模式、workload、调度)全部继承,只加领域字段。"""


config = load_config_from_file("config/my_config.yaml", config_class=MyConfig)

engine = WorkflowEngine(EcflowBackend())
suite = engine.Suite(config.workflow_name)
suite.add_family("main").add_task("forecast")
```

完整的端到端最小应用见 [`examples/toyflow/`](examples/toyflow/README.md)。

## 文档

在线文档：<https://takflow.readthedocs.io/>

本地构建：

```bash
uv sync --group docs
cd docs && make html
```

- [快速上手](docs/source/quickstart.md)
- 使用指南：[配置](docs/source/guide/config.md) · [jobspec](docs/source/guide/jobspec.md) ·
  [流程与钩子](docs/source/guide/flow-and-hooks.md) ·
  [后端与资源载体](docs/source/guide/backends.md) · [构建 CLI](docs/source/guide/cli.md)
- [架构设计](docs/source/develop/architecture.md) · [jobspec 契约](docs/source/reference/jobspec-schema.md)

## 许可

`takflow` 采用 Apache-2.0 许可证。
