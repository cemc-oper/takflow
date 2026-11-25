"""toyflow — 基于 takflow 构建工作流生成器的最小完整示例。

toyflow 是一个玩具天气预报系统的工作流生成器，演示 takflow 的全部核心能力：

- ``config``   : 子类化 ``BaseWorkflowConfig``，添加领域字段。
- ``flow``     : 用 ``takflow.flow`` 抽象 API 搭建 obs → main → post 节点树。
- ``hooks``    : 应用自有的 engine hook 注册表 + takflow 共享的 credential hook。
- ``cli``      提供独立的资源、配置、作业、流程和凭证生成命令。
"""

__version__ = "0.1.0"
