takflow.toolkit — 工具层
========================

为上层应用构建 CLI 提供可复用能力：渲染作业模板、复制静态资源、渲染配置与凭证文件、构建信息头和可选观测导出。

takflow.toolkit.job
-------------------

.. automodule:: takflow.toolkit.job
   :members:
   :show-inheritance:

takflow.toolkit.resource
------------------------

.. automodule:: takflow.toolkit.resource
   :members:
   :show-inheritance:

takflow.toolkit.config
----------------------

旧应用适配器的配置渲染入口。新应用使用 ``takflow.build`` 的 config 阶段，详见 :doc:`../guide/build`；历史边界见 :doc:`../guide/legacy-adapters`。

.. automodule:: takflow.toolkit.config
   :members:
   :show-inheritance:

takflow.toolkit.credential
--------------------------

.. automodule:: takflow.toolkit.credential
   :members:
   :show-inheritance:

takflow.toolkit.observability
-----------------------------

可选 Sledra 配置、任务映射和定义导出接口；启用方式见 :doc:`../guide/observability`。

.. automodule:: takflow.toolkit.observability
   :members:
   :show-inheritance:

takflow.toolkit.util
--------------------

.. automodule:: takflow.toolkit.util
   :members:
   :show-inheritance:

takflow.build_info
------------------

.. automodule:: takflow.build_info
   :members:
   :show-inheritance:
