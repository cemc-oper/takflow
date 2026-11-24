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

标准应用通过 `Application` 声明配置、资源和领域 suite builder，再由标准构建消费同一个有效上下文：

```python
from pathlib import Path

from takflow.application import Application, ApplicationBrand
from takflow.build import build
from takflow.config import BaseWorkflowConfig


class MyConfig(BaseWorkflowConfig):
    """通用字段由框架继承，这里只添加领域字段。"""


def create_suite(config, engine):
    suite = engine.Suite(config.workflow_name)
    suite.add_family("main").add_task("forecast")
    return suite


application = Application(
    config_type=MyConfig,
    resources=Path("src/my_workflow/resources"),
    suite_builder=create_suite,
    brand=ApplicationBrand("my-workflow", "0.1.0"),
)

with application.prepare("config/my_config.yaml", output_repo_base="build") as context:
    result = build(context)
```

应用的资源目录还需提供配置、作业模板和静态脚本。完整的底层 API 与旧 CLI 示例见 [`examples/toyflow/`](examples/toyflow/README.md)；标准应用路径见[设计总览](docs/source/guide/overview.md)和[应用声明](docs/source/guide/application.md)。

## 文档

在线文档：<https://takflow.readthedocs.io/>

## 许可

`takflow` 采用 Apache-2.0 许可证。
