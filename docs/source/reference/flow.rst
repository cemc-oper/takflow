takflow.flow — 抽象层
=====================

与后端无关的流程定义 API：``WorkflowEngine``、``Node``、``WorkflowBackend``、Hook 注册表。
同一套节点树可在两个后端共同支持的子集上生成 ecFlow ``.def`` 或 takler JSON；
label、late、repeat-day 等差异及显式不支持路径见 :doc:`../guide/backends` 的能力矩阵。

takflow.flow.node
-----------------

.. automodule:: takflow.flow.node
   :members:
   :show-inheritance:

takflow.flow.backend
--------------------

.. automodule:: takflow.flow.backend
   :members:
   :show-inheritance:

takflow.flow.hook
-----------------

.. automodule:: takflow.flow.hook
   :members:
   :show-inheritance:
