takflow.flow.backends — 转换层
================================

把抽象流程定义转换为具体运行形式：ecFlow ``.def``、takler flow、
``#ORVIX`` / ``slsubmit6`` 运行时提交描述。

工作流后端只有 ecFlow 和 takler；shell 是生成模式，orvix/slsubmit6 是资源载体，
都不是额外的 ``WorkflowBackend``。公共操作的支持状态、显式不支持路径和语义差异见
:doc:`../guide/backends` 的能力矩阵。

takflow.flow.backends.ecflow
----------------------------

.. automodule:: takflow.flow.backends.ecflow
   :members:
   :show-inheritance:

takflow.flow.backends.ecflow.serializer
---------------------------------------

折叠进来的纯 Python ecFlow ``.def`` 序列化器（原 light-ecflow），
模拟 ecflow Python API 并输出定义文件。

.. automodule:: takflow.flow.backends.ecflow.serializer
   :members:
   :show-inheritance:

takflow.flow.backends.takler
----------------------------

.. automodule:: takflow.flow.backends.takler
   :members:
   :show-inheritance:

takflow.jobs.submission
-----------------------

绑定提交命令、取消命令和节点资源。迁移旧导入时参见 :doc:`../guide/backends`。

.. automodule:: takflow.jobs.submission
   :members:

.. automodule:: takflow.jobs.submission.variables
   :members:

.. automodule:: takflow.jobs.submission.direct
   :members:

.. automodule:: takflow.jobs.submission.orvix
   :members:

.. automodule:: takflow.jobs.submission.slsubmit6
   :members:
