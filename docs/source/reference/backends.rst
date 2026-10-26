takflow.backends — 转换层
=========================

把抽象流程定义转换为具体运行形式：ecFlow ``.def``、takler flow、
``#ORVIX`` / ``slsubmit6`` 运行时提交描述。

工作流后端只有 ecFlow 和 takler；shell 是生成模式，orvix/slsubmit6 是资源载体，
都不是额外的 ``WorkflowBackend``。公共操作的支持状态、显式不支持路径和语义差异见
:doc:`../guide/backends` 的能力矩阵。

takflow.backends.ecflow
-----------------------

.. automodule:: takflow.backends.ecflow
   :members:
   :show-inheritance:

takflow.backends.ecflow.serializer
----------------------------------

折叠进来的纯 Python ecFlow ``.def`` 序列化器（原 light-ecflow），
模拟 ecflow Python API 并输出定义文件。

.. automodule:: takflow.backends.ecflow.serializer
   :members:
   :show-inheritance:

takflow.backends.takler
-----------------------

.. automodule:: takflow.backends.takler
   :members:
   :show-inheritance:

takflow.backends.runtime
------------------------

运行时资源载体适配器：把通用资源模型翻译为调度器相关的运行时变量/指令。

.. automodule:: takflow.backends.runtime
   :members:
   :show-inheritance:
