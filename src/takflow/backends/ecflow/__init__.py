"""
ecflow 后端：将 takflow 的抽象流程定义转换为 ecFlow ``.def`` 文件。
"""
from takflow.backends.ecflow.backend import EcflowBackend

__all__ = ["EcflowBackend"]
